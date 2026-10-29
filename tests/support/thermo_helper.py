"""Dedicated Thermo helper resolution and caching routines for integration tests."""

from __future__ import annotations

import shutil
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ThermoHelperArchiveError,
    ThermoHelperChecksumError,
    ThermoHelperDownloadError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperVersionError,
)
from rawtrace_qc.thermo import (
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperSpecification,
    ThermoHelperState,
    accept_thermo_license,
    download_thermo_helper_archive,
    get_thermo_helper_status,
    install_thermo_helper,
    verify_thermo_helper_archive,
)

_TESTS_ROOT = Path(__file__).resolve().parents[1]
TEST_HELPER_CACHE_DIR = _TESTS_ROOT / ".cache" / "thermo-helper"
TEST_HELPER_ARCHIVE_CACHE_DIR = TEST_HELPER_CACHE_DIR / "archives"
TEST_HELPER_CACHE_MAX_AGE = timedelta(hours=24)
_CACHE_STAMP_NAME = ".cache-created-at"


def expire_stale_test_cache(
    cache_root: Path = TEST_HELPER_CACHE_DIR, max_age: timedelta = TEST_HELPER_CACHE_MAX_AGE
) -> bool:
    """Delete the whole helper test cache once it is older than `max_age`.

    Cache age is tracked by a stamp file holding the creation time as a Unix
    timestamp, so file modification times are never consulted. A cache without a
    readable stamp is treated as expired. A fresh stamp is written whenever the
    cache is created or purged.

    Args:
        cache_root: Root of the cache to expire. Defaults to `tests/.cache/thermo-helper`.
        max_age: Maximum cache age before it is purged. Defaults to 24 hours.

    Returns:
        True if an existing cache was deleted, otherwise False.
    """
    stamp_path = cache_root / _CACHE_STAMP_NAME
    purged = False
    if cache_root.exists():
        if _read_cache_age(stamp_path) <= max_age.total_seconds():
            return False
        shutil.rmtree(cache_root)
        purged = True
    cache_root.mkdir(parents=True)
    stamp_path.write_text(str(time.time()), encoding="utf-8")
    return purged


def get_or_download_thermo_helper_archive(
    specification: ThermoHelperSpecification = THERMO_HELPER_SPECIFICATION,
    cache_directory: Path = TEST_HELPER_ARCHIVE_CACHE_DIR,
    timeout: float = 60.0,
) -> Path:
    """Return the verified helper archive from the shared test cache.

    Missing or invalid cache entries are downloaded to a temporary sibling file,
    verified against the pinned checksum, and atomically published. Transient
    network failures skip the network-dependent test that requested the archive.

    Args:
        specification: Pinned helper release metadata. Defaults to
            `THERMO_HELPER_SPECIFICATION`.
        cache_directory: Directory for cached release archives. Defaults to
            `tests/.cache/thermo-helper/archives`.
        timeout: Maximum network timeout in seconds. Defaults to 60.0.

    Returns:
        The path to the verified cached archive.

    Raises:
        ThermoHelperArchiveError: If a downloaded archive cannot be read.
        ThermoHelperChecksumError: If a downloaded archive fails checksum verification.
        ThermoHelperDownloadError: If a non-transient failure prevents downloading.
    """
    archive_cache_directory = cache_directory.expanduser().resolve()
    archive_path = archive_cache_directory / specification.asset_name

    if archive_path.is_file():
        try:
            verify_thermo_helper_archive(archive_path, specification=specification)
        except (ThermoHelperArchiveError, ThermoHelperChecksumError):
            pass
        else:
            return archive_path

    archive_cache_directory.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".thermo-helper-download-", dir=archive_cache_directory
        ) as temporary_directory:
            staged_archive = Path(temporary_directory) / specification.asset_name
            download_thermo_helper_archive(staged_archive, specification=specification, timeout=timeout)
            verify_thermo_helper_archive(staged_archive, specification=specification)
            staged_archive.replace(archive_path)
    except ThermoHelperDownloadError as error:
        if _is_transient_network_failure(error):
            pytest.skip(f"Network or proxy prevented the Thermo helper archive download: {error}")
        raise

    return archive_path


def resolve_integration_thermo_helper(
    specification: ThermoHelperSpecification = THERMO_HELPER_SPECIFICATION,
    cache_root: Path = TEST_HELPER_CACHE_DIR,
) -> Path:
    """Resolve a usable ThermoScanHeaderExtractor executable for integration tests.

    Resolution strategy:
    1. Check the real per-user application data directory (read-only). If the
       helper is installed and licensed there, return it.
    2. Fall back to the persistent test cache directory (`tests/.cache/thermo-helper`).
    3. Check status at the test cache. If installed and licensed, return it.
     4. If not installed, install to the test cache. Transient network failures
         trigger a pytest skip; integrity and installation failures propagate.
     5. If installed but unlicensed, accept the cache's license.
     6. Return the ready executable. Version, license, and helper failures remain
         test failures.

    Args:
        specification: Pinned helper specification. Defaults to
            `THERMO_HELPER_SPECIFICATION`.
        cache_root: Root directory for caching the helper across test runs.

    Returns:
        The validated Path to a ready Thermo helper executable.
    """
    if environment.get_platform() != "win32":
        pytest.skip("ThermoScanHeaderExtractor integration requires Windows.")

    real_status = get_thermo_helper_status(specification=specification)
    if real_status.state is ThermoHelperState.READY and real_status.path is not None:
        return real_status.path

    cache_data_dir = cache_root.resolve()
    cache_status = get_thermo_helper_status(data_directory=cache_data_dir, specification=specification)

    if cache_status.state is ThermoHelperState.INVALID_VERSION:
        raise ThermoHelperVersionError(cache_status.message)
    if cache_status.state is ThermoHelperState.READY and cache_status.path is not None:
        return cache_status.path

    if cache_status.state is ThermoHelperState.NOT_INSTALLED:
        archive_path = get_or_download_thermo_helper_archive(
            specification=specification, cache_directory=cache_data_dir / "archives"
        )
        install_thermo_helper(archive_path, data_directory=cache_data_dir, specification=specification, timeout=60.0)
        cache_status = get_thermo_helper_status(data_directory=cache_data_dir, specification=specification)
        if cache_status.state is ThermoHelperState.INVALID_VERSION:
            raise ThermoHelperVersionError(cache_status.message)

    if cache_status.state is ThermoHelperState.UNLICENSED:
        if cache_status.path is None:
            raise ThermoHelperLicenseError(cache_status.message)
        accept_thermo_license(cache_status.path, data_directory=cache_data_dir, specification=specification)
        cache_status = get_thermo_helper_status(data_directory=cache_data_dir, specification=specification)

    if cache_status.state is ThermoHelperState.READY and cache_status.path is not None:
        return cache_status.path

    if cache_status.state is ThermoHelperState.NOT_INSTALLED:
        raise ThermoHelperNotFoundError(cache_status.message)
    if cache_status.state is ThermoHelperState.UNLICENSED:
        raise ThermoHelperLicenseError(cache_status.message)
    if cache_status.state is ThermoHelperState.INVALID_VERSION:
        raise ThermoHelperVersionError(cache_status.message)
    raise RuntimeError(f"Thermo helper is not usable: {cache_status.message}")


def _read_cache_age(stamp_path: Path) -> float:
    try:
        return time.time() - float(stamp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return float("inf")


def _is_transient_network_failure(error: ThermoHelperDownloadError) -> bool:
    cause = error.__cause__
    while cause is not None:
        if isinstance(cause, HTTPError):
            return cause.code in {403, 407, 408, 429, 502, 503, 504}
        if isinstance(cause, (URLError, TimeoutError, ConnectionError)):
            return True
        cause = cause.__cause__
    return False

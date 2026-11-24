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
)
from rawtrace_qc.thermo import (
    THERMO_HELPER_RELEASE,
    ThermoHelperSpecification,
    accept_thermo_license,
    download_thermo_helper_archive,
    extract_thermo_helper_archive,
    is_thermo_helper_supported,
    resolve_thermo_helper_specification,
    verify_thermo_helper_archive,
)

WIN_X64_SPECIFICATION = THERMO_HELPER_RELEASE.specification("win-x64")
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


def resolve_specification_or_skip() -> ThermoHelperSpecification:
    """Resolve the host helper specification or skip the requesting test.

    Returns:
        The helper specification for the current host runtime.
    """
    if not is_thermo_helper_supported():
        pytest.skip(
            f"ThermoScanHeaderExtractor is not supported on platform {environment.get_platform()!r} and machine "
            f"{environment.get_machine()!r}. Supported runtimes are {sorted(THERMO_HELPER_RELEASE.assets)}."
        )
    return resolve_thermo_helper_specification()


def get_or_download_thermo_helper_archive(
    specification: ThermoHelperSpecification | None = None,
    cache_directory: Path = TEST_HELPER_ARCHIVE_CACHE_DIR,
    timeout: float = 60.0,
) -> Path:
    """Return the verified helper archive from the shared test cache.

    Missing or invalid cache entries are downloaded to a temporary sibling file,
    verified against the pinned checksum, and atomically published. Transient
    network failures skip the network-dependent test that requested the archive.

    Args:
        specification: Pinned helper release metadata. If None (default),
            resolve the host specification, skipping the test on unsupported runtimes.
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
    specification = specification or resolve_specification_or_skip()
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
    specification: ThermoHelperSpecification | None = None,
    cache_root: Path = TEST_HELPER_CACHE_DIR,
) -> Path:
    """Resolve a usable ThermoScanHeaderExtractor executable for integration tests.

    Extracts the pinned archive into the test cache (`tests/.cache/thermo-helper`), unless an earlier run already
    did, and accepts the Thermo license with the extracted helper. Call it only while
    `THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR` names a temporary folder, as the session fixture
    `_isolate_thermo_license` in `tests/conftest.py` guarantees, so that the acceptance never reaches the
    license folder of the user. The managed helper of the user is not used.

    Transient network failures skip the test. Integrity, version and other helper failures remain test failures.

    Args:
        specification: Pinned helper specification. If None (default),
            resolve the host specification, skipping the test on unsupported runtimes.
        cache_root: Root directory for caching the helper across test runs.

    Returns:
        The path of the cached helper executable, with the license accepted.
    """
    specification = specification or resolve_specification_or_skip()
    cached_executable = _extract_cached_thermo_helper(specification, cache_root.resolve())
    accept_thermo_license(cached_executable, specification=specification)
    return cached_executable


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


def _extract_cached_thermo_helper(specification: ThermoHelperSpecification, cache_root: Path) -> Path:
    helper_directory = cache_root / "helpers" / specification.version / specification.runtime
    executable = helper_directory / specification.executable_name
    if executable.is_file():
        return executable

    archive_path = get_or_download_thermo_helper_archive(
        specification=specification, cache_directory=cache_root / "archives"
    )
    shutil.rmtree(helper_directory, ignore_errors=True)
    helper_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".thermo-helper-extract-", dir=helper_directory.parent
    ) as temporary_directory:
        staged_executable = extract_thermo_helper_archive(
            archive_path, Path(temporary_directory) / "extracted", specification=specification
        )
        staged_executable.parent.replace(helper_directory)
    return executable

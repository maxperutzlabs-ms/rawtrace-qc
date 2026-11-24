"""Expose and accept the ThermoScanHeaderExtractor license agreement."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rawtrace_qc.errors import (
    ThermoHelperConfigError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
)
from rawtrace_qc.thermo import locator
from rawtrace_qc.thermo.runner import thermo_config_directory
from rawtrace_qc.thermo.specification import (
    ThermoHelperSpecification,
    resolve_thermo_helper_specification,
)

_CONFIG_ERROR_EXIT_CODE = 5


def get_thermo_license_text(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
    timeout: float = 10.0,
) -> str:
    """Return the Thermo license agreement without accepting it.

    Runs the pinned helper's `--thermo-license` command and returns its output
    unchanged. This operation does not create or modify the acceptance marker.

    Args:
        explicit_path: Optional helper executable or containing directory.
            Defaults to None.
        data_directory: Application data directory override. If None (default),
            uses the platform-specific user data directory.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.
        timeout: Maximum command time in seconds. Defaults to 10.0.

    Returns:
        The license agreement text printed by the helper.

    Raises:
        UnsupportedPlatformError: If the current runtime has no pinned helper
            release.
        ThermoHelperNotFoundError: If no helper executable is found.
        ThermoHelperVersionError: If the helper version is wrong or unreadable.
        ThermoHelperLicenseError: If the helper fails or returns empty text.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()
    executable = _resolve_thermo_helper(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )
    config_directory = thermo_config_directory(
        specification, data_directory=data_directory
    )
    locator.verify_helper_version(
        executable,
        expected_version=specification.version,
        timeout=timeout,
        config_directory=config_directory,
    )
    license_text = _run_license_command(
        executable,
        "--thermo-license",
        action="display the Thermo license agreement",
        timeout=timeout,
        config_directory=config_directory,
    )
    if not license_text.strip():
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} returned empty license "
            f"text. Verify that the helper can display its license agreement."
        )
    return license_text


def accept_thermo_license(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
    timeout: float = 10.0,
) -> None:
    """Record acceptance of the Thermo license through the helper.

    Runs the helper's explicit `--agree-to-terms` command only when the helper
    does not already report the license as accepted. Success is confirmed by
    asking the helper again with `--license-status`. The helper records the
    acceptance in `thermo_config_directory()` of the data directory, so it
    applies to one helper version. If `THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR`
    is set and not empty, the helper uses that folder instead.

    Args:
        explicit_path: Optional helper executable or containing directory.
            Defaults to None.
        data_directory: Application data directory override. If None (default),
            uses the platform-specific user data directory.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.
        timeout: Maximum command time in seconds. Defaults to 10.0.

    Returns:
        None.

    Raises:
        UnsupportedPlatformError: If the current runtime has no pinned helper
            release.
        ThermoHelperNotFoundError: If no helper executable is found.
        ThermoHelperVersionError: If the helper version is wrong or unreadable.
        ThermoHelperLicenseError: If the acceptance command fails, or the
            helper still reports the license as not accepted after it.
        ThermoHelperConfigError: If the helper cannot use its license folder.
        ThermoHelperExecutionError: If the license state cannot be queried.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()
    executable = _resolve_thermo_helper(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )
    config_directory = thermo_config_directory(
        specification, data_directory=data_directory
    )
    locator.verify_helper_version(
        executable,
        expected_version=specification.version,
        timeout=timeout,
        config_directory=config_directory,
    )
    if locator.query_license_status(
        executable, timeout=timeout, config_directory=config_directory
    ).accepted:
        return

    _run_license_command(
        executable,
        "--agree-to-terms",
        action="accept the Thermo license agreement",
        timeout=timeout,
        config_directory=config_directory,
    )

    license_status = locator.query_license_status(
        executable, timeout=timeout, config_directory=config_directory
    )
    if not license_status.accepted:
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} exited successfully but "
            "still reports the Thermo license as not accepted. Check that the "
            f"acceptance file {license_status.marker_path} can be created, then "
            "retry."
        )


def _resolve_thermo_helper(
    explicit_path: Path | str | None,
    *,
    data_directory: Path | str | None,
    specification: ThermoHelperSpecification,
) -> Path:
    executable = locator.find_thermo_helper_path(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )
    if executable is None:
        raise ThermoHelperNotFoundError(
            "ThermoScanHeaderExtractor executable was not found. Please install "
            f"version {specification.version!r} or supply a valid executable path."
        )
    return executable


def _run_license_command(
    executable: Path,
    command: str,
    *,
    action: str,
    timeout: float,
    config_directory: Path,
) -> str:
    try:
        result = locator.execute_helper_process(
            [executable, command],
            timeout=timeout,
            config_directory=config_directory,
        )
    except subprocess.TimeoutExpired as error:
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} timed out after "
            f"{timeout} seconds while attempting to {action}."
        ) from error
    except OSError as error:
        raise ThermoHelperLicenseError(
            f"Could not execute ThermoScanHeaderExtractor at {executable} while "
            f"attempting to {action}: {error}. Check the helper file and "
            "permissions."
        ) from error

    stderr_sample = result.stderr.strip()
    detail = f": {stderr_sample}" if stderr_sample else ""
    if result.returncode == _CONFIG_ERROR_EXIT_CODE:
        raise ThermoHelperConfigError(
            f"ThermoScanHeaderExtractor at {executable} could not use its license "
            f"folder while attempting to {action}{detail}. Check that the folder "
            "is writable."
        )
    if result.returncode != 0:
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} failed with exit code "
            f"{result.returncode} while attempting to {action}{detail}."
        )
    return result.stdout

"""Expose and accept the ThermoScanHeaderExtractor license agreement."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    UnsupportedPlatformError,
)
from rawtrace_qc.thermo import locator
from rawtrace_qc.thermo.specification import (
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperSpecification,
)


def get_thermo_license_text(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification = THERMO_HELPER_SPECIFICATION,
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
        specification: Pinned helper release metadata. Defaults to
            `THERMO_HELPER_SPECIFICATION`.
        timeout: Maximum command time in seconds. Defaults to 10.0.

    Returns:
        The license agreement text printed by the helper.

    Raises:
        UnsupportedPlatformError: If the current platform is not Windows.
        ThermoHelperNotFoundError: If no helper executable is found.
        ThermoHelperVersionError: If the helper version is wrong or unreadable.
        ThermoHelperLicenseError: If the helper fails or returns empty text.
    """
    executable = _resolve_thermo_helper(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )
    locator.verify_helper_version(
        executable,
        expected_version=specification.version,
        timeout=timeout,
    )
    license_text = _run_license_command(
        executable,
        "--thermo-license",
        action="display the Thermo license agreement",
        timeout=timeout,
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
    specification: ThermoHelperSpecification = THERMO_HELPER_SPECIFICATION,
    timeout: float = 10.0,
) -> None:
    """Record acceptance of the Thermo license through the helper.

    Runs the helper's explicit `--agree-to-terms` command only when the helper
    does not already report the license as accepted. Success is confirmed by
    asking the helper again. Where the helper records acceptance is left to the
    helper; since v0.2.0 it is recorded per user.

    Args:
        explicit_path: Optional helper executable or containing directory.
            Defaults to None.
        data_directory: Application data directory override. If None (default),
            uses the platform-specific user data directory.
        specification: Pinned helper release metadata. Defaults to
            `THERMO_HELPER_SPECIFICATION`.
        timeout: Maximum command time in seconds. Defaults to 10.0.

    Returns:
        None.

    Raises:
        UnsupportedPlatformError: If the current platform is not Windows.
        ThermoHelperNotFoundError: If no helper executable is found.
        ThermoHelperVersionError: If the helper version is wrong or unreadable.
        ThermoHelperLicenseError: If the helper fails, or still reports the
            license as not accepted after the acceptance command.
    """
    executable = _resolve_thermo_helper(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )
    locator.verify_helper_version(
        executable,
        expected_version=specification.version,
        timeout=timeout,
    )
    if locator.is_license_accepted(executable, timeout=timeout):
        return

    _run_license_command(
        executable,
        "--agree-to-terms",
        action="accept the Thermo license agreement",
        timeout=timeout,
    )

    if not locator.is_license_accepted(executable, timeout=timeout):
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} exited successfully but "
            "still reports the Thermo license as not accepted. Run "
            f"'{executable.name} --agree-to-terms' manually to see where the "
            "helper records acceptance, then retry."
        )


def _resolve_thermo_helper(
    explicit_path: Path | str | None,
    *,
    data_directory: Path | str | None,
    specification: ThermoHelperSpecification,
) -> Path:
    current_platform = environment.get_platform()
    if current_platform != "win32":
        raise UnsupportedPlatformError(
            "ThermoScanHeaderExtractor license operations require Windows, but "
            f"current platform is {current_platform!r}."
        )

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
) -> str:
    try:
        result = locator.execute_helper_process(
            [executable, command],
            timeout=timeout,
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

    if result.returncode != 0:
        stderr_sample = result.stderr.strip()
        detail = f": {stderr_sample}" if stderr_sample else ""
        raise ThermoHelperLicenseError(
            f"ThermoScanHeaderExtractor at {executable} failed with exit code "
            f"{result.returncode} while attempting to {action}{detail}."
        )
    return result.stdout

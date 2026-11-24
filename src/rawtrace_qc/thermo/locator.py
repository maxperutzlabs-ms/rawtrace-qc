"""Locating and status reporting for the ThermoScanHeaderExtractor helper."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ThermoHelperCommandError,
    ThermoHelperConfigError,
    ThermoHelperError,
    ThermoHelperExecutableNotFoundError,
    ThermoHelperExecutionError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperOutputError,
    ThermoHelperTimeoutError,
    ThermoHelperVersionError,
    UnsupportedPlatformError,
)
from rawtrace_qc.thermo.specification import (
    THERMO_HELPER_RELEASE,
    ThermoHelperSpecification,
    resolve_thermo_helper_specification,
)

_LICENSE_ACCEPTED_EXIT_CODE = 0
_LICENSE_NOT_ACCEPTED_EXIT_CODE = 4
_LICENSE_CONFIG_ERROR_EXIT_CODE = 5
_CONFIG_DIRECTORY_VARIABLE = "THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR"
_SETUP_ERRORS = (
    ThermoHelperNotFoundError,
    ThermoHelperVersionError,
    ThermoHelperLicenseError,
    ThermoHelperConfigError,
    UnsupportedPlatformError,
    ThermoHelperExecutableNotFoundError,
)


class ThermoHelperState(StrEnum):
    """Represent the readiness state of ThermoScanHeaderExtractor."""

    READY = "ready"
    UNLICENSED = "unlicensed"
    INVALID_VERSION = "invalid_version"
    NOT_INSTALLED = "not_installed"
    UNSUPPORTED_PLATFORM = "unsupported_platform"


@dataclass(frozen=True, slots=True)
class ThermoLicenseStatus:
    """Describe the Thermo license state that the helper reports.

    Attributes:
        accepted: True if the Thermo license agreement has been accepted.
        marker_path: The file in which the helper records the acceptance. It
            exists only if `accepted` is True.
    """

    accepted: bool
    marker_path: Path


@dataclass(frozen=True, slots=True)
class ThermoHelperStatus:
    """Describe the installation, version, and license state of the helper.

    `license_marker_path` is the file in which the helper records the license
    acceptance. It is None if the helper was not asked, or if it could not
    determine the file, for example because its license folder is unusable.
    """

    state: ThermoHelperState
    path: Path | None
    version: str | None
    license_accepted: bool
    message: str
    license_marker_path: Path | None = None
    expected_version: str = THERMO_HELPER_RELEASE.version

    @property
    def is_ready(self) -> bool:
        """Return True if the helper is installed, verified, and licensed."""
        return self.state is ThermoHelperState.READY


def locate_thermo_helper(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
) -> Path:
    """Locate and return a usable ThermoScanHeaderExtractor executable.

    Checks that the current runtime is supported, resolves the executable path
    by priority, verifies that the helper is installed, checks that its version
    matches the pinned specification, and verifies that the license agreement
    has been accepted.

    Args:
        explicit_path: Optional explicit executable or directory path. Defaults
            to None.
        data_directory: Data directory root. If None (default), uses the
            platform default user data directory.
        specification: Release specification. If None (default), resolve the
            specification for the current host runtime.
    Returns:
        The validated Path to the usable ThermoScanHeaderExtractor executable.

    Raises:
        UnsupportedPlatformError: If the current runtime has no pinned helper
            release.
        ThermoHelperNotFoundError: If no helper executable is found.
        ThermoHelperVersionError: If the helper version is wrong or unreadable,
            or the helper cannot report its license state.
        ThermoHelperLicenseError: If the Thermo license agreement has not been
            accepted.
        ThermoHelperConfigError: If the helper cannot use or locate its license
            folder.

    Examples:
        ```python
        from rawtrace_qc.thermo import locate_thermo_helper

        executable = locate_thermo_helper()
        print(f"Using helper at: {executable}")
        ```
    """
    status = get_thermo_helper_status(
        explicit_path,
        data_directory=data_directory,
        specification=specification,
    )

    if status.state is ThermoHelperState.NOT_INSTALLED:
        raise ThermoHelperNotFoundError(status.message)
    if status.state is ThermoHelperState.INVALID_VERSION:
        raise ThermoHelperVersionError(status.message)
    if status.state is ThermoHelperState.UNLICENSED:
        if status.license_marker_path is None:
            raise ThermoHelperConfigError(status.message)
        raise ThermoHelperLicenseError(status.message)
    if status.state is ThermoHelperState.UNSUPPORTED_PLATFORM:
        raise UnsupportedPlatformError(status.message)

    if status.path is None:
        raise ThermoHelperNotFoundError(status.message)

    return status.path


def is_thermo_setup_error(error: BaseException) -> bool:
    """Check whether an error means that the Thermo helper is not ready.

    Setting up the helper fixes these errors: it is missing, has the wrong
    version, cannot be started, its license is not accepted or its license
    folder is unusable, or the system is not supported. Other errors, such as
    a `ThermoHelperCommandError` from extraction, concern one file.

    Args:
        error: Error raised while locating the helper or extracting a file.

    Returns:
        True if `error` is a setup problem of the helper.
    """
    return isinstance(error, _SETUP_ERRORS)


def get_thermo_helper_status(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
) -> ThermoHelperStatus:
    """Inspect the status of ThermoScanHeaderExtractor without side effects.

    Checks what is present, what version it is, and whether the license has
    been accepted. If the helper is not installed, no process is executed. An
    `explicit_path` that does not lead to the executable is reported as
    `NOT_INSTALLED`, without checking the managed installation.

    Args:
        explicit_path: Optional explicit executable or directory path. Defaults
            to None.
        data_directory: Data directory root. If None (default), uses the
            platform default user data directory.
        specification: Release specification. If None (default), resolve the
            specification for the current host runtime.
    Returns:
        A `ThermoHelperStatus` instance describing the helper state.
    """
    if specification is None:
        try:
            specification = resolve_thermo_helper_specification()
        except UnsupportedPlatformError as error:
            return ThermoHelperStatus(
                state=ThermoHelperState.UNSUPPORTED_PLATFORM,
                path=None,
                version=None,
                license_accepted=False,
                message=str(error),
                expected_version=THERMO_HELPER_RELEASE.version,
            )

    try:
        candidate = find_thermo_helper_path(
            explicit_path,
            data_directory=data_directory,
            specification=specification,
        )
    except ThermoHelperNotFoundError as error:
        return ThermoHelperStatus(
            state=ThermoHelperState.NOT_INSTALLED,
            path=None,
            version=None,
            license_accepted=False,
            message=str(error),
            expected_version=specification.version,
        )

    if candidate is None:
        managed_path = (
            managed_thermo_helper_directory(
                specification, data_directory=data_directory
            )
            / specification.executable_name
        )
        return ThermoHelperStatus(
            state=ThermoHelperState.NOT_INSTALLED,
            path=None,
            version=None,
            license_accepted=False,
            message=(
                f"ThermoScanHeaderExtractor executable was not found. "
                f"Checked: {managed_path}. Please install "
                f"ThermoScanHeaderExtractor v{specification.version}."
            ),
            expected_version=specification.version,
        )

    try:
        reported_version = query_helper_version(candidate)
    except ThermoHelperVersionError as error:
        return ThermoHelperStatus(
            state=ThermoHelperState.INVALID_VERSION,
            path=candidate,
            version=None,
            license_accepted=False,
            message=(
                f"ThermoScanHeaderExtractor at {candidate} has an unreadable "
                f"version: {error}"
            ),
            expected_version=specification.version,
        )

    if reported_version != specification.version:
        return ThermoHelperStatus(
            state=ThermoHelperState.INVALID_VERSION,
            path=candidate,
            version=reported_version,
            license_accepted=False,
            message=(
                f"ThermoScanHeaderExtractor at {candidate} reported version "
                f"{reported_version!r}, but expected {specification.version!r}. "
                f"Please install version {specification.version!r}."
            ),
            expected_version=specification.version,
        )

    try:
        license_status = query_license_status(candidate)
    except ThermoHelperConfigError as error:
        return ThermoHelperStatus(
            state=ThermoHelperState.UNLICENSED,
            path=candidate,
            version=reported_version,
            license_accepted=False,
            message=str(error),
            expected_version=specification.version,
        )
    except ThermoHelperError as error:
        return ThermoHelperStatus(
            state=ThermoHelperState.INVALID_VERSION,
            path=candidate,
            version=reported_version,
            license_accepted=False,
            message=(
                f"ThermoScanHeaderExtractor at {candidate} does not work "
                f"correctly, because its license state could not be read: {error}"
            ),
            expected_version=specification.version,
        )

    if not license_status.accepted:
        return ThermoHelperStatus(
            state=ThermoHelperState.UNLICENSED,
            path=candidate,
            version=reported_version,
            license_accepted=False,
            message=(
                f"ThermoScanHeaderExtractor at {candidate} is installed "
                f"(version {reported_version}), but the Thermo license "
                "agreement has not been accepted."
            ),
            license_marker_path=license_status.marker_path,
            expected_version=specification.version,
        )

    return ThermoHelperStatus(
        state=ThermoHelperState.READY,
        path=candidate,
        version=reported_version,
        license_accepted=True,
        message=(
            f"ThermoScanHeaderExtractor v{reported_version} at {candidate} is ready."
        ),
        license_marker_path=license_status.marker_path,
        expected_version=specification.version,
    )


def find_thermo_helper_path(
    explicit_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
) -> Path | None:
    """Resolve the candidate ThermoScanHeaderExtractor path by priority.

    An explicitly supplied path is used exclusively, so a mistyped path never
    selects a different helper. Without one, the managed install path in the user
    data directory for the pinned version is used. Does not execute the helper.

    Args:
        explicit_path: Optional explicit executable or directory path. Defaults
            to None.
        data_directory: Data directory root. If None (default), uses the
            platform default user data directory.
        specification: Release specification. If None (default), resolve the
            specification for the current host runtime.

    Returns:
        The resolved executable path, or None if no `explicit_path` is supplied
        and the managed installation does not exist.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
        ThermoHelperNotFoundError: If `explicit_path` is neither a file nor a
            folder containing the executable.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()

    if explicit_path is not None:
        explicit = Path(explicit_path).expanduser().resolve()
        if explicit.is_file():
            return explicit
        if explicit.is_dir():
            candidate = explicit / specification.executable_name
            if candidate.is_file():
                return candidate.resolve()
        raise ThermoHelperNotFoundError(
            f"ThermoScanHeaderExtractor was not found at helper path "
            f"'{explicit}'. Supply the executable or a folder that contains "
            f"{specification.executable_name!r}, or omit the path to use the "
            "managed installation."
        )

    managed_path = (
        managed_thermo_helper_directory(specification, data_directory=data_directory)
        / specification.executable_name
    ).resolve()
    if managed_path.is_file():
        return managed_path

    return None


def managed_thermo_helper_directory(
    specification: ThermoHelperSpecification | None = None,
    *,
    data_directory: Path | str | None = None,
) -> Path:
    """Return the managed install directory of a helper release for one runtime.

    The directory is `<data_directory>/tools/<tool>/<version>/<runtime>` and is
    not created by this function.

    Args:
        specification: Release specification. If None (default), resolve the
            specification for the current host runtime.
        data_directory: Data directory root. If None (default), uses the
            platform default user data directory.

    Returns:
        The managed install directory path.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()
    return environment.helper_tool_directory(
        specification.tool_name,
        specification.version,
        specification.runtime,
        data_directory=data_directory,
    )


def verify_helper_version(
    executable_path: Path,
    expected_version: str = THERMO_HELPER_RELEASE.version,
    *,
    timeout: float = 10.0,
) -> str:
    """Verify that the helper reports the expected version.

    Args:
        executable_path: Path to the ThermoScanHeaderExtractor executable.
        expected_version: Expected release version. Defaults to the pinned
            version in `THERMO_HELPER_RELEASE`.
        timeout: Maximum time to wait in seconds. Defaults to 10.0.

    Returns:
        The verified version string.

    Raises:
        ThermoHelperVersionError: If the reported version does not match
            `expected_version` or cannot be read.
    """
    reported = query_helper_version(executable_path, timeout=timeout)
    if reported != expected_version:
        raise ThermoHelperVersionError(
            f"ThermoScanHeaderExtractor at {executable_path} reported version "
            f"{reported!r}, but expected {expected_version!r}. Please install "
            f"version {expected_version!r}."
        )
    return reported


def query_helper_version(
    executable_path: Path,
    *,
    timeout: float = 10.0,
) -> str:
    """Query the version reported by ThermoScanHeaderExtractor.

    Executes the helper with `--version` and returns the trimmed first line of output.

    Args:
        executable_path: Path to the ThermoScanHeaderExtractor executable.
        timeout: Maximum time to wait in seconds. Defaults to 10.0.

    Returns:
        The version string reported by the tool.

    Raises:
        ThermoHelperVersionError: If the tool fails to run, exits with non-zero
            status, times out, or returns an unreadable version.
    """
    try:
        result = execute_helper_process([executable_path, "--version"], timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise ThermoHelperVersionError(
            f"ThermoScanHeaderExtractor at {executable_path} timed out after "
            f"{timeout} seconds when querying version."
        ) from error
    except OSError as error:
        raise ThermoHelperVersionError(
            f"Failed to execute ThermoScanHeaderExtractor at "
            f"{executable_path}: {error}."
        ) from error

    if result.returncode != 0:
        stderr_sample = result.stderr.strip()
        detail = f": {stderr_sample}" if stderr_sample else ""
        raise ThermoHelperVersionError(
            f"ThermoScanHeaderExtractor at {executable_path} failed with exit "
            f"code {result.returncode}{detail}."
        )

    output = result.stdout.strip()
    if not output:
        raise ThermoHelperVersionError(
            f"ThermoScanHeaderExtractor at {executable_path} returned empty "
            "version output."
        )

    version_line = next(
        (line.strip() for line in output.splitlines() if line.strip()), ""
    )
    if not version_line:
        raise ThermoHelperVersionError(
            f"ThermoScanHeaderExtractor at {executable_path} returned "
            f"unreadable version output {output!r}."
        )
    return version_line


def query_license_status(
    executable_path: Path,
    *,
    timeout: float = 10.0,
) -> ThermoLicenseStatus:
    """Ask the helper whether the Thermo license has been accepted.

    The helper is the authority on its license state. It is run with
    `--license-status`, which never creates or changes anything. It exits with
    code 0 if the license has been accepted and with code 4 if not, and in both
    cases prints the path of its acceptance marker file.

    Args:
        executable_path: Path to the ThermoScanHeaderExtractor executable.
        timeout: Maximum time to wait in seconds. Defaults to 10.0.

    Returns:
        The license state and the path of the acceptance marker file.

    Raises:
        ThermoHelperConfigError: If the helper cannot determine its license
            folder (exit code 5).
        ThermoHelperCommandError: If the helper exits with another code.
        ThermoHelperOutputError: If the helper does not print exactly one line
            with the marker path.
        ThermoHelperTimeoutError: If the helper exceeds `timeout`.
        ThermoHelperExecutionError: If the helper cannot be started.
    """
    action = "when checking the Thermo license state"
    try:
        result = execute_helper_process(
            [executable_path, "--license-status"], timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        raise ThermoHelperTimeoutError(
            f"ThermoScanHeaderExtractor at {executable_path} timed out after "
            f"{timeout} seconds {action}.",
            stdout="",
            stderr="",
        ) from error
    except OSError as error:
        raise ThermoHelperExecutionError(
            f"Failed to execute ThermoScanHeaderExtractor at {executable_path} "
            f"{action}: {error}.",
            stdout="",
            stderr="",
        ) from error

    if result.returncode == _LICENSE_CONFIG_ERROR_EXIT_CODE:
        stderr_sample = result.stderr.strip()
        detail = f" Helper message: {stderr_sample}" if stderr_sample else ""
        raise ThermoHelperConfigError(
            f"ThermoScanHeaderExtractor at {executable_path} could not determine "
            f"its license folder. If {_CONFIG_DIRECTORY_VARIABLE} is set, it "
            f"must be the absolute path of a folder.{detail}"
        )
    if result.returncode not in (
        _LICENSE_ACCEPTED_EXIT_CODE,
        _LICENSE_NOT_ACCEPTED_EXIT_CODE,
    ):
        stderr_sample = result.stderr.strip()
        detail = f" Helper message: {stderr_sample}" if stderr_sample else ""
        raise ThermoHelperCommandError(
            f"ThermoScanHeaderExtractor at {executable_path} exited with "
            f"unexpected code {result.returncode} {action}.{detail}",
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    marker_line = result.stdout.removesuffix("\n").removesuffix("\r")
    if not marker_line or any(
        character in marker_line for character in ("\n", "\r", "\ufffd")
    ):
        raise ThermoHelperOutputError(
            f"ThermoScanHeaderExtractor at {executable_path} did not report the "
            f"path of its license acceptance file {action}.",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return ThermoLicenseStatus(
        accepted=result.returncode == _LICENSE_ACCEPTED_EXIT_CODE,
        marker_path=Path(marker_line),
    )


def execute_helper_process(
    args: Sequence[str | Path],
    *,
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    """Execute a low-level Thermo helper command.

    Args:
        args: Command arguments starting with the executable path.
        timeout: Maximum execution time in seconds. Defaults to 10.0.

    Returns:
        The completed process result with captured standard output and error.

    Raises:
        OSError: If the process cannot be started or executable is missing.
        subprocess.TimeoutExpired: If the process exceeds the timeout.
    """
    str_args = [str(arg) for arg in args]
    return subprocess.run(
        str_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )

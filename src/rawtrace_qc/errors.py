"""Exception types shared by rawtrace-qc public APIs."""

from __future__ import annotations

from pathlib import Path


class RawtraceError(Exception):
    """Base class for expected rawtrace-qc errors."""


class ConfigurationError(RawtraceError):
    """Raise when a rawtrace-qc option or configuration is invalid."""


class DiscoveryError(RawtraceError):
    """Raise when the discovery source cannot be traversed."""


class ArtifactValidationError(RawtraceError):
    """Raise when a generated or loaded trace artifact violates its contract."""


class ProcessingError(RawtraceError):
    """Raise when trace artifacts cannot be prepared for reporting."""


class ReportError(RawtraceError):
    """Raise when report data or HTML cannot be created."""


class ExtractionError(RawtraceError):
    """Raise when one acquisition cannot be read or lacks the requested data."""

    def __init__(self, message: str, *, path: Path) -> None:
        self.path = path
        super().__init__(message)


class ThermoHelperError(RawtraceError):
    """Base class for ThermoScanHeaderExtractor helper errors."""


class ThermoHelperExecutionError(ThermoHelperError):
    """Raise when the Thermo helper process cannot be executed successfully."""

    def __init__(self, message: str, *, stdout: str, stderr: str) -> None:
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"{message} Captured stdout: {stdout!r}; captured stderr: {stderr!r}."
        )


class ThermoHelperCommandError(ThermoHelperExecutionError):
    """Raise when the Thermo helper exits with a non-zero status."""

    def __init__(
        self, message: str, *, returncode: int, stdout: str, stderr: str
    ) -> None:
        self.returncode = returncode
        super().__init__(message, stdout=stdout, stderr=stderr)


class ThermoHelperTimeoutError(ThermoHelperExecutionError):
    """Raise when the Thermo helper exceeds its execution timeout."""


class ThermoHelperExecutableNotFoundError(ThermoHelperExecutionError):
    """Raise when the requested Thermo helper executable cannot be started."""


class ThermoHelperOutputError(ThermoHelperExecutionError):
    """Raise when the Thermo helper output cannot be decoded as UTF-8."""


class UnsupportedPlatformError(ThermoHelperError):
    """Raise when an operation is unsupported on the current operating system."""


class ThermoHelperNotFoundError(ThermoHelperError):
    """Raise when no usable ThermoScanHeaderExtractor executable is found."""


class ThermoHelperVersionError(ThermoHelperError):
    """Raise when the Thermo helper version is invalid, unreadable, or mismatched."""


class ThermoHelperLicenseError(ThermoHelperError):
    """Raise when the Thermo license agreement has not been accepted."""


class ThermoHelperInstallationError(ThermoHelperError):
    """Raise when the Thermo helper cannot be installed safely."""


class ThermoHelperDownloadError(ThermoHelperInstallationError):
    """Raise when the pinned Thermo helper archive cannot be downloaded."""


class ThermoHelperChecksumError(ThermoHelperInstallationError):
    """Raise when a Thermo helper archive does not match its pinned checksum."""


class ThermoHelperArchiveError(ThermoHelperInstallationError):
    """Raise when a Thermo helper archive is invalid or unsafe to extract."""


class ThermoHelperInstallConflictError(ThermoHelperInstallationError):
    """Raise when an existing helper install conflicts with the pinned release."""

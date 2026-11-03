"""CLI error reporting and user guidance helpers."""

from __future__ import annotations

import sys

from rawtrace_qc.errors import (
    ThermoHelperError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperVersionError,
    UnsupportedPlatformError,
)

CHECK_THERMO_SETUP = "Check setup with `rawtrace-qc thermo status`."


def print_cli_error(error: Exception, *, thermo: bool = False) -> None:
    """Print a standardized CLI error message and actionable guidance to stderr.

    Args:
        error: The exception to format and display.
        thermo: If True, include the fallback hint for Thermo-related operations
            when the error is a `ThermoHelperError`. Defaults to False.
    """
    print(f"Error: {error}", file=sys.stderr)
    hint = thermo_setup_hint(error)
    if hint is None and thermo and isinstance(error, ThermoHelperError):
        hint = CHECK_THERMO_SETUP
    if hint is not None:
        print(hint, file=sys.stderr)


def thermo_setup_hint(error: Exception) -> str | None:
    """Return the setup step that resolves a Thermo helper error.

    Args:
        error: The exception to look up.

    Returns:
        The setup guidance, or None if `error` has no specific setup step.
    """
    if isinstance(error, ThermoHelperNotFoundError):
        return (
            "Install the helper with `rawtrace-qc thermo install` (or "
            "`rawtrace-qc thermo install --from-zip PATH` offline), then review "
            "and accept its terms with `rawtrace-qc thermo accept-license`."
        )
    if isinstance(error, ThermoHelperLicenseError):
        return (
            "Review and accept the displayed terms with "
            "`rawtrace-qc thermo accept-license`."
        )
    if isinstance(error, ThermoHelperVersionError):
        return "Install the pinned helper version with `rawtrace-qc thermo install`."
    if isinstance(error, UnsupportedPlatformError):
        return (
            "Thermo .raw extraction is not supported on this system; see the "
            "supported runtimes above."
        )
    return None

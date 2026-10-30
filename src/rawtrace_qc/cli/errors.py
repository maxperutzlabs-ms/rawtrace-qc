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


def print_cli_error(error: Exception, *, thermo: bool = False) -> None:
    """Print a standardized CLI error message and actionable guidance to stderr.

    Args:
        error: The exception to format and display.
        thermo: If True, include the fallback hint for Thermo-related operations
            when the error is a `ThermoHelperError`. Defaults to False.
    """
    print(f"Error: {error}", file=sys.stderr)
    if isinstance(error, ThermoHelperNotFoundError):
        print(
            "Install the helper with `rawtrace-qc thermo install` (or "
            "`rawtrace-qc thermo install --from-zip PATH` offline), then review "
            "and accept its terms with `rawtrace-qc thermo accept-license`.",
            file=sys.stderr,
        )
    elif isinstance(error, ThermoHelperLicenseError):
        print(
            "Review and accept the displayed terms with "
            "`rawtrace-qc thermo accept-license`.",
            file=sys.stderr,
        )
    elif isinstance(error, ThermoHelperVersionError):
        print(
            "Install the pinned helper version with `rawtrace-qc thermo install`, "
            "or pass a matching executable with `--helper-path`.",
            file=sys.stderr,
        )
    elif isinstance(error, UnsupportedPlatformError):
        print(
            "Thermo .raw extraction is not supported on this system; see the "
            "supported runtimes above.",
            file=sys.stderr,
        )
    elif thermo and isinstance(error, ThermoHelperError):
        print("Check setup with `rawtrace-qc thermo status`.", file=sys.stderr)

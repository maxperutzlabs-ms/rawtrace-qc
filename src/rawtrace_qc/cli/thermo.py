"""ThermoScanHeaderExtractor CLI commands."""

from __future__ import annotations

from pathlib import Path

from cyclopts import App

from rawtrace_qc.cli.errors import print_cli_error
from rawtrace_qc.errors import ThermoHelperError
from rawtrace_qc.thermo import (
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperState,
    accept_thermo_license,
    get_thermo_helper_status,
    get_thermo_license_text,
    install_thermo_helper,
)

thermo_app = App(name="thermo", help="Manage ThermoScanHeaderExtractor setup.")


@thermo_app.command
def status(
    helper_path: Path | None = None,
    data_directory: Path | None = None,
) -> int:
    """Show Thermo helper installation, version, and license status.

    Args:
        helper_path: Optional helper executable or its containing directory.
        data_directory: Optional application data directory override.

    Returns:
        Exit code `0` when the helper is ready, otherwise `1`.
    """
    helper_status = get_thermo_helper_status(
        explicit_path=helper_path,
        data_directory=data_directory,
    )
    print(f"Thermo helper status: {helper_status.state.value}")
    print(helper_status.message)
    if helper_status.is_ready:
        return 0
    print(_status_action(helper_status.state))
    return 1


@thermo_app.command
def install(
    from_zip: Path | None = None,
    data_directory: Path | None = None,
) -> int:
    """Install the pinned helper from its release or a local ZIP archive.

    Args:
        from_zip: Optional local helper ZIP for offline installation.
        data_directory: Optional application data directory override.

    Returns:
        Exit code `0` when installation succeeds, otherwise `1`.
    """
    try:
        executable = install_thermo_helper(
            archive_path=from_zip,
            data_directory=data_directory,
            specification=THERMO_HELPER_SPECIFICATION,
        )
    except ThermoHelperError as error:
        print_cli_error(error, thermo=True)
        return 1

    print(f"Installed ThermoScanHeaderExtractor at {executable}")
    print(
        "Review the terms, then run `rawtrace-qc thermo accept-license` to accept them."
    )
    return 0


@thermo_app.command(name="accept-license")
def accept_license(
    helper_path: Path | None = None,
    data_directory: Path | None = None,
) -> int:
    """Display the Thermo terms and explicitly record license acceptance.

    Running this command is the user's explicit acceptance action. The helper
    prints its terms before the library records acceptance.

    Args:
        helper_path: Optional helper executable or its containing directory.
        data_directory: Optional application data directory override.

    Returns:
        Exit code `0` when acceptance is recorded, otherwise `1`.
    """
    try:
        terms = get_thermo_license_text(
            explicit_path=helper_path,
            data_directory=data_directory,
        )
        print("The following Thermo license terms will be accepted by this command:")
        print(terms, end="" if terms.endswith("\n") else "\n")
        accept_thermo_license(
            explicit_path=helper_path,
            data_directory=data_directory,
        )
    except ThermoHelperError as error:
        print_cli_error(error, thermo=True)
        return 1

    print("Thermo license acceptance is recorded for the current user.")
    return 0


def _status_action(state: ThermoHelperState) -> str:
    actions = {
        ThermoHelperState.NOT_INSTALLED: (
            "Install it with `rawtrace-qc thermo install`; use `--from-zip PATH` "
            "for an offline archive."
        ),
        ThermoHelperState.UNLICENSED: (
            "Review and accept the terms with `rawtrace-qc thermo accept-license`."
        ),
        ThermoHelperState.INVALID_VERSION: (
            "Install the pinned helper version with `rawtrace-qc thermo install`."
        ),
        ThermoHelperState.UNSUPPORTED_PLATFORM: (
            "Thermo .raw extraction and helper setup require Windows."
        ),
        ThermoHelperState.READY: "",
    }
    return actions[state]

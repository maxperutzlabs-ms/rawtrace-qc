"""ThermoScanHeaderExtractor CLI commands."""

from __future__ import annotations

from pathlib import Path

from cyclopts import App

from rawtrace_qc.cli.errors import THERMO_CONFIG_HINT, print_cli_error
from rawtrace_qc.errors import ThermoHelperError
from rawtrace_qc.thermo import (
    ThermoHelperState,
    ThermoHelperStatus,
    accept_thermo_license,
    get_thermo_helper_status,
    get_thermo_license_text,
    install_thermo_helper,
)

thermo_app = App(name="thermo", help="Manage ThermoScanHeaderExtractor setup.")


@thermo_app.command
def status(
    *,
    helper_path: Path | None = None,
) -> int:
    """Show Thermo helper installation, version, and license status.

    Args:
        helper_path: Use this helper executable, or the helper in this folder.

    Returns:
        Exit code `0` when the helper is ready, otherwise `1`.
    """
    helper_status = get_thermo_helper_status(explicit_path=helper_path)
    print(f"Thermo helper status: {helper_status.state.value}")
    print(helper_status.message)
    if helper_status.license_marker_path is not None:
        print(f"License acceptance file: {helper_status.license_marker_path}")
    if helper_status.is_ready:
        return 0
    print(_status_action(helper_status, helper_path))
    return 1


@thermo_app.command
def install(
    *,
    from_archive: Path | None = None,
    overwrite: bool = False,
) -> int:
    """Install the pinned helper from its release or a local archive.

    Args:
        from_archive: Install from this local `.zip` or `.tar.gz` archive
            instead of downloading it.
        overwrite: Replace whatever is already at the install location.

    Returns:
        Exit code `0` when installation succeeds, otherwise `1`.
    """
    try:
        executable = install_thermo_helper(
            archive_path=from_archive,
            overwrite=overwrite,
        )
    except ThermoHelperError as error:
        print_cli_error(error, thermo=True)
        return 1

    print(f"Installed ThermoScanHeaderExtractor at {executable}")
    print(
        "Read the terms with `rawtrace-qc thermo show-license`, then run "
        "`rawtrace-qc thermo accept-license` to accept them."
    )
    return 0


@thermo_app.command(name="show-license")
def show_license(
    *,
    helper_path: Path | None = None,
) -> int:
    """Display the Thermo license terms without accepting them.

    Args:
        helper_path: Use this helper executable, or the helper in this folder.

    Returns:
        Exit code `0` when the terms are displayed, otherwise `1`.
    """
    try:
        terms = get_thermo_license_text(explicit_path=helper_path)
    except ThermoHelperError as error:
        print_cli_error(error, thermo=True)
        return 1

    print(terms, end="" if terms.endswith("\n") else "\n")
    return 0


@thermo_app.command(name="accept-license")
def accept_license(
    *,
    helper_path: Path | None = None,
) -> int:
    """Display the Thermo terms and explicitly record license acceptance.

    Running this command is the user's explicit acceptance action. The helper
    prints its terms before the library records acceptance.

    Args:
        helper_path: Use this helper executable, or the helper in this folder.

    Returns:
        Exit code `0` when acceptance is recorded, otherwise `1`.
    """
    try:
        terms = get_thermo_license_text(explicit_path=helper_path)
        print("The following Thermo license terms will be accepted by this command:")
        print(terms, end="" if terms.endswith("\n") else "\n")
        accept_thermo_license(explicit_path=helper_path)
    except ThermoHelperError as error:
        print_cli_error(error, thermo=True)
        return 1

    print(
        "Thermo license acceptance is recorded for the current user and this "
        "version of the Thermo tool."
    )
    return 0


def _status_action(helper_status: ThermoHelperStatus, helper_path: Path | None) -> str:
    helper_option = "" if helper_path is None else f' --helper-path "{helper_path}"'
    if helper_status.license_folder_unusable:
        return THERMO_CONFIG_HINT
    actions = {
        ThermoHelperState.NOT_INSTALLED: (
            "Install it with `rawtrace-qc thermo install`; use "
            "`--from-archive PATH` for an offline archive."
        ),
        ThermoHelperState.UNLICENSED: (
            f"Read the terms with `rawtrace-qc thermo show-license{helper_option}`, "
            "then accept them with "
            f"`rawtrace-qc thermo accept-license{helper_option}`."
        ),
        ThermoHelperState.INVALID_VERSION: (
            "Replace it with the pinned helper version using "
            "`rawtrace-qc thermo install --overwrite`."
        ),
        ThermoHelperState.UNSUPPORTED_PLATFORM: (
            "Thermo .raw extraction and helper setup are not supported on this "
            "system; see the supported runtimes above."
        ),
        ThermoHelperState.READY: "",
    }
    return actions[helper_status.state]

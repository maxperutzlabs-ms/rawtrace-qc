"""Thermo helper release metadata and integration support."""

from rawtrace_qc.thermo.installation import (
    download_thermo_helper_archive,
    extract_thermo_helper_archive,
    install_thermo_helper,
    verify_thermo_helper_archive,
)
from rawtrace_qc.thermo.license import (
    accept_thermo_license,
    get_thermo_license_text,
)
from rawtrace_qc.thermo.locator import (
    ThermoHelperState,
    ThermoHelperStatus,
    execute_helper_process,
    find_thermo_helper_path,
    get_thermo_helper_status,
    is_license_accepted,
    locate_thermo_helper,
    query_helper_version,
    verify_helper_version,
)
from rawtrace_qc.thermo.runner import (
    build_thermo_helper_command,
    run_thermo_helper,
)
from rawtrace_qc.thermo.specification import (
    THERMO_HELPER_NAME,
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperSpecification,
)

__all__ = [
    "THERMO_HELPER_NAME",
    "THERMO_HELPER_SPECIFICATION",
    "ThermoHelperSpecification",
    "ThermoHelperState",
    "ThermoHelperStatus",
    "accept_thermo_license",
    "build_thermo_helper_command",
    "download_thermo_helper_archive",
    "extract_thermo_helper_archive",
    "execute_helper_process",
    "find_thermo_helper_path",
    "get_thermo_helper_status",
    "get_thermo_license_text",
    "is_license_accepted",
    "install_thermo_helper",
    "locate_thermo_helper",
    "query_helper_version",
    "run_thermo_helper",
    "verify_helper_version",
    "verify_thermo_helper_archive",
]

"""Integration test for installing the pinned Thermo helper and querying its state."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc import environment
from rawtrace_qc.thermo import (
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperState,
    get_thermo_helper_status,
    install_thermo_helper,
    is_license_accepted,
    verify_helper_version,
)
from tests.support.thermo_helper import get_or_download_thermo_helper_archive


@pytest.mark.network
def test_downloads_installs_and_reports_version_and_license_state(tmp_path: Path) -> None:
    if environment.get_platform() != "win32":
        pytest.skip("ThermoScanHeaderExtractor integration requires Windows.")

    specification = THERMO_HELPER_SPECIFICATION
    data_directory = tmp_path / "app-data"
    initial_status = get_thermo_helper_status(data_directory=data_directory, specification=specification)
    assert initial_status.state is ThermoHelperState.NOT_INSTALLED

    archive_path = get_or_download_thermo_helper_archive(specification=specification)

    executable = install_thermo_helper(
        archive_path,
        data_directory=data_directory,
        specification=specification,
        timeout=60.0,
    )

    assert executable.is_file()
    assert verify_helper_version(executable, specification.version) == specification.version

    # The license state belongs to the current user and is never changed here;
    # only check that the helper's answer is consistent with the reported status.
    license_accepted = is_license_accepted(executable)
    status = get_thermo_helper_status(data_directory=data_directory, specification=specification)
    expected_state = ThermoHelperState.READY if license_accepted else ThermoHelperState.UNLICENSED
    assert status.state is expected_state
    assert status.license_accepted is license_accepted

"""Integration test for installing the pinned Thermo helper and querying its state."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.thermo import (
    ThermoHelperState,
    get_thermo_helper_status,
    install_thermo_helper,
    thermo_config_directory,
    verify_helper_version,
)
from rawtrace_qc.thermo.runner import THERMO_CONFIG_DIRECTORY_VARIABLE
from tests.support.thermo_helper import get_or_download_thermo_helper_archive, resolve_specification_or_skip


@pytest.mark.network
def test_downloads_installs_and_reports_version_and_license_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(THERMO_CONFIG_DIRECTORY_VARIABLE, raising=False)
    specification = resolve_specification_or_skip()
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

    status = get_thermo_helper_status(data_directory=data_directory, specification=specification)
    assert status.state is ThermoHelperState.UNLICENSED
    assert status.license_marker_path == (
        thermo_config_directory(specification, data_directory=data_directory) / ".thermo-license-accepted"
    )

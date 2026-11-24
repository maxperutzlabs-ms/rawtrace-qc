"""Integration tests for installing the pinned Thermo helper and for its real license flow."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.errors import ThermoHelperConfigError, ThermoHelperLicenseError
from rawtrace_qc.thermo import (
    ThermoHelperState,
    accept_thermo_license,
    get_thermo_helper_status,
    install_thermo_helper,
    locate_thermo_helper,
    thermo_config_directory,
    verify_helper_version,
)
from rawtrace_qc.thermo.runner import THERMO_CONFIG_DIRECTORY_VARIABLE
from tests.support.thermo_helper import get_or_download_thermo_helper_archive, resolve_specification_or_skip

pytestmark = pytest.mark.network

_MARKER_NAME = ".thermo-license-accepted"


@pytest.mark.usefixtures("isolated_data_directory")
def test_downloads_installs_and_reports_version_and_license_state() -> None:
    specification = resolve_specification_or_skip()
    initial_status = get_thermo_helper_status(specification=specification)
    assert initial_status.state is ThermoHelperState.NOT_INSTALLED

    archive_path = get_or_download_thermo_helper_archive(specification=specification)

    executable = install_thermo_helper(archive_path, specification=specification, timeout=60.0)

    assert executable.is_file()
    assert verify_helper_version(executable, specification.version) == specification.version

    status = get_thermo_helper_status(specification=specification)
    assert status.state is ThermoHelperState.UNLICENSED
    assert status.license_marker_path == thermo_config_directory(specification) / _MARKER_NAME


class TestRealLicenseFlow:
    def test_acceptance_in_a_set_folder_turns_unlicensed_into_ready(
        self, thermo_helper_executable: Path, isolated_thermo_config: Path
    ) -> None:
        status = get_thermo_helper_status(thermo_helper_executable)
        assert status.state is ThermoHelperState.UNLICENSED
        assert status.license_marker_path == isolated_thermo_config / _MARKER_NAME
        with pytest.raises(ThermoHelperLicenseError):
            locate_thermo_helper(thermo_helper_executable)

        accept_thermo_license(thermo_helper_executable)

        assert get_thermo_helper_status(thermo_helper_executable).state is ThermoHelperState.READY
        assert locate_thermo_helper(thermo_helper_executable) == thermo_helper_executable
        assert (isolated_thermo_config / _MARKER_NAME).is_file()
        assert not thermo_config_directory().exists()

    @pytest.mark.usefixtures("isolated_data_directory")
    def test_acceptance_without_a_set_folder_uses_the_default_folder(self, thermo_helper_executable: Path) -> None:
        accept_thermo_license(thermo_helper_executable)

        assert (thermo_config_directory() / _MARKER_NAME).is_file()

    def test_relative_folder_is_reported_as_a_config_error(
        self, thermo_helper_executable: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(THERMO_CONFIG_DIRECTORY_VARIABLE, "relative-config")

        status = get_thermo_helper_status(thermo_helper_executable)

        assert status.state is ThermoHelperState.UNLICENSED
        assert status.license_marker_path is None
        with pytest.raises(ThermoHelperConfigError, match="relative-config"):
            locate_thermo_helper(thermo_helper_executable)
        with pytest.raises(ThermoHelperConfigError):
            accept_thermo_license(thermo_helper_executable)

"""Unit tests for locating and reporting status of ThermoScanHeaderExtractor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ThermoHelperCommandError,
    ThermoHelperConfigError,
    ThermoHelperError,
    ThermoHelperExecutionError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperOutputError,
    ThermoHelperTimeoutError,
    ThermoHelperVersionError,
    UnsupportedPlatformError,
)
from rawtrace_qc.thermo import (
    ThermoHelperState,
    find_thermo_helper_path,
    get_thermo_helper_status,
    locate_thermo_helper,
    managed_thermo_helper_directory,
    query_helper_version,
    query_license_status,
    verify_helper_version,
)
from tests.support.mock_helper import MockThermoHelper, create_mock_helper_file
from tests.support.thermo_helper import WIN_X64_SPECIFICATION


@pytest.fixture(autouse=True)
def mock_windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "get_platform", lambda: "win32")
    monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")


class TestFindThermoHelperPath:
    def test_finds_explicit_file_path_when_present(self, tmp_path: Path) -> None:
        explicit_exe = create_mock_helper_file(tmp_path / "custom")

        result = find_thermo_helper_path(explicit_exe)

        assert result == explicit_exe.resolve()

    def test_finds_executable_inside_explicit_directory(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom"
        explicit_exe = create_mock_helper_file(custom_dir)

        result = find_thermo_helper_path(custom_dir)

        assert result == explicit_exe.resolve()

    def test_finds_managed_install_in_data_directory(self) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        managed_exe = create_mock_helper_file(managed_dir)

        result = find_thermo_helper_path()

        assert result == managed_exe.resolve()

    def test_explicit_path_takes_priority_over_managed_install(self, tmp_path: Path) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        create_mock_helper_file(managed_dir)
        explicit_exe = create_mock_helper_file(tmp_path / "custom")

        result = find_thermo_helper_path(explicit_exe)

        assert result == explicit_exe.resolve()

    def test_raises_for_missing_explicit_path_even_when_managed_install_exists(self, tmp_path: Path) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        create_mock_helper_file(managed_dir)
        non_existent = tmp_path / "does_not_exist" / "helper.exe"

        with pytest.raises(ThermoHelperNotFoundError, match="does_not_exist"):
            find_thermo_helper_path(non_existent)

    def test_raises_for_explicit_folder_without_executable(self, tmp_path: Path) -> None:
        empty_folder = tmp_path / "custom"
        empty_folder.mkdir()

        with pytest.raises(ThermoHelperNotFoundError, match="custom"):
            find_thermo_helper_path(empty_folder)

    def test_returns_none_when_no_explicit_path_and_no_managed_install_exist(self) -> None:
        result = find_thermo_helper_path()

        assert result is None


class TestGetThermoHelperStatus:
    def test_returns_unsupported_platform_state_for_unsupported_runtime_without_running_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)
        monkeypatch.setattr(environment, "get_platform", lambda: "freebsd")
        monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")

        status = get_thermo_helper_status()

        assert status.state is ThermoHelperState.UNSUPPORTED_PLATFORM
        assert status.path is None
        assert status.version is None
        assert not status.license_accepted
        assert not status.is_ready
        assert "'freebsd'" in status.message
        assert "'linux-x64'" in status.message
        assert len(mock_runner.commands_run) == 0

    def test_reports_missing_explicit_path_as_not_installed_without_using_managed_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper(license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        create_mock_helper_file(managed_dir)

        status = get_thermo_helper_status(tmp_path / "does_not_exist")

        assert status.state is ThermoHelperState.NOT_INSTALLED
        assert status.path is None
        assert "does_not_exist" in status.message
        assert mock_runner.commands_run == []

    def test_returns_not_installed_state_when_executable_missing_without_running_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status()

        assert status.state is ThermoHelperState.NOT_INSTALLED
        assert status.path is None
        assert status.version is None
        assert not status.license_accepted
        assert not status.is_ready
        assert "executable was not found" in status.message
        assert len(mock_runner.commands_run) == 0

    def test_not_installed_message_names_the_runtime_specific_managed_path(
        self, isolated_data_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", MockThermoHelper())
        legacy_dir = isolated_data_directory / "tools" / WIN_X64_SPECIFICATION.tool_name / WIN_X64_SPECIFICATION.version
        create_mock_helper_file(legacy_dir)

        status = get_thermo_helper_status()

        expected_path = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        assert status.state is ThermoHelperState.NOT_INSTALLED
        assert str(expected_path / WIN_X64_SPECIFICATION.executable_name) in status.message
        assert expected_path.name == "win-x64"

    def test_returns_unlicensed_state_when_version_matches_but_helper_reports_license_not_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.UNLICENSED
        assert status.path == exe.resolve()
        assert status.version == WIN_X64_SPECIFICATION.version
        assert not status.license_accepted
        assert not status.is_ready
        assert status.license_marker_path == Path(mock_runner.license_marker_path)
        assert "has not been accepted" in status.message

    def test_returns_ready_state_when_version_matches_and_helper_reports_license_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.READY
        assert status.path == exe.resolve()
        assert status.version == WIN_X64_SPECIFICATION.version
        assert status.license_accepted
        assert status.is_ready
        assert status.license_marker_path == Path(mock_runner.license_marker_path)
        assert "is ready" in status.message

    def test_returns_invalid_version_state_when_helper_reports_different_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version="0.1.0", license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.INVALID_VERSION
        assert status.path == exe.resolve()
        assert status.version == "0.1.0"
        assert not status.license_accepted
        assert not status.is_ready
        assert "reported version '0.1.0'" in status.message
        assert [command[1:] for command in mock_runner.commands_run] == [["--version"]]

    @pytest.mark.parametrize(
        ("exit_code", "state"), [(5, ThermoHelperState.UNLICENSED), (7, ThermoHelperState.INVALID_VERSION)]
    )
    def test_reports_failed_license_query_without_marker_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, state: ThermoHelperState
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_status_exit_code=exit_code, stderr="no config dir")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is state
        assert not status.license_accepted
        assert status.license_marker_path is None
        assert "no config dir" in status.message

    def test_returns_invalid_version_state_when_helper_exits_with_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(exit_code=1, stderr="fatal error")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.INVALID_VERSION
        assert status.path == exe.resolve()
        assert status.version is None
        assert not status.is_ready
        assert "exit code 1" in status.message

    def test_returns_invalid_version_state_when_helper_returns_empty_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(stdout="")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.INVALID_VERSION
        assert status.path == exe.resolve()
        assert status.version is None
        assert not status.is_ready
        assert "empty version output" in status.message

    def test_returns_invalid_version_state_when_helper_command_times_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(hang=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.INVALID_VERSION
        assert status.path == exe.resolve()
        assert status.version is None
        assert not status.is_ready
        assert "timed out" in status.message

    def test_returns_invalid_version_state_when_execution_raises_os_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(os_error=OSError("Access denied"))
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.INVALID_VERSION
        assert status.path == exe.resolve()
        assert status.version is None
        assert not status.is_ready
        assert "could not be started" in status.message


class TestLocateThermoHelper:
    def test_raises_unsupported_platform_error_for_unsupported_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        monkeypatch.setattr(environment, "get_machine", lambda: "riscv64")
        with pytest.raises(UnsupportedPlatformError, match="'riscv64'"):
            locate_thermo_helper()

    def test_raises_thermo_helper_not_found_error_when_executable_missing(self) -> None:
        with pytest.raises(ThermoHelperNotFoundError, match="executable was not found"):
            locate_thermo_helper()

    def test_raises_thermo_helper_license_error_when_license_not_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="license agreement has not been accepted"):
            locate_thermo_helper(exe)

    def test_raises_thermo_helper_config_error_when_license_folder_is_unusable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_status_exit_code=5)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperConfigError, match="license folder"):
            locate_thermo_helper(exe)

    def test_raises_thermo_helper_version_error_when_version_mismatched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version="9.9.9")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="reported version '9.9.9'"):
            locate_thermo_helper(exe)

    def test_raises_thermo_helper_version_error_when_process_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(exit_code=1, stderr="crashed")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="exit code 1"):
            locate_thermo_helper(exe)

    def test_returns_executable_path_when_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        result = locate_thermo_helper(exe)

        assert result == exe.resolve()

    def test_raises_not_found_for_missing_explicit_path_without_using_managed_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        create_mock_helper_file(managed_dir)
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperNotFoundError, match="does_not_exist"):
            locate_thermo_helper(tmp_path / "does_not_exist")

        assert mock_runner.commands_run == []

    def test_explicit_path_takes_precedence_in_location_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)
        create_mock_helper_file(managed_dir)
        explicit_exe = create_mock_helper_file(tmp_path / "custom")
        mock_runner = MockThermoHelper(version=WIN_X64_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        result = locate_thermo_helper(explicit_exe)

        assert result == explicit_exe.resolve()


class TestVerifyHelperVersion:
    def test_returns_reported_version_when_matching_expectation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version="0.1.0")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        verified = verify_helper_version(exe, "0.1.0")

        assert verified == "0.1.0"

    def test_raises_version_error_on_version_mismatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version="0.2.0")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="reported version '0.2.0', but expected '0.1.0'"):
            verify_helper_version(exe, "0.1.0")


class TestQueryHelperVersion:
    def test_extracts_first_line_from_clean_version_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(stdout="0.1.0\n")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        assert query_helper_version(exe) == "0.1.0"
        assert mock_runner.commands_run == [[str(exe), "--version"]]

    def test_raises_version_error_when_output_is_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(stdout="")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="returned empty version output"):
            query_helper_version(exe)

    def test_raises_version_error_when_process_exits_with_nonzero_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(exit_code=1, stderr="fatal error")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="exit code 1 when asked for its version: fatal error"):
            query_helper_version(exe)

    def test_raises_version_error_when_process_times_out(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(hang=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="timed out after 5.0 seconds"):
            query_helper_version(exe, timeout=5.0)

    def test_raises_version_error_when_execution_fails_with_os_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(os_error=OSError("Exec format error"))
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="could not be started"):
            query_helper_version(exe)

    def test_mentions_glibc_when_the_program_loader_is_missing_on_linux(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(os_error=FileNotFoundError("No such file or directory"))
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperVersionError, match="glibc"):
            query_helper_version(exe)


class TestQueryLicenseStatus:
    @pytest.mark.parametrize("accepted", [True, False])
    def test_reports_license_state_and_marker_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accepted: bool
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_accepted=accepted)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        license_status = query_license_status(exe)

        assert license_status.accepted is accepted
        assert license_status.marker_path == Path(mock_runner.license_marker_path)
        assert mock_runner.commands_run == [[str(exe), "--license-status"]]

    def test_strips_only_the_windows_line_ending(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(stdout="C:/My Config /.thermo-license-accepted\r\n")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        assert query_license_status(exe).marker_path == Path("C:/My Config /.thermo-license-accepted")

    @pytest.mark.parametrize(
        ("helper_options", "error_type"),
        [
            ({"license_status_exit_code": 5}, ThermoHelperConfigError),
            ({"license_status_exit_code": 7}, ThermoHelperCommandError),
            ({"stdout": ""}, ThermoHelperOutputError),
            ({"stdout": "first\nsecond\n"}, ThermoHelperOutputError),
            ({"stdout": "C:/\ufffd/.thermo-license-accepted\n"}, ThermoHelperOutputError),
            ({"hang": True}, ThermoHelperTimeoutError),
            ({"os_error": OSError("Access denied")}, ThermoHelperExecutionError),
        ],
        ids=["exit-5", "exit-7", "empty", "two-lines", "not-utf8", "timeout", "os-error"],
    )
    def test_raises_specific_error_when_the_state_cannot_be_read(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        helper_options: dict[str, Any],
        error_type: type[ThermoHelperError],
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", MockThermoHelper(**helper_options))

        with pytest.raises(error_type):
            query_license_status(exe)

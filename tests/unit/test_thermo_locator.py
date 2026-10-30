"""Unit tests for locating and reporting status of ThermoScanHeaderExtractor."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rawtrace_qc import environment
from rawtrace_qc.environment import helper_tool_directory
from rawtrace_qc.errors import (
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperVersionError,
    UnsupportedPlatformError,
)
from rawtrace_qc.thermo import (
    THERMO_HELPER_SPECIFICATION,
    ThermoHelperState,
    find_thermo_helper_path,
    get_thermo_helper_status,
    is_license_accepted,
    locate_thermo_helper,
    query_helper_version,
    verify_helper_version,
)
from tests.support.mock_helper import MockThermoHelper, create_mock_helper_file


@pytest.fixture(autouse=True)
def mock_windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "get_platform", lambda: "win32")


class TestFindThermoHelperPath:
    def test_finds_explicit_file_path_when_present(self, tmp_path: Path) -> None:
        explicit_exe = create_mock_helper_file(tmp_path / "custom")

        result = find_thermo_helper_path(explicit_exe, data_directory=tmp_path / "appdata")

        assert result == explicit_exe.resolve()

    def test_finds_executable_inside_explicit_directory(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom"
        explicit_exe = create_mock_helper_file(custom_dir)

        result = find_thermo_helper_path(custom_dir, data_directory=tmp_path / "appdata")

        assert result == explicit_exe.resolve()

    def test_finds_managed_install_in_data_directory(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "appdata"
        managed_dir = helper_tool_directory(
            THERMO_HELPER_SPECIFICATION.tool_name,
            THERMO_HELPER_SPECIFICATION.version,
            data_directory=data_dir,
        )
        managed_exe = create_mock_helper_file(managed_dir)

        result = find_thermo_helper_path(data_directory=data_dir)

        assert result == managed_exe.resolve()

    def test_explicit_path_takes_priority_over_managed_install(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "appdata"
        managed_dir = helper_tool_directory(
            THERMO_HELPER_SPECIFICATION.tool_name,
            THERMO_HELPER_SPECIFICATION.version,
            data_directory=data_dir,
        )
        create_mock_helper_file(managed_dir)
        explicit_exe = create_mock_helper_file(tmp_path / "custom")

        result = find_thermo_helper_path(explicit_exe, data_directory=data_dir)

        assert result == explicit_exe.resolve()

    def test_falls_back_to_managed_install_when_explicit_path_does_not_exist(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "appdata"
        managed_dir = helper_tool_directory(
            THERMO_HELPER_SPECIFICATION.tool_name,
            THERMO_HELPER_SPECIFICATION.version,
            data_directory=data_dir,
        )
        managed_exe = create_mock_helper_file(managed_dir)
        non_existent = tmp_path / "does_not_exist" / "helper.exe"

        result = find_thermo_helper_path(non_existent, data_directory=data_dir)

        assert result == managed_exe.resolve()

    def test_returns_none_when_neither_explicit_nor_managed_exists(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "appdata"
        non_existent = tmp_path / "custom" / "missing.exe"

        result = find_thermo_helper_path(non_existent, data_directory=data_dir)

        assert result is None


class TestGetThermoHelperStatus:
    def test_returns_unsupported_platform_state_on_non_windows_without_running_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")

        status = get_thermo_helper_status()

        assert status.state is ThermoHelperState.UNSUPPORTED_PLATFORM
        assert status.path is None
        assert status.version is None
        assert not status.license_accepted
        assert not status.is_ready
        assert "requires Windows" in status.message
        assert len(mock_runner.commands_run) == 0

    def test_returns_not_installed_state_when_executable_missing_without_running_process(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(data_directory=tmp_path / "appdata")

        assert status.state is ThermoHelperState.NOT_INSTALLED
        assert status.path is None
        assert status.version is None
        assert not status.license_accepted
        assert not status.is_ready
        assert "executable was not found" in status.message
        assert len(mock_runner.commands_run) == 0

    def test_returns_unlicensed_state_when_version_matches_but_helper_reports_license_not_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.UNLICENSED
        assert status.path == exe.resolve()
        assert status.version == THERMO_HELPER_SPECIFICATION.version
        assert not status.license_accepted
        assert not status.is_ready
        assert "--agree-to-terms" in status.message

    def test_returns_ready_state_when_version_matches_and_helper_reports_license_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.READY
        assert status.path == exe.resolve()
        assert status.version == THERMO_HELPER_SPECIFICATION.version
        assert status.license_accepted
        assert status.is_ready
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

    def test_returns_unlicensed_state_when_license_probe_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version)

        def run(args: list[str | Path], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
            if len(args) == 1:
                return subprocess.CompletedProcess(args=args, returncode=5, stdout="", stderr="no config dir")
            return mock_runner(args, timeout=timeout)

        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", run)

        status = get_thermo_helper_status(exe)

        assert status.state is ThermoHelperState.UNLICENSED
        assert not status.license_accepted
        assert "license state could not be determined" in status.message
        assert "unexpected code 5" in status.message

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
        assert "unreadable version" in status.message

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
        assert "Failed to execute" in status.message


class TestLocateThermoHelper:
    def test_raises_unsupported_platform_error_on_non_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "darwin")
        with pytest.raises(UnsupportedPlatformError, match="requires Windows"):
            locate_thermo_helper()

    def test_raises_thermo_helper_not_found_error_when_executable_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ThermoHelperNotFoundError, match="executable was not found"):
            locate_thermo_helper(data_directory=tmp_path / "appdata")

    def test_raises_thermo_helper_license_error_when_license_not_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="license agreement has not been accepted"):
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

        with pytest.raises(ThermoHelperVersionError, match="unreadable version"):
            locate_thermo_helper(exe)

    def test_returns_executable_path_when_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        result = locate_thermo_helper(exe)

        assert result == exe.resolve()

    def test_explicit_path_takes_precedence_in_location_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data_dir = tmp_path / "appdata"
        managed_dir = helper_tool_directory(
            THERMO_HELPER_SPECIFICATION.tool_name,
            THERMO_HELPER_SPECIFICATION.version,
            data_directory=data_dir,
        )
        create_mock_helper_file(managed_dir)
        explicit_exe = create_mock_helper_file(tmp_path / "custom")
        mock_runner = MockThermoHelper(version=THERMO_HELPER_SPECIFICATION.version, license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        result = locate_thermo_helper(explicit_exe, data_directory=data_dir)

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

        with pytest.raises(ThermoHelperVersionError, match="failed with exit code 1: fatal error"):
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

        with pytest.raises(ThermoHelperVersionError, match="Failed to execute"):
            query_helper_version(exe)


class TestIsLicenseAccepted:
    def test_returns_true_when_bare_invocation_exits_with_usage_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        assert is_license_accepted(exe) is True
        assert mock_runner.commands_run == [[str(exe)]]

    def test_returns_false_when_bare_invocation_exits_with_license_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_accepted=False)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        assert is_license_accepted(exe) is False
        assert mock_runner.license_accepted is False

    def test_raises_on_unexpected_exit_code(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(exit_code=5, stderr="configuration directory unavailable")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="unexpected code 5.*configuration directory unavailable"):
            is_license_accepted(exe)

    def test_raises_on_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", MockThermoHelper(hang=True))

        with pytest.raises(ThermoHelperLicenseError, match="timed out"):
            is_license_accepted(exe)

    def test_raises_on_os_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        exe = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(os_error=OSError("Access denied"))
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="Access denied"):
            is_license_accepted(exe)

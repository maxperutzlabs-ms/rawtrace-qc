"""Unit tests for displaying and accepting the Thermo license agreement."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import ThermoHelperLicenseError, ThermoHelperNotFoundError, UnsupportedPlatformError
from rawtrace_qc.thermo import accept_thermo_license, get_thermo_license_text, managed_thermo_helper_directory
from tests.support.mock_helper import MockThermoHelper, create_mock_helper_file
from tests.support.thermo_helper import WIN_X64_SPECIFICATION


@pytest.fixture(autouse=True)
def mock_windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "get_platform", lambda: "win32")
    monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")


class TestGetThermoLicenseText:
    def test_returns_license_text_without_accepting_terms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        license_text = "Thermo agreement\nAdditional terms\n"
        mock_runner = MockThermoHelper(license_text=license_text)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        result = get_thermo_license_text(executable)

        assert result == license_text
        assert mock_runner.license_accepted is False
        assert mock_runner.commands_run == [
            [str(executable.resolve()), "--version"],
            [str(executable.resolve()), "--thermo-license"],
        ]

    def test_raises_when_helper_fails_to_display_license_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_text_exit_code=1, stderr="license output unavailable")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="failed with exit code 1"):
            get_thermo_license_text(executable)

    def test_raises_when_helper_returns_empty_license_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_text="")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="returned empty license text"):
            get_thermo_license_text(executable)


class TestExplicitHelperPath:
    @pytest.mark.parametrize("license_function", [get_thermo_license_text, accept_thermo_license])
    def test_missing_explicit_path_raises_without_running_the_managed_helper(
        self, license_function: Callable[..., object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        managed_dir = managed_thermo_helper_directory(WIN_X64_SPECIFICATION, data_directory=tmp_path)
        create_mock_helper_file(managed_dir)
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperNotFoundError, match="does_not_exist"):
            license_function(tmp_path / "does_not_exist", data_directory=tmp_path)

        assert mock_runner.commands_run == []
        assert mock_runner.license_accepted is False


class TestAcceptThermoLicense:
    def test_accepts_terms_and_confirms_acceptance_with_the_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        accept_thermo_license(executable)

        assert mock_runner.license_accepted is True
        assert mock_runner.commands_run == [
            [str(executable.resolve()), "--version"],
            [str(executable.resolve())],
            [str(executable.resolve()), "--agree-to-terms"],
            [str(executable.resolve())],
        ]

    def test_raises_when_helper_exits_abnormally(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(agreement_exit_code=1, stderr="agreement failed")
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="failed with exit code 1"):
            accept_thermo_license(executable)

        assert mock_runner.license_accepted is False

    def test_raises_when_helper_still_reports_license_not_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(records_acceptance=False)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        with pytest.raises(ThermoHelperLicenseError, match="still reports the Thermo license as not accepted"):
            accept_thermo_license(executable)

    def test_does_not_run_acceptance_when_helper_reports_license_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = create_mock_helper_file(tmp_path)
        mock_runner = MockThermoHelper(license_accepted=True)
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)

        accept_thermo_license(executable)

        assert mock_runner.commands_run == [
            [str(executable.resolve()), "--version"],
            [str(executable.resolve())],
        ]


class TestUnsupportedRuntime:
    @pytest.mark.parametrize("operation", [get_thermo_license_text, accept_thermo_license])
    def test_license_operations_raise_unsupported_platform_error_without_running_process(
        self, operation: Callable[[], object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_runner = MockThermoHelper()
        monkeypatch.setattr("rawtrace_qc.thermo.locator.execute_helper_process", mock_runner)
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        monkeypatch.setattr(environment, "get_machine", lambda: "x86_64")

        with pytest.raises(UnsupportedPlatformError, match="'linux-x64'"):
            operation()

        assert mock_runner.commands_run == []

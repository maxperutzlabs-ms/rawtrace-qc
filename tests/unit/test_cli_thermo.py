from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc import environment
from rawtrace_qc.cli import main
from rawtrace_qc.cli import thermo as thermo_cli_module
from rawtrace_qc.environment import helper_tool_directory
from rawtrace_qc.errors import ThermoHelperChecksumError, ThermoHelperDownloadError
from rawtrace_qc.thermo import THERMO_HELPER_SPECIFICATION
from rawtrace_qc.thermo import locator as locator_module
from tests.support.mock_helper import MockThermoHelper, create_mock_helper_file


def _create_helper(data_directory: Path) -> Path:
    helper_directory = helper_tool_directory(
        THERMO_HELPER_SPECIFICATION.tool_name,
        THERMO_HELPER_SPECIFICATION.version,
        data_directory=data_directory,
    )
    return create_mock_helper_file(helper_directory)


class TestThermoStatusCommand:
    @pytest.mark.parametrize(
        ("state", "version", "licensed", "platform", "exit_code", "action"),
        [
            ("not_installed", None, False, "win32", 1, "thermo install"),
            ("unlicensed", THERMO_HELPER_SPECIFICATION.version, False, "win32", 1, "thermo accept-license"),
            ("invalid_version", "9.9.9", True, "win32", 1, "pinned helper version"),
            ("unsupported_platform", None, False, "linux", 1, "requires Windows"),
            ("ready", THERMO_HELPER_SPECIFICATION.version, True, "win32", 0, "is ready"),
        ],
    )
    def test_status_reports_each_helper_state(
        self,
        state: str,
        version: str | None,
        licensed: bool,
        platform: str,
        exit_code: int,
        action: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        data_directory = tmp_path / "appdata"
        helper = None
        if version is not None:
            helper = _create_helper(data_directory)
        mock_helper = MockThermoHelper(
            version=version or THERMO_HELPER_SPECIFICATION.version, license_accepted=licensed
        )
        monkeypatch.setattr(environment, "get_platform", lambda: platform)
        monkeypatch.setattr(locator_module, "execute_helper_process", mock_helper)

        result = main(["thermo", "status", "--data-directory", str(data_directory)])

        output = capsys.readouterr().out
        assert result == exit_code
        assert f"Thermo helper status: {state}" in output
        assert action in output
        if helper is None or platform != "win32":
            assert mock_helper.commands_run == []
        else:
            expected_commands = [["--version"]] if state == "invalid_version" else [["--version"], []]
            assert [command[1:] for command in mock_helper.commands_run] == expected_commands


class TestThermoSetupCommands:
    def test_install_passes_offline_archive_and_data_directory_to_library(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_path = tmp_path / "helper.zip"
        archive_path.write_bytes(b"mock archive")
        data_directory = tmp_path / "shared-tools"
        executable = data_directory / "ThermoScanHeaderExtractor.exe"
        calls: dict[str, object] = {}

        def fake_install(**kwargs: object) -> Path:
            calls.update(kwargs)
            return executable

        monkeypatch.setattr(thermo_cli_module, "install_thermo_helper", fake_install)

        result = main(
            [
                "thermo",
                "install",
                "--from-zip",
                str(archive_path),
                "--data-directory",
                str(data_directory),
            ]
        )

        output = capsys.readouterr().out
        assert result == 0
        assert calls["archive_path"] == archive_path
        assert calls["data_directory"] == data_directory
        assert calls["specification"] is THERMO_HELPER_SPECIFICATION
        assert str(executable) in output
        assert "thermo accept-license" in output

    def test_install_reports_library_errors_with_failure_exit_code_and_status_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fail_install(**_kwargs: object) -> Path:
            raise ThermoHelperChecksumError("Archive checksum did not match.")

        monkeypatch.setattr(thermo_cli_module, "install_thermo_helper", fail_install)

        result = main(["thermo", "install", "--from-zip", str(tmp_path / "bad.zip")])

        captured = capsys.readouterr()
        assert result == 1
        assert "Archive checksum did not match." in captured.err
        assert "Check setup with `rawtrace-qc thermo status`." in captured.err

    def test_install_reports_download_error_with_failure_exit_code_and_status_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fail_install(**_kwargs: object) -> Path:
            raise ThermoHelperDownloadError("Failed to reach download server.")

        monkeypatch.setattr(thermo_cli_module, "install_thermo_helper", fail_install)

        result = main(["thermo", "install"])

        captured = capsys.readouterr()
        assert result == 1
        assert "Failed to reach download server." in captured.err
        assert "Check setup with `rawtrace-qc thermo status`." in captured.err

    def test_accept_license_displays_terms_and_records_explicit_acceptance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        data_directory = tmp_path / "appdata"
        _create_helper(data_directory)
        mock_helper = MockThermoHelper()
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(locator_module, "execute_helper_process", mock_helper)

        result = main(["thermo", "accept-license", "--data-directory", str(data_directory)])

        output = capsys.readouterr().out
        assert result == 0
        assert output.index("Mock Thermo license terms.") < output.index("Thermo license acceptance is recorded")
        assert [command[1:] for command in mock_helper.commands_run] == [
            ["--version"],
            ["--thermo-license"],
            ["--version"],
            [],
            ["--agree-to-terms"],
            [],
        ]
        assert mock_helper.license_accepted is True

    def test_accept_license_reports_when_helper_does_not_record_acceptance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        data_directory = tmp_path / "appdata"
        _create_helper(data_directory)
        mock_helper = MockThermoHelper(records_acceptance=False)
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(locator_module, "execute_helper_process", mock_helper)

        result = main(["thermo", "accept-license", "--data-directory", str(data_directory)])

        captured = capsys.readouterr()
        assert result == 1
        assert "Mock Thermo license terms." in captured.out
        assert "still reports the Thermo license as not accepted" in captured.err
        assert "thermo accept-license" in captured.err

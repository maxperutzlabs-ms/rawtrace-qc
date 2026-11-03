from __future__ import annotations

import builtins
import sys

import pytest
from rawtrace_qc.cli import main
from rawtrace_qc.cli.errors import print_cli_error
from rawtrace_qc.errors import (
    ThermoHelperChecksumError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperVersionError,
    UnsupportedPlatformError,
)


class TestCliEntryPoint:
    def test_missing_optional_dependency_prints_install_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setitem(sys.modules, "rawtrace_qc.cli.main", None)
        monkeypatch.setitem(sys.modules, "cyclopts", None)

        original_import = builtins.__import__

        def import_without_cyclopts(name: str, *args: object, **kwargs: object) -> object:
            if name == "cyclopts" or name == "rawtrace_qc.cli.main":
                raise ModuleNotFoundError("No module named 'cyclopts'", name="cyclopts")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_without_cyclopts)

        result = main(["thermo", "status"])

        assert result == 2
        assert "uv sync --extra cli" in capsys.readouterr().err

    def test_main_help_runs_without_arguments(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        result = main(["--help"])

        output = capsys.readouterr().out
        assert result == 0
        assert "rawtrace-qc" in output
        assert "thermo" in output


class TestCliErrors:
    def test_print_cli_error_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        error = ThermoHelperNotFoundError("Helper not found.")
        print_cli_error(error)

        captured = capsys.readouterr()
        assert "Error: Helper not found." in captured.err
        assert "rawtrace-qc thermo install" in captured.err

    def test_print_cli_error_license(self, capsys: pytest.CaptureFixture[str]) -> None:
        error = ThermoHelperLicenseError("License not accepted.")
        print_cli_error(error)

        captured = capsys.readouterr()
        assert "Error: License not accepted." in captured.err
        assert "rawtrace-qc thermo accept-license" in captured.err

    def test_print_cli_error_version(self, capsys: pytest.CaptureFixture[str]) -> None:
        error = ThermoHelperVersionError("Version mismatch.")
        print_cli_error(error)

        captured = capsys.readouterr()
        assert "Error: Version mismatch." in captured.err
        assert "thermo install --overwrite" in captured.err

    def test_print_cli_error_unsupported_platform(self, capsys: pytest.CaptureFixture[str]) -> None:
        error = UnsupportedPlatformError("Non-Windows.")
        print_cli_error(error)

        captured = capsys.readouterr()
        assert "Error: Non-Windows." in captured.err
        assert "Thermo .raw extraction is not supported on this system" in captured.err

    def test_print_cli_error_thermo_fallback_hint(self, capsys: pytest.CaptureFixture[str]) -> None:
        error = ThermoHelperChecksumError("Bad checksum.")
        print_cli_error(error, thermo=True)

        captured = capsys.readouterr()
        assert "Error: Bad checksum." in captured.err
        assert "Check setup with `rawtrace-qc thermo status`." in captured.err

    def test_print_cli_error_without_thermo_flag_omits_status_hint(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        error = ThermoHelperChecksumError("Bad checksum.")
        print_cli_error(error, thermo=False)

        captured = capsys.readouterr()
        assert "Error: Bad checksum." in captured.err
        assert "Check setup with `rawtrace-qc thermo status`." not in captured.err

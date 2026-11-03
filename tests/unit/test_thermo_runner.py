"""Unit tests for building and running ThermoScanHeaderExtractor commands."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from rawtrace_qc.errors import (
    OperationCancelledError,
    ThermoHelperCommandError,
    ThermoHelperExecutableNotFoundError,
    ThermoHelperOutputError,
    ThermoHelperTimeoutError,
)
from rawtrace_qc.thermo import build_thermo_helper_command, run_thermo_helper
from rawtrace_qc.thermo import runner as runner_module

_MOCK_HELPER_SCRIPT = Path(__file__).resolve().parents[1] / "support" / "mock_helper.py"


def _mock_helper_command(mode: str) -> list[str | Path]:
    return [sys.executable, _MOCK_HELPER_SCRIPT, f"--runner-test-{mode}"]


class TestBuildThermoHelperCommand:
    @pytest.mark.parametrize(
        ("select_ms1", "select_msn", "expected_flags"),
        [
            (True, True, ["--ms1", "--msn"]),
            (True, False, ["--ms1"]),
            (False, True, ["--msn"]),
        ],
    )
    def test_includes_selected_ms_levels(
        self,
        select_ms1: bool,
        select_msn: bool,
        expected_flags: list[str],
    ) -> None:
        command = build_thermo_helper_command(
            "ThermoScanHeaderExtractor.exe",
            "sample.raw",
            select_ms1=select_ms1,
            select_msn=select_msn,
        )

        assert command == [
            "ThermoScanHeaderExtractor.exe",
            "sample.raw",
            *expected_flags,
        ]

    def test_includes_precision_and_output_options_as_separate_arguments(self, tmp_path: Path) -> None:
        executable = tmp_path / "helper tools" / "ThermoScanHeaderExtractor.exe"
        input_path = tmp_path / "raw files" / "\u00b5 sample.raw"
        output_directory = tmp_path / "reports" / "\u03bb output"

        command = build_thermo_helper_command(
            executable,
            input_path,
            output_directory,
            "\u00e9chantillon 1",
            precision_mode="high",
            select_ms1=True,
            select_msn=False,
        )

        assert command == [
            str(executable),
            str(input_path),
            "--high-precision",
            "--ms1",
            "-o",
            str(output_directory),
            "--name",
            "\u00e9chantillon 1",
        ]

    def test_rejects_selection_without_any_ms_level(self) -> None:
        with pytest.raises(ValueError, match="At least one of select_ms1 or select_msn"):
            build_thermo_helper_command(
                "ThermoScanHeaderExtractor.exe",
                "sample.raw",
                select_ms1=False,
                select_msn=False,
            )

    def test_rejects_invalid_precision_mode(self) -> None:
        with pytest.raises(ValueError, match="precision_mode must be 'low' or 'high'"):
            build_thermo_helper_command(
                "ThermoScanHeaderExtractor.exe",
                "sample.raw",
                precision_mode="medium",  # type: ignore[arg-type]
            )


class TestRunThermoHelper:
    def test_captures_stdout_and_stderr_from_mock_helper_process(self) -> None:
        result = run_thermo_helper(_mock_helper_command("success"), timeout=5.0)

        assert result.returncode == 0
        assert result.stdout.splitlines() == ["mock helper stdout"]
        assert result.stderr.splitlines() == ["mock helper stderr"]

    def test_raises_command_error_with_captured_output_from_mock_helper_process(self) -> None:
        with pytest.raises(ThermoHelperCommandError) as error:
            run_thermo_helper(_mock_helper_command("failure"), timeout=5.0)

        assert error.value.stdout.splitlines() == ["mock helper stdout"]
        assert error.value.stderr.splitlines() == ["mock helper stderr"]
        assert "status 7" in str(error.value)
        assert "mock helper stderr" in str(error.value)

    def test_raises_timeout_with_partial_output_from_mock_helper_process(self) -> None:
        with pytest.raises(ThermoHelperTimeoutError) as error:
            run_thermo_helper(_mock_helper_command("timeout"), timeout=0.5)

        assert error.value.stdout.splitlines() == ["mock helper stdout"]
        assert error.value.stderr.splitlines() == ["mock helper stderr"]
        assert "0.5-second timeout" in str(error.value)

    def test_cancel_event_stops_the_running_mock_helper_process(self) -> None:
        cancel = threading.Event()
        timer = threading.Timer(0.2, cancel.set)
        timer.start()
        started = time.monotonic()

        with pytest.raises(OperationCancelledError):
            run_thermo_helper(_mock_helper_command("timeout"), timeout=25.0, cancel=cancel)

        timer.join()
        assert time.monotonic() - started < 20

    def test_captures_output_when_a_cancel_event_is_never_set(self) -> None:
        result = run_thermo_helper(_mock_helper_command("success"), timeout=5.0, cancel=threading.Event())

        assert result.returncode == 0
        assert result.stdout.splitlines() == ["mock helper stdout"]
        assert result.stderr.splitlines() == ["mock helper stderr"]

    def test_raises_command_error_when_a_cancel_event_is_never_set(self) -> None:
        with pytest.raises(ThermoHelperCommandError) as error:
            run_thermo_helper(_mock_helper_command("failure"), timeout=5.0, cancel=threading.Event())

        assert error.value.returncode == 7

    def test_raises_timeout_with_partial_output_when_a_cancel_event_is_never_set(self) -> None:
        with pytest.raises(ThermoHelperTimeoutError) as error:
            run_thermo_helper(_mock_helper_command("timeout"), timeout=0.5, cancel=threading.Event())

        assert error.value.stdout.splitlines() == ["mock helper stdout"]
        assert "0.5-second timeout" in str(error.value)

    def test_translates_nonzero_exit_from_mocked_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def return_failure(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=4,
                stdout=b"captured output",
                stderr=b"captured \xff error",
            )

        monkeypatch.setattr(runner_module, "_execute_process", return_failure)

        with pytest.raises(ThermoHelperCommandError) as error:
            run_thermo_helper(["helper.exe", "input.raw"])

        assert error.value.stdout == "captured output"
        assert error.value.stderr == r"captured \xff error"

    def test_translates_timeout_from_mocked_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_timeout(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
            raise subprocess.TimeoutExpired(
                command,
                timeout,
                output=b"partial output",
                stderr=b"partial error",
            )

        monkeypatch.setattr(runner_module, "_execute_process", raise_timeout)

        with pytest.raises(ThermoHelperTimeoutError) as error:
            run_thermo_helper(["helper.exe", "input.raw"], timeout=1.0)

        assert error.value.stdout == "partial output"
        assert error.value.stderr == "partial error"

    def test_translates_missing_executable_from_mocked_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_missing_executable(_command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
            raise FileNotFoundError("helper.exe was not found")

        monkeypatch.setattr(runner_module, "_execute_process", raise_missing_executable)

        with pytest.raises(ThermoHelperExecutableNotFoundError) as error:
            run_thermo_helper(["helper.exe", "input.raw"])

        assert error.value.stdout == ""
        assert error.value.stderr == ""
        assert "helper.exe was not found" in str(error.value)

    def test_translates_unreadable_output_from_mocked_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def return_unreadable_output(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=b"\xff",
                stderr=b"captured error",
            )

        monkeypatch.setattr(runner_module, "_execute_process", return_unreadable_output)

        with pytest.raises(ThermoHelperOutputError) as error:
            run_thermo_helper(["helper.exe", "input.raw"])

        assert error.value.stdout == r"\xff"
        assert error.value.stderr == "captured error"
        assert "not valid UTF-8" in str(error.value)

    def test_rejects_empty_command_and_nonpositive_timeout(self) -> None:
        with pytest.raises(ValueError, match="command must contain an executable"):
            run_thermo_helper([])

        with pytest.raises(ValueError, match="timeout must be greater than zero"):
            run_thermo_helper(["helper.exe"], timeout=0)

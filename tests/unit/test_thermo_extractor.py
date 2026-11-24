"""Unit tests for ThermoExtractor using mocked runner and locator."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pyarrow as pa
import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import (
    AcquisitionAccessError,
    AcquisitionReadError,
    ArtifactValidationError,
    ExtractionError,
    NoScansError,
    OperationCancelledError,
    ThermoHelperCommandError,
    ThermoHelperConfigError,
    ThermoHelperExecutionError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    ThermoHelperTimeoutError,
    TraceWriteError,
    UnsupportedPlatformError,
)
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.thermo import locator as locator_module
from rawtrace_qc.thermo import thermo_config_directory
from rawtrace_qc.thermo.runner import THERMO_CONFIG_DIRECTORY_VARIABLE
from rawtrace_qc.traces import load_trace, write_trace
from tests.support.mock_helper import MockThermoHelper, create_mock_helper_file


def _create_valid_parquet(
    path: Path,
    *,
    ms_level_file: str = "ms1",
    precision_mode: str = "low",
    source_filename: str = "sample.raw",
) -> None:
    trace_type = pa.float32() if precision_mode == "low" else pa.float64()
    table = pa.Table.from_arrays(
        [
            pa.array([1, 2], type=pa.int32()),
            pa.array([100.0, 200.0], type=trace_type),
            pa.array([10.0, 20.0], type=trace_type),
            pa.array([1.0, 2.0], type=trace_type),
            pa.array([1, 1] if ms_level_file == "ms1" else [2, 2], type=pa.int8()),
        ],
        names=["scan_id", "total_ion_current", "base_peak_intensity", "retention_time_sec", "ms_level"],
    )
    write_trace(
        table,
        path,
        vendor="thermo",
        source_filename=source_filename,
        ms_level_file=ms_level_file,
        precision_mode=precision_mode,
        row_granularity="spectrum",
        extracted_at="2026-09-30T12:00:00Z",
        acquisition_start_time="2026-09-30T10:00:00Z",
        generator="ThermoScanHeaderExtractor/0.1.0",
        source_id="TEST_001",
    )


class TestThermoExtractorUnit:
    @pytest.fixture(autouse=True)
    def force_windows_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")

    def test_missing_helper_raises_not_found_error_without_running(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()

        runner_called = False

        def mock_runner(*args, **kwargs):
            nonlocal runner_called
            runner_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        extractor = ThermoExtractor()
        with pytest.raises(ThermoHelperNotFoundError):
            extractor.extract(raw_file)

        assert not runner_called

    def test_unlicensed_helper_raises_license_error_without_running(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        helper_path = create_mock_helper_file(tmp_path / "helper")
        helper_process = MockThermoHelper()
        monkeypatch.setattr(locator_module, "execute_helper_process", helper_process)

        runner_called = False

        def mock_runner(*args, **kwargs):
            nonlocal runner_called
            runner_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        extractor = ThermoExtractor(helper_path=helper_path)
        with pytest.raises(ThermoHelperLicenseError):
            extractor.extract(raw_file)

        assert not runner_called
        assert [command[1:] for command in helper_process.commands_run] == [["--version"], ["--license-status"]]

    def test_empty_selection_creates_nothing_without_invoking_runner_or_locator(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "no-out"

        locator_called = False
        runner_called = False

        def mock_locate(*args, **kwargs):
            nonlocal locator_called
            locator_called = True
            return Path("dummy.exe")

        def mock_runner(*args, **kwargs):
            nonlocal runner_called
            runner_called = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.locate_thermo_helper", mock_locate)
        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        result = ThermoExtractor().extract(
            raw_file,
            output_directory=output_directory,
            select_ms1=False,
            select_msn=False,
        )

        assert result.ms1_path is None
        assert result.msn_path is None
        assert not output_directory.exists()
        assert not locator_called
        assert not runner_called

    def test_unreadable_file_cleans_up_and_reports_the_helper_reason(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "output-dir"

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_failing_runner(command, **kwargs):
            out_idx = command.index("-o") + 1
            temp_out = Path(command[out_idx])
            (temp_out / "sample.raw.ms1-trace.parquet").write_text("partial")
            raise ThermoHelperCommandError(
                "Helper failed",
                returncode=3,
                stdout="diagnostic stdout",
                stderr="diagnostic stderr",
            )

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_failing_runner)

        with pytest.raises(AcquisitionReadError, match="'sample.raw'.*diagnostic stderr") as error:
            ThermoExtractor().extract(raw_file, output_directory=output_directory)

        assert error.value.path == raw_file.resolve()
        assert isinstance(error.value.__cause__, ThermoHelperCommandError)
        assert not output_directory.exists() or not list(output_directory.iterdir())

    def test_passes_the_cancel_event_and_config_folder_to_the_helper_and_cleans_up_partial_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "output-dir"
        cancel = threading.Event()
        received: list[object] = []

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_cancelled_runner(command, **kwargs):
            received.extend((kwargs["cancel"], kwargs["config_directory"]))
            temp_out = Path(command[command.index("-o") + 1])
            (temp_out / "sample.raw.ms1-trace.parquet").write_text("partial")
            raise OperationCancelledError("stopped")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_cancelled_runner)

        with pytest.raises(OperationCancelledError):
            ThermoExtractor(cancel=cancel).extract(raw_file, output_directory=output_directory)

        assert received == [cancel, thermo_config_directory()]
        assert not output_directory.exists()

    @pytest.mark.parametrize(
        ("helper_error", "expected"),
        [
            (ThermoHelperCommandError("usage", returncode=1, stdout="", stderr=""), ThermoHelperCommandError),
            (ThermoHelperCommandError("access", returncode=2, stdout="", stderr=""), AcquisitionAccessError),
            (ThermoHelperCommandError("license", returncode=4, stdout="", stderr=""), ThermoHelperLicenseError),
            (ThermoHelperCommandError("config", returncode=5, stdout="", stderr=""), ThermoHelperConfigError),
            (ThermoHelperCommandError("write", returncode=6, stdout="", stderr=""), TraceWriteError),
            (ThermoHelperCommandError("internal", returncode=7, stdout="", stderr=""), ThermoHelperCommandError),
            (ThermoHelperCommandError("newer", returncode=42, stdout="", stderr=""), ThermoHelperCommandError),
            (ThermoHelperCommandError("signal", returncode=-11, stdout="", stderr=""), ThermoHelperCommandError),
            (ThermoHelperTimeoutError("timeout", stdout="", stderr=""), ExtractionError),
            (None, ThermoHelperExecutionError),
        ],
    )
    def test_helper_failures_raise_the_error_class_of_their_cause(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        helper_error: Exception | None,
        expected: type[Exception],
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_runner(command, **kwargs):
            if helper_error is not None:
                raise helper_error
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        with pytest.raises(expected) as error:
            ThermoExtractor().extract(raw_file, output_directory=tmp_path / "output")

        assert type(error.value) is expected

    def test_license_folder_error_names_the_folder_of_the_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        monkeypatch.setenv(THERMO_CONFIG_DIRECTORY_VARIABLE, str(tmp_path / "user-config"))
        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_runner(command, **kwargs):
            raise ThermoHelperCommandError("config", returncode=5, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        with pytest.raises(ThermoHelperConfigError) as error:
            ThermoExtractor().extract(raw_file, output_directory=tmp_path / "output")

        assert str(tmp_path / "user-config") in str(error.value)

    def test_runner_success_with_invalid_output_content_is_caught_by_validation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "out-invalid"

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_runner_corrupt(command, **kwargs):
            out_idx = command.index("-o") + 1
            temp_out = Path(command[out_idx])
            (temp_out / "sample.raw.ms1-trace.parquet").write_bytes(b"NOT_A_PARQUET_FILE")
            (temp_out / "sample.raw.msn-trace.parquet").write_bytes(b"NOT_A_PARQUET_FILE")
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner_corrupt)

        with pytest.raises(ArtifactValidationError):
            ThermoExtractor().extract(raw_file, output_directory=output_directory)

        assert not output_directory.exists() or not list(output_directory.iterdir())

    @pytest.mark.parametrize(
        ("output_name", "thermo_stem", "bruker_stem"),
        [
            (None, "sample.raw", "sample.d"),
            ("report.raw", "report.raw", "report.raw"),
        ],
    )
    def test_output_naming_and_location_match_bruker(
        self,
        bruker_fixture: Path,
        monkeypatch: pytest.MonkeyPatch,
        output_name: str | None,
        thermo_stem: str,
        bruker_stem: str,
    ) -> None:
        raw_file = bruker_fixture.parent / "sample.raw"
        raw_file.touch()

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_successful_runner(command, **kwargs):
            out_idx = command.index("-o") + 1
            temp_out = Path(command[out_idx])
            name_idx = command.index("--name") + 1
            name = command[name_idx]
            _create_valid_parquet(
                temp_out / f"{name}.ms1-trace.parquet",
                ms_level_file="ms1",
                source_filename=raw_file.name,
            )
            _create_valid_parquet(
                temp_out / f"{name}.msn-trace.parquet",
                ms_level_file="msn",
                source_filename=raw_file.name,
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_successful_runner)

        result = ThermoExtractor().extract(
            raw_file,
            output_name=output_name,
            precision_mode="low",
            select_msn=False,
        )
        bruker_result = BrukerExtractor().extract(
            bruker_fixture,
            output_name=output_name,
            select_msn=False,
        )

        assert result.ms1_path is not None
        assert bruker_result.ms1_path is not None
        assert result.ms1_path.parent == bruker_result.ms1_path.parent
        assert result.ms1_path.parent == bruker_fixture.parent
        assert result.ms1_path.name == f"{thermo_stem}.ms1-trace.parquet"
        assert bruker_result.ms1_path.name == f"{bruker_stem}.ms1-trace.parquet"
        if output_name is not None:
            assert result.ms1_path == bruker_result.ms1_path
        assert result.msn_path is None
        assert result.ms1_path.is_file()
        assert not (bruker_fixture.parent / f"{thermo_stem}.msn-trace.parquet").exists()

    @pytest.mark.parametrize(
        ("select_ms1", "select_msn", "match"),
        [(True, False, "no MS1 data"), (False, True, "no MSn data"), (True, True, "no MS1 or MSn scans")],
    )
    def test_exit_code_8_reports_the_missing_levels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, select_ms1: bool, select_msn: bool, match: str
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_no_scans_runner(command, **kwargs):
            raise ThermoHelperCommandError("Helper failed", returncode=8, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_no_scans_runner)

        with pytest.raises(NoScansError, match=match):
            ThermoExtractor().extract(
                raw_file,
                output_directory=tmp_path / "output",
                select_ms1=select_ms1,
                select_msn=select_msn,
            )

    def test_existing_output_is_overwritten(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "overwrite-dir"

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_runner(command, **kwargs):
            out_idx = command.index("-o") + 1
            temp_out = Path(command[out_idx])
            prec = "high" if "--high-precision" in command else "low"
            _create_valid_parquet(
                temp_out / "sample.raw.ms1-trace.parquet",
                ms_level_file="ms1",
                precision_mode=prec,
            )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_runner)

        first = ThermoExtractor().extract(
            raw_file,
            output_directory=output_directory,
            precision_mode="low",
            select_msn=False,
        )
        second = ThermoExtractor().extract(
            raw_file,
            output_directory=output_directory,
            precision_mode="high",
            select_msn=False,
        )

        assert first.ms1_path == second.ms1_path
        assert second.ms1_path is not None
        assert load_trace(second.ms1_path).metadata["precision_mode"] == "high"

    def test_unsupported_platform_raises_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "freebsd")
        monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()

        with pytest.raises(UnsupportedPlatformError):
            ThermoExtractor().extract(raw_file)

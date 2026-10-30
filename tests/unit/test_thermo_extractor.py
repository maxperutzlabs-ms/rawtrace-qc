"""Unit tests for ThermoExtractor using mocked runner and locator."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pyarrow as pa
import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ArtifactValidationError,
    ThermoHelperCommandError,
    ThermoHelperLicenseError,
    ThermoHelperNotFoundError,
    UnsupportedPlatformError,
)
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.thermo import locator as locator_module
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

        extractor = ThermoExtractor(data_directory=tmp_path / "empty-app-data")
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
        assert [command[1:] for command in helper_process.commands_run] == [["--version"], []]

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

    def test_runner_failure_cleans_up_and_attaches_output(
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
                stdout="diagnostic stdout",
                stderr="diagnostic stderr",
            )

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_failing_runner)

        with pytest.raises(ThermoHelperCommandError) as error:
            ThermoExtractor().extract(raw_file, output_directory=output_directory)

        assert "diagnostic stdout" in error.value.stdout
        assert "diagnostic stderr" in error.value.stderr
        assert not output_directory.exists() or not list(output_directory.iterdir())

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

    def test_ms1_only_acquisition_with_explicit_msn_selection_raises_runtime_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()
        output_directory = tmp_path / "msn-only"

        monkeypatch.setattr(
            "rawtrace_qc.extractors.thermo.locate_thermo_helper",
            lambda *args, **kwargs: Path("mock.exe"),
        )

        def mock_ms1_only_runner(command, **kwargs):
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr("rawtrace_qc.extractors.thermo.run_thermo_helper", mock_ms1_only_runner)

        with pytest.raises(RuntimeError, match="no MSn scans"):
            ThermoExtractor().extract(
                raw_file,
                output_directory=output_directory,
                select_ms1=False,
                select_msn=True,
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
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        raw_file = tmp_path / "sample.raw"
        raw_file.touch()

        with pytest.raises(UnsupportedPlatformError):
            ThermoExtractor().extract(raw_file)

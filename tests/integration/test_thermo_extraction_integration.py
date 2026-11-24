"""Integration tests for ThermoExtractor using a real .raw fixture and helper."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from rawtrace_qc.extractors import ThermoExtractor
from rawtrace_qc.traces import load_trace

pytestmark = pytest.mark.network


class TestThermoExtractionIntegration:
    def test_extracts_real_thermo_raw_and_verifies_known_structure(
        self,
        thermo_helper_executable: Path,
        thermo_raw_fixture: Path,
        tmp_path: Path,
    ) -> None:
        extractor = ThermoExtractor(helper_path=thermo_helper_executable)
        output_dir = tmp_path / "thermo_traces"

        result = extractor.extract(
            thermo_raw_fixture,
            output_directory=output_dir,
            precision_mode="low",
        )

        assert result.ms1_path is not None
        assert result.msn_path is not None

        ms1 = load_trace(result.ms1_path)
        msn = load_trace(result.msn_path)

        assert ms1.metadata["vendor"] == "thermo"
        assert ms1.metadata["ms_level_file"] == "ms1"
        assert ms1.metadata["row_granularity"] == "spectrum"
        assert ms1.metadata["source_filename"] == "exploris480_ms1_dia_3cycles.raw"
        assert ms1.metadata["source_id"] == "MA10459C_20260930114656"
        assert ms1.metadata["acquisition_start_time"] == "2026-09-30T11:46:56"

        assert msn.metadata["vendor"] == "thermo"
        assert msn.metadata["ms_level_file"] == "msn"
        assert msn.metadata["row_granularity"] == "spectrum"
        assert msn.metadata["source_filename"] == "exploris480_ms1_dia_3cycles.raw"
        assert msn.metadata["source_id"] == "MA10459C_20260930114656"
        assert msn.metadata["acquisition_start_time"] == "2026-09-30T11:46:56"

        assert ms1.table.num_rows == 3
        assert msn.table.num_rows == 36

        assert ms1.table["scan_id"].to_pylist() == [1, 14, 27]
        assert set(ms1.table["ms_level"].to_pylist()) == {1}
        assert set(msn.table["ms_level"].to_pylist()) == {2}

    def test_single_level_ms1_extraction(
        self,
        thermo_helper_executable: Path,
        thermo_raw_fixture: Path,
        tmp_path: Path,
    ) -> None:
        extractor = ThermoExtractor(helper_path=thermo_helper_executable)
        output_dir = tmp_path / "ms1_only"

        result = extractor.extract(
            thermo_raw_fixture,
            output_directory=output_dir,
            select_ms1=True,
            select_msn=False,
        )

        assert result.ms1_path is not None
        assert result.msn_path is None
        assert result.ms1_path.is_file()
        assert not (output_dir / f"{thermo_raw_fixture.name}.msn-trace.parquet").exists()

    def test_high_precision_mode_produces_float64(
        self,
        thermo_helper_executable: Path,
        thermo_raw_fixture: Path,
        tmp_path: Path,
    ) -> None:
        extractor = ThermoExtractor(helper_path=thermo_helper_executable)
        output_dir = tmp_path / "high_precision"

        result = extractor.extract(
            thermo_raw_fixture,
            output_directory=output_dir,
            precision_mode="high",
            select_msn=False,
        )

        assert result.ms1_path is not None
        ms1 = load_trace(result.ms1_path)
        assert ms1.metadata["precision_mode"] == "high"
        assert ms1.table.schema.field("retention_time_sec").type == pa.float64()
        assert ms1.table.schema.field("total_ion_current").type == pa.float64()
        assert ms1.table.schema.field("base_peak_intensity").type == pa.float64()

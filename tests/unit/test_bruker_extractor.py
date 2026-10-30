from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pyarrow as pa
import pytest
from rawtrace_qc.extractors import BrukerExtractor
from rawtrace_qc.traces import load_trace


class TestBrukerExtractor:
    def test_default_selection_writes_both_levels_and_uses_native_frame_intensities(self, bruker_fixture: Path) -> None:
        result = BrukerExtractor().extract(bruker_fixture, output_directory=bruker_fixture / "out")

        assert result.ms1_path is not None
        assert result.msn_path is not None
        ms1 = load_trace(result.ms1_path)
        msn = load_trace(result.msn_path)
        assert ms1.table.column_names == [
            "scan_id",
            "total_ion_current",
            "base_peak_intensity",
            "retention_time_sec",
            "ms_level",
        ]
        assert msn.metadata["row_granularity"] == "frame-aggregate"
        assert ms1.metadata["source_filename"] == "sample.d"
        assert msn.metadata["source_filename"] == "sample.d"
        assert ms1.metadata["source_id"] == "78d629b2-0edc-4f60-b942-979a46b94ac8"
        assert msn.metadata["source_id"] == "78d629b2-0edc-4f60-b942-979a46b94ac8"
        assert ms1.metadata["acquisition_start_time"] == "2026-08-01T12:30:15Z"
        assert msn.metadata["acquisition_start_time"] == "2026-08-01T12:30:15Z"
        assert msn.table["scan_id"].to_pylist() == [2, 3]
        assert ms1.table["base_peak_intensity"].to_pylist() == [100.0]
        assert msn.table["base_peak_intensity"].to_pylist() == [200.0, 300.0]

    def test_zero_ms1_rows_write_empty_artifact(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.execute("UPDATE Frames SET MsMsType = 8")
            connection.execute("DELETE FROM DiaFrameMsMsInfo")
            connection.commit()

        result = BrukerExtractor().extract(bruker_fixture, output_directory=tmp_path / "empty-ms1")

        assert result.ms1_path is not None
        assert result.msn_path is not None
        ms1 = load_trace(result.ms1_path)
        assert ms1.table.num_rows == 0
        assert ms1.metadata["ms_level_file"] == "ms1"

    def test_rows_are_ordered_by_retention_time_then_scan_id(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.executemany("UPDATE Frames SET Time = ? WHERE Id = ?", [(2.0, 1), (1.0, 2), (1.0, 3)])
            connection.execute("UPDATE Frames SET MsMsType = 0")
            connection.execute("DELETE FROM DiaFrameMsMsInfo")
            connection.commit()

        result = BrukerExtractor().extract(
            bruker_fixture,
            output_directory=tmp_path / "ordered",
            select_msn=False,
        )

        assert result.ms1_path is not None
        artifact = load_trace(result.ms1_path)
        assert artifact.table["scan_id"].to_pylist() == [2, 3, 1]
        assert artifact.table["retention_time_sec"].to_pylist() == [1.0, 1.0, 2.0]

    def test_duplicate_frame_ids_are_rejected(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.execute("ALTER TABLE Frames RENAME TO OriginalFrames")
            connection.execute("CREATE TABLE Frames (Id INTEGER, Time REAL, MsMsType INTEGER)")
            connection.executemany("INSERT INTO Frames VALUES (?, ?, ?)", [(1, 1.0, 0), (1, 2.0, 0)])
            connection.commit()

        with pytest.raises(RuntimeError, match="duplicate scan_id"):
            BrukerExtractor().extract(bruker_fixture, output_directory=tmp_path / "duplicate", select_msn=False)

    @pytest.mark.parametrize(
        ("select_ms1", "select_msn", "ms1_expected", "msn_expected"),
        [(True, False, True, False), (False, True, False, True)],
    )
    def test_selection_flags_control_created_artifacts(
        self,
        bruker_fixture: Path,
        tmp_path: Path,
        select_ms1: bool,
        select_msn: bool,
        ms1_expected: bool,
        msn_expected: bool,
    ) -> None:
        result = BrukerExtractor().extract(
            bruker_fixture, output_directory=tmp_path / "selected", select_ms1=select_ms1, select_msn=select_msn
        )

        assert (result.ms1_path is not None) is ms1_expected
        assert (result.msn_path is not None) is msn_expected

    def test_both_false_validates_input_but_creates_nothing(self, bruker_fixture: Path, tmp_path: Path) -> None:
        output_directory = tmp_path / "no-output"

        result = BrukerExtractor().extract(
            bruker_fixture, output_directory=output_directory, select_ms1=False, select_msn=False
        )

        assert result.ms1_path is None
        assert result.msn_path is None
        assert not output_directory.exists()

    def test_ms1_only_acquisition_omits_msn_artifact(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.execute("DELETE FROM Frames WHERE Id > 1")
            connection.execute("DELETE FROM DiaFrameMsMsInfo")
            connection.commit()

        result = BrukerExtractor().extract(bruker_fixture, output_directory=tmp_path / "ms1-only")

        assert result.ms1_path is not None
        assert result.msn_path is None
        assert not (tmp_path / "ms1-only" / "sample.d.msn-trace.parquet").exists()

    def test_explicit_msn_selection_rejects_ms1_only_acquisition(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.execute("DELETE FROM Frames WHERE Id > 1")
            connection.execute("DELETE FROM DiaFrameMsMsInfo")
            connection.commit()

        with pytest.raises(RuntimeError, match="no MSn frames"):
            BrukerExtractor().extract(
                bruker_fixture, output_directory=tmp_path / "msn-only", select_ms1=False, select_msn=True
            )

    def test_high_precision_writes_float64_trace_columns(self, bruker_fixture: Path, tmp_path: Path) -> None:
        result = BrukerExtractor().extract(
            bruker_fixture, output_directory=tmp_path / "high", precision_mode="high", select_msn=False
        )

        assert result.ms1_path is not None
        artifact = load_trace(result.ms1_path)
        assert artifact.table.schema.field("retention_time_sec").type == pa.float64()
        assert artifact.metadata["precision_mode"] == "high"

    def test_existing_output_is_overwritten(self, bruker_fixture: Path, tmp_path: Path) -> None:
        output_directory = tmp_path / "overwrite"
        first = BrukerExtractor().extract(
            bruker_fixture, output_directory=output_directory, precision_mode="low", select_msn=False
        )
        second = BrukerExtractor().extract(
            bruker_fixture, output_directory=output_directory, precision_mode="high", select_msn=False
        )

        assert first.ms1_path == second.ms1_path
        assert second.ms1_path is not None
        assert load_trace(second.ms1_path).metadata["precision_mode"] == "high"

    def test_invalid_input_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Expected a Bruker"):
            BrukerExtractor().extract(tmp_path / "missing.d")

    def test_missing_required_frames_column_is_rejected(self, bruker_fixture: Path, tmp_path: Path) -> None:
        with closing(sqlite3.connect(bruker_fixture / "analysis.tdf")) as connection, connection:
            connection.execute("ALTER TABLE Frames RENAME TO IncompleteFrames")
            connection.execute("CREATE TABLE Frames (Id INTEGER, Time REAL)")
            connection.commit()

        with pytest.raises(RuntimeError, match="Frames is missing"):
            BrukerExtractor().extract(bruker_fixture, output_directory=tmp_path / "invalid", select_msn=False)

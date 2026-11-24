from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from rawtrace_qc.errors import ConfigurationError, ProcessingError
from rawtrace_qc.processing import (
    FaimsProcessingMode,
    ProcessedTable,
    ProcessingOptions,
    process_traces,
    relabel_tables,
)
from rawtrace_qc.traces import TraceArtifact


def _metadata(*, row_granularity: str = "spectrum", ms_level_file: str = "msn") -> dict[str, str]:
    return {
        "schema_version": "1",
        "generator": "test/1.0",
        "vendor": "bruker",
        "source_filename": "sample.d",
        "source_id": "78d629b2-0edc-4f60-b942-979a46b94ac8",
        "ms_level_file": ms_level_file,
        "precision_mode": "high",
        "row_granularity": row_granularity,
        "extracted_at": "2026-08-05T12:00:00Z",
        "acquisition_start_time": "2026-08-05T10:00:00Z",
    }


def _artifact(*, table: pa.Table | None = None, metadata: dict[str, str] | None = None) -> TraceArtifact:
    if table is None:
        table = pa.table(
            {
                "scan_id": pa.array([1, 2, 3, 4], type=pa.int32()),
                "retention_time_sec": pa.array([30.0, 60.0, 90.0, 120.0]),
                "ms_level": pa.array([2, 3, 2, 3], type=pa.int8()),
                "total_ion_current": pa.array([10.0, 20.0, 30.0, 40.0]),
                "base_peak_intensity": pa.array([1.0, 2.0, 3.0, 4.0]),
            }
        )
    return TraceArtifact(path=Path("generated-name.ms1-trace.parquet"), table=table, metadata=metadata or _metadata())


class TestProcessingOptions:
    def test_defaults_select_ms1_and_ms2_and_split_faims(self) -> None:
        options = ProcessingOptions()

        assert options.ms_levels == (1, 2)
        assert options.faims_mode is FaimsProcessingMode.SPLIT
        assert options.minimum_faims_percentage is None

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"ms_levels": ()},
            {"ms_levels": (1, 1)},
            {"ms_levels": (0,)},
            {"faims_mode": "invalid"},
            {"minimum_faims_percentage": 101},
        ],
    )
    def test_invalid_options_raise_configuration_error(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ConfigurationError):
            ProcessingOptions(**kwargs)  # type: ignore[arg-type]


class TestProcessTraces:
    def test_empty_input_returns_empty_tuple(self) -> None:
        assert process_traces([]) == ()

    def test_default_processing_splits_selected_levels_and_prepares_columns(self) -> None:
        processed = process_traces([_artifact()])

        assert len(processed) == 1
        assert [item.metadata.ms_level for item in processed] == [2]
        assert processed[0].metadata.rawfile_name == "sample.d"
        assert processed[0].metadata.label == "sample.d"
        assert processed[0].metadata.source_id == "78d629b2-0edc-4f60-b942-979a46b94ac8"
        assert processed[0].metadata.vendor == "bruker"
        assert processed[0].metadata.row_granularity == "spectrum"
        assert processed[0].metadata.time_unit == "min"
        assert processed[0].metadata.precision == "high"
        assert processed[0].metadata.channels == ("total_ion_current", "base_peak_intensity")
        assert processed[0].table.column_names == ["retention_time_min", "total_ion_current", "base_peak_intensity"]
        assert processed[0].table["retention_time_min"].to_pylist() == [0.5, 1.5]
        assert "scan_id" not in processed[0].table.column_names
        assert "ms_level" not in processed[0].table.column_names

    def test_processing_can_select_ms3_and_copies_trace_metadata(self) -> None:
        artifact = _artifact(metadata=_metadata(row_granularity="frame-aggregate"))

        processed = process_traces([artifact], options=ProcessingOptions(ms_levels=(3,)))

        assert len(processed) == 1
        assert processed[0].metadata.ms_level == 3
        assert processed[0].metadata.schema_version == "1"
        assert processed[0].metadata.ms_level_file == "msn"
        assert processed[0].metadata.generator == "test/1.0"
        assert processed[0].metadata.source_id == "78d629b2-0edc-4f60-b942-979a46b94ac8"
        assert processed[0].metadata.extracted_at == "2026-08-05T12:00:00Z"
        assert processed[0].metadata.acquisition_start_time == "2026-08-05T10:00:00Z"
        assert processed[0].metadata.row_granularity == "frame-aggregate"

    def test_processing_preserves_missing_recommended_metadata_as_none(self) -> None:
        metadata = _metadata()
        metadata.pop("generator")
        metadata.pop("extracted_at")
        metadata.pop("acquisition_start_time")

        processed = process_traces([_artifact(metadata=metadata)])

        assert processed[0].metadata.generator is None
        assert processed[0].metadata.extracted_at is None
        assert processed[0].metadata.acquisition_start_time is None
        assert processed[0].metadata.acquisition_path is None
        assert processed[0].metadata.source_id == "78d629b2-0edc-4f60-b942-979a46b94ac8"

    def test_split_faims_creates_one_table_per_cv(self) -> None:
        table = _artifact().table.append_column("faims_cv", pa.array([-50.0, -50.0, -60.0, -60.0], type=pa.float32()))

        processed = process_traces([_artifact(table=table)])

        assert [(item.metadata.ms_level, item.metadata.faims_cv) for item in processed] == [(2, -60.0), (2, -50.0)]
        assert all("faims_cv" not in item.table.column_names for item in processed)

    def test_combined_faims_is_not_implemented(self) -> None:
        table = _artifact().table.append_column("faims_cv", pa.array([-50.0, -50.0, -60.0, -60.0], type=pa.float32()))

        with pytest.raises(NotImplementedError, match="combined processing"):
            process_traces([_artifact(table=table)], options=ProcessingOptions(faims_mode=FaimsProcessingMode.COMBINED))

    def test_combined_mode_is_ignored_for_non_faims_tables(self) -> None:
        processed = process_traces([_artifact()], options=ProcessingOptions(faims_mode=FaimsProcessingMode.COMBINED))

        assert len(processed) == 1
        assert processed[0].metadata.faims_cv is None

    def test_sparse_faims_partitions_can_be_removed(self) -> None:
        table = pa.table(
            {
                "scan_id": pa.array([1, 2, 3, 4, 5], type=pa.int32()),
                "retention_time_sec": pa.array([30.0, 60.0, 90.0, 120.0, 150.0]),
                "ms_level": pa.array([2, 2, 2, 2, 2], type=pa.int8()),
                "faims_cv": pa.array([-50.0, -50.0, -50.0, -50.0, -60.0], type=pa.float32()),
            }
        )

        processed = process_traces([_artifact(table=table)], options=ProcessingOptions(minimum_faims_percentage=40))

        assert [(item.metadata.ms_level, item.metadata.faims_cv) for item in processed] == [(2, -50.0)]

    def test_mixed_null_and_numeric_faims_values_are_rejected(self) -> None:
        table = _artifact().table.append_column("faims_cv", pa.array([None, -50.0, -60.0, -60.0], type=pa.float32()))

        with pytest.raises(ProcessingError, match="FAIMS CV is missing"):
            process_traces([_artifact(table=table)])

    def test_missing_channels_are_not_filled_with_sentinel_values(self) -> None:
        table = _artifact().table.drop(["base_peak_intensity"])

        processed = process_traces([_artifact(table=table)])

        assert processed[0].metadata.channels == ("total_ion_current",)
        assert processed[0].table.column_names == ["retention_time_min", "total_ion_current"]

    def test_invalid_artifact_input_raises_processing_error(self) -> None:
        with pytest.raises(ProcessingError, match="expects TraceArtifact"):
            process_traces([object()])  # type: ignore[list-item]


class TestRelabelTables:
    def test_relabel_tables_returns_new_tables_without_mutating_input(self) -> None:
        original = process_traces([_artifact()])

        relabeled = relabel_tables(original, ["Short"])

        assert [item.metadata.label for item in original] == ["sample.d"]
        assert [item.metadata.label for item in relabeled] == ["Short"]
        assert all(isinstance(item, ProcessedTable) for item in relabeled)

    @pytest.mark.parametrize("labels", [[], ["one", "two"], [""]])
    def test_invalid_labels_raise_processing_error(self, labels: list[str]) -> None:
        with pytest.raises(ProcessingError):
            relabel_tables(process_traces([_artifact()]), labels)

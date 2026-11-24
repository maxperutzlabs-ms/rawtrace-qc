"""Transform validated trace artifacts into report-ready Arrow tables."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc

from rawtrace_qc.errors import ProcessingError
from rawtrace_qc.processing.models import (
    FaimsProcessingMode,
    ProcessedTable,
    ProcessedTableMetadata,
    ProcessingOptions,
)
from rawtrace_qc.traces import TraceArtifact, validate_trace

_REPORT_CHANNELS = ("total_ion_current", "base_peak_intensity")
_ARROW_EQUAL = pc.__dict__["equal"]
_ARROW_DIVIDE = pc.__dict__["divide"]


def process_traces(
    artifacts: Sequence[TraceArtifact],
    *,
    options: ProcessingOptions | None = None,
) -> tuple[ProcessedTable, ...]:
    """Prepare validated trace artifacts for report generation.

    Each selected MS level and FAIMS partition becomes a separate processed
    table. The returned tables contain retention time in minutes and the
    available report channels, but omit source-only columns such as `scan_id`,
    `ms_level`, and `faims_cv`. Plotting and HTML serialization are deliberately
    outside this module.

    Args:
        artifacts: Trace artifacts to process in the order used for output.
        options: Partitioning options. Defaults to MS levels `(1, 2)`, separate
            FAIMS tables, and no sparse-FAIMS filtering.

    Returns:
        A tuple containing processed tables in deterministic input, MS level,
        and FAIMS value order. Empty input returns an empty tuple.

    Raises:
        NotImplementedError: If combined FAIMS processing is selected for a
            FAIMS-bearing table.
        ArtifactValidationError: If an artifact violates the schema-v1 trace
            contract.
        ProcessingError: If an input is not a `TraceArtifact`, or a selected
            MS level has FAIMS CVs missing for some scans.
    """
    selected_options = options or ProcessingOptions()
    processed: list[ProcessedTable] = []
    for artifact in artifacts:
        if not isinstance(artifact, TraceArtifact):
            raise ProcessingError(
                "process_traces() expects TraceArtifact instances. "
                "Load artifacts with load_trace()."
            )
        validate_trace(artifact.table, artifact.metadata, strict=True)
        for ms_level in selected_options.ms_levels:
            level_table = _filter_ms_level(artifact.table, ms_level)
            if level_table.num_rows == 0:
                continue
            processing_queue: list[tuple[float | str | None, pa.Table]]
            if _contains_faims(level_table):
                processing_queue = list(
                    _partition_faims(
                        level_table,
                        mode=selected_options.faims_mode,
                        minimum_percentage=selected_options.minimum_faims_percentage,
                    )
                )
            else:
                processing_queue = [(None, level_table)]
            for faims_cv, partition in processing_queue:
                if partition.num_rows == 0:
                    continue
                processed.append(
                    _create_processed_table(
                        artifact,
                        partition,
                        ms_level=ms_level,
                        faims_cv=faims_cv,
                    )
                )
    return tuple(processed)


def relabel_tables(
    processed_tables: Sequence[ProcessedTable],
    labels: Sequence[str],
) -> tuple[ProcessedTable, ...]:
    """Return processed tables with replacement display labels.

    Args:
        processed_tables: Processed tables whose labels should be replaced.
        labels: One non-empty display label for each processed table, in the
            same order.

    Returns:
        New ProcessedTable instances containing references to the original
        PyArrow tables (zero-copy) with updated label metadata.

    Raises:
        ProcessingError: If the label count differs from the table count or a
            label is not a non-empty string.
    """
    if len(processed_tables) != len(labels):
        raise ProcessingError(
            f"Received {len(labels)} labels for "
            f"{len(processed_tables)} processed tables."
        )
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ProcessingError("Processed table labels must be non-empty strings.")
    return tuple(
        ProcessedTable(item.table, replace(item.metadata, label=label))
        for item, label in zip(processed_tables, labels, strict=True)
    )


def _filter_ms_level(table: pa.Table, ms_level: int) -> pa.Table:
    field_type = table.schema.field("ms_level").type
    return table.filter(
        _ARROW_EQUAL(table["ms_level"], pa.scalar(ms_level, type=field_type))
    )


def _partition_faims(
    table: pa.Table,
    *,
    mode: FaimsProcessingMode,
    minimum_percentage: float | None,
) -> tuple[tuple[float | str | None, pa.Table], ...]:
    if mode is FaimsProcessingMode.COMBINED:
        raise NotImplementedError(
            "FAIMS combined processing is not implemented yet. Use split mode."
        )

    values = table["faims_cv"].combine_chunks().to_pylist()
    non_null_values = [value for value in values if value is not None]
    if not non_null_values:
        return ((None, table),)
    if len(non_null_values) != len(values):
        raise ProcessingError(
            "FAIMS CV is missing for some scans, so they cannot be assigned to a CV."
        )
    if any(not isinstance(value, (int, float)) for value in non_null_values):
        raise ProcessingError(
            "Trace artifact faims_cv values must be numeric or null; mixed "
            "FAIMS value types are not supported."
        )
    if any(not math.isfinite(float(value)) for value in non_null_values):
        raise ProcessingError("Trace artifact faims_cv values must be finite numbers.")
    field_type = table.schema.field("faims_cv").type
    unique_values = sorted({float(value) for value in non_null_values})
    partitions = []
    for faims_cv in unique_values:
        partition = table.filter(
            _ARROW_EQUAL(table["faims_cv"], pa.scalar(faims_cv, type=field_type))
        )
        percentage = partition.num_rows / table.num_rows * 100
        if minimum_percentage is None or percentage >= minimum_percentage:
            partitions.append((faims_cv, partition))
    return tuple(partitions)


def _contains_faims(table: pa.Table) -> bool:
    if "faims_cv" not in table.column_names:
        return False
    return table["faims_cv"].null_count < table.num_rows


def _create_processed_table(
    artifact: TraceArtifact,
    table: pa.Table,
    *,
    ms_level: int,
    faims_cv: float | str | None,
) -> ProcessedTable:
    sorted_table = table.sort_by([("retention_time_sec", "ascending")])
    processed_columns: list[pa.Array | pa.ChunkedArray] = [
        _ARROW_DIVIDE(sorted_table["retention_time_sec"], pa.scalar(60.0))
    ]
    processed_names = ["retention_time_min"]
    channels: list[str] = []
    for channel in _REPORT_CHANNELS:
        if channel in sorted_table.column_names:
            processed_columns.append(sorted_table[channel])
            processed_names.append(channel)
            channels.append(channel)
    processed_table = pa.Table.from_arrays(processed_columns, names=processed_names)

    source_metadata = artifact.metadata
    rawfile_name = cast(str, source_metadata["source_filename"])
    metadata = ProcessedTableMetadata(
        rawfile_name=rawfile_name,
        label=rawfile_name,
        source_id=source_metadata.get("source_id"),
        schema_version=cast(str, source_metadata["schema_version"]),
        generator=source_metadata.get("generator"),
        vendor=cast(str, source_metadata["vendor"]),
        ms_level_file=cast(str, source_metadata["ms_level_file"]),
        extracted_at=source_metadata.get("extracted_at"),
        acquisition_start_time=source_metadata.get("acquisition_start_time"),
        acquisition_path=source_metadata.get("acquisition_path"),
        ms_level=ms_level,
        faims_cv=faims_cv,
        row_granularity=cast(str, source_metadata["row_granularity"]),
        time_unit="min",
        precision=cast(str, source_metadata["precision_mode"]),
        channels=tuple(channels),
    )
    return ProcessedTable(processed_table, metadata)

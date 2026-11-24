"""Load, write, and validate schema-v1 trace artifacts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from rawtrace_qc.errors import ArtifactValidationError
from rawtrace_qc.traces.schema import (
    OPTIONAL_METADATA,
    REQUIRED_COLUMNS,
    REQUIRED_METADATA,
    SCHEMA_VERSION,
    TRACE_COLUMN_BY_NAME,
    ColumnDefinition,
    ColumnLogicalType,
    ColumnSupport,
)


@dataclass(frozen=True, slots=True)
class TraceArtifact:
    """Store a validated scan-trace table and its provenance metadata."""

    path: Path
    table: pa.Table
    metadata: Mapping[str, str | None]


def load_trace(path: Path, *, strict: bool = True) -> TraceArtifact:
    """Load and validate a scan-trace Parquet artifact.

    Args:
        path: Parquet file to load.
        strict: If True (default), reject columns that are not implemented by
            this package. If False, validate known future columns and ignore
            columns that are not part of the v1 contract.

    Returns:
        The validated Arrow table and decoded file metadata.

    Raises:
        ArtifactValidationError: If the file cannot be read or violates the
            scan-trace contract.
    """
    resolved_path = path.expanduser().resolve()
    if not resolved_path.is_file():
        raise ArtifactValidationError(f"Scan-trace file not found: {resolved_path}")

    try:
        with pa.OSFile(str(resolved_path), "rb") as source:
            parquet_file = pq.ParquetFile(source)
            try:
                table = parquet_file.read()
                metadata = _decode_metadata(table.schema.metadata)
                validate_trace(table, metadata, strict=strict)
                _validate_compression(parquet_file)
            finally:
                parquet_file.close()
    except (OSError, pa.ArrowException) as error:
        raise ArtifactValidationError(
            f"Could not read scan-trace Parquet file {resolved_path}: {error}"
        ) from error

    return TraceArtifact(resolved_path, table, metadata)


def write_trace(
    table: pa.Table,
    output_path: Path,
    *,
    vendor: str,
    source_filename: str,
    ms_level_file: str,
    precision_mode: str,
    row_granularity: str,
    extracted_at: str | None = None,
    acquisition_start_time: str | None = None,
    generator: str | None = None,
    source_id: str | None = None,
    acquisition_path: str | None = None,
) -> Path:
    """Write a validated table as a schema-v1 Snappy Parquet artifact.

    Args:
        table: Arrow table containing scan-trace rows.
        output_path: Destination path. Existing files are overwritten.
        vendor: Source vendor identifier such as `bruker` or `thermo`.
        source_filename: Original source filename, including its extension.
        ms_level_file: File level identifier, either `ms1` or `msn`.
        precision_mode: Trace precision identifier, either `low` or `high`.
        row_granularity: Row meaning, either `spectrum` or `frame-aggregate`.
        extracted_at: Optional ISO-8601 UTC extraction timestamp.
        acquisition_start_time: Optional ISO-8601 UTC source acquisition start
            timestamp.
        generator: Optional name and version of the producing extractor.
        source_id: Optional unique source-run identifier.
        acquisition_path: Optional vendor-recorded source acquisition path.

    Returns:
        The resolved destination path.

    Raises:
        ArtifactValidationError: If the table or metadata violates the
            scan-trace contract.
    """
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "vendor": vendor,
        "source_filename": source_filename,
        "ms_level_file": ms_level_file,
        "precision_mode": precision_mode,
        "row_granularity": row_granularity,
        "extracted_at": extracted_at,
        "acquisition_start_time": acquisition_start_time,
    }
    metadata.update(
        {
            "generator": generator,
            "source_id": source_id,
            "acquisition_path": acquisition_path,
        }
    )
    validate_trace(table, metadata, strict=True)

    resolved_path = output_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    encoded_metadata = {
        key.encode(): value.encode()
        for key, value in metadata.items()
        if value is not None
    }
    pq.write_table(
        table.replace_schema_metadata(encoded_metadata),
        resolved_path,
        compression="snappy",
    )
    return resolved_path


def _decode_metadata(
    raw_metadata: Mapping[bytes, bytes] | None,
) -> dict[str, str | None]:
    if raw_metadata is None:
        return {field: None for field in OPTIONAL_METADATA}
    try:
        metadata: dict[str, str | None] = {
            key.decode("utf-8"): value.decode("utf-8")
            for key, value in raw_metadata.items()
        }
    except UnicodeDecodeError as error:
        raise ArtifactValidationError(
            "Parquet metadata must contain UTF-8 text."
        ) from error
    for field in OPTIONAL_METADATA:
        metadata.setdefault(field, None)
    return metadata


def validate_trace(
    table: pa.Table,
    metadata: Mapping[str, str | None],
    *,
    strict: bool = True,
) -> None:
    """Validate a trace table and its schema metadata.

    Args:
        table: Arrow table containing scan-trace rows.
        metadata: Decoded Parquet metadata associated with the table.
        strict: If True, reject unknown and reserved columns. If False, allow
            columns that are not implemented by this package while still
            validating known column types.

    Raises:
        ArtifactValidationError: If the table or metadata violates the
            schema-v1 trace contract.
    """
    missing_columns = REQUIRED_COLUMNS - set(table.column_names)
    if missing_columns:
        raise ArtifactValidationError(
            "Scan-trace is missing required columns: "
            f"{', '.join(sorted(missing_columns))}"
        )

    unknown_columns = set(table.column_names) - set(TRACE_COLUMN_BY_NAME)
    reserved_columns = {
        column
        for column in table.column_names
        if column in TRACE_COLUMN_BY_NAME
        and TRACE_COLUMN_BY_NAME[column].support is ColumnSupport.RESERVED
    }
    unsupported_columns = unknown_columns | reserved_columns
    if strict and unsupported_columns:
        raise ArtifactValidationError(
            "Scan-trace contains columns not implemented by rawtrace-qc: "
            f"{', '.join(sorted(unsupported_columns))}"
        )

    for column in table.column_names:
        definition = TRACE_COLUMN_BY_NAME.get(column)
        if definition is not None:
            _validate_column_type(table, definition)

    for column in REQUIRED_COLUMNS:
        if table.column(column).null_count:
            raise ArtifactValidationError(
                f"Required column {column!r} contains null values."
            )

    _validate_metadata(metadata)
    _validate_levels(table, metadata)
    _validate_faims(table)


def _validate_column_type(table: pa.Table, definition: ColumnDefinition) -> None:
    data_type = table.schema.field(definition.name).type
    if definition.logical_type is ColumnLogicalType.INTEGER:
        valid = pa.types.is_integer(data_type)
    else:
        valid = pa.types.is_floating(data_type)
    if not valid:
        raise ArtifactValidationError(
            f"Column {definition.name!r} has an invalid Arrow type: {data_type}."
        )


def _validate_levels(table: pa.Table, metadata: Mapping[str, str | None]) -> None:
    ms_level_file = metadata.get("ms_level_file")
    levels = table.column("ms_level").combine_chunks().to_pylist()
    if ms_level_file == "ms1" and any(level != 1 for level in levels):
        raise ArtifactValidationError("An MS1 trace must contain only ms_level=1 rows.")
    if ms_level_file == "msn" and any(level is None or level < 2 for level in levels):
        raise ArtifactValidationError(
            "An MSn trace must contain only ms_level values >= 2."
        )


def _validate_faims(table: pa.Table) -> None:
    if "faims_cv" not in table.column_names:
        return

    values = table["faims_cv"].combine_chunks().to_pylist()
    non_null_values = [value for value in values if value is not None]
    if any(not math.isfinite(float(value)) for value in non_null_values):
        raise ArtifactValidationError(
            "A trace faims_cv column must contain finite values."
        )


def _validate_metadata(metadata: Mapping[str, str | None]) -> None:
    missing_metadata = {
        field for field in REQUIRED_METADATA if metadata.get(field) is None
    }
    if missing_metadata:
        raise ArtifactValidationError(
            "Scan-trace is missing required metadata: "
            f"{', '.join(sorted(missing_metadata))}"
        )
    schema_version = metadata["schema_version"]
    if schema_version != SCHEMA_VERSION:
        raise ArtifactValidationError(
            f"Unsupported scan-trace schema version {schema_version!r}; "
            f"expected {SCHEMA_VERSION!r}."
        )
    ms_level_file = metadata["ms_level_file"]
    if ms_level_file not in {"ms1", "msn"}:
        raise ArtifactValidationError("Metadata ms_level_file must be 'ms1' or 'msn'.")
    precision_mode = metadata["precision_mode"]
    if precision_mode not in {"low", "high"}:
        raise ArtifactValidationError(
            "Metadata precision_mode must be 'low' or 'high'."
        )
    row_granularity = metadata["row_granularity"]
    if row_granularity not in {"spectrum", "frame-aggregate"}:
        raise ArtifactValidationError(
            "Metadata row_granularity must be 'spectrum' or 'frame-aggregate'."
        )
    vendor = metadata["vendor"]
    source_filename = metadata["source_filename"]
    if (
        not isinstance(vendor, str)
        or not vendor.strip()
        or not isinstance(source_filename, str)
        or not source_filename.strip()
    ):
        raise ArtifactValidationError(
            "Metadata vendor and source_filename must not be empty."
        )
    for field_name in ("extracted_at", "acquisition_start_time"):
        value = metadata.get(field_name)
        if value is not None:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ArtifactValidationError(
                    f"Metadata {field_name} must be an ISO-8601 timestamp."
                ) from error


def _validate_compression(parquet_file: pq.ParquetFile) -> None:
    metadata = parquet_file.metadata
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index in range(row_group.num_columns):
            compression = row_group.column(column_index).compression
            if compression != "SNAPPY":
                raise ArtifactValidationError(
                    f"Scan-trace must use Snappy compression, got {compression!r}."
                )

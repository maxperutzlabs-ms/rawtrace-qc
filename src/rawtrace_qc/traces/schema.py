"""Define the declarative schema-v1 trace contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SCHEMA_VERSION = "1"


class ColumnLogicalType(StrEnum):
    """Describe the logical type of a trace column."""

    INTEGER = "integer"
    FLOAT = "float"


class ColumnSupport(StrEnum):
    """Describe whether a contract column is currently implemented."""

    IMPLEMENTED = "implemented"
    RESERVED = "reserved"


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    """Describe one schema-v1 trace column."""

    name: str
    logical_type: ColumnLogicalType
    required: bool
    support: ColumnSupport = ColumnSupport.IMPLEMENTED


TRACE_COLUMNS = (
    ColumnDefinition("scan_id", ColumnLogicalType.INTEGER, required=True),
    ColumnDefinition("retention_time_sec", ColumnLogicalType.FLOAT, required=True),
    ColumnDefinition("ms_level", ColumnLogicalType.INTEGER, required=True),
    ColumnDefinition("total_ion_current", ColumnLogicalType.FLOAT, required=False),
    ColumnDefinition("base_peak_intensity", ColumnLogicalType.FLOAT, required=False),
    ColumnDefinition("faims_cv", ColumnLogicalType.FLOAT, required=False),
    ColumnDefinition(
        "injection_time_ms",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
    ColumnDefinition(
        "base_peak_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
    ColumnDefinition(
        "polarity",
        ColumnLogicalType.INTEGER,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
    ColumnDefinition(
        "precursor_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
    ColumnDefinition(
        "isolation_window_lower_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
    ColumnDefinition(
        "isolation_window_upper_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
    ),
)

TRACE_COLUMN_BY_NAME = {column.name: column for column in TRACE_COLUMNS}
REQUIRED_COLUMNS = frozenset(column.name for column in TRACE_COLUMNS if column.required)
IMPLEMENTED_COLUMNS = frozenset(
    column.name
    for column in TRACE_COLUMNS
    if column.support is ColumnSupport.IMPLEMENTED
)
IMPLEMENTED_OPTIONAL_COLUMNS = IMPLEMENTED_COLUMNS - REQUIRED_COLUMNS
KNOWN_COLUMNS = frozenset(TRACE_COLUMN_BY_NAME)


class MetadataField(StrEnum):
    """Name a schema-v1 Parquet metadata field."""

    SCHEMA_VERSION = "schema_version"
    GENERATOR = "generator"
    VENDOR = "vendor"
    SOURCE_FILENAME = "source_filename"
    MS_LEVEL_FILE = "ms_level_file"
    PRECISION_MODE = "precision_mode"
    ROW_GRANULARITY = "row_granularity"
    EXTRACTED_AT = "extracted_at"
    ACQUISITION_START_TIME = "acquisition_start_time"
    SOURCE_ID = "source_id"
    ACQUISITION_PATH = "acquisition_path"


REQUIRED_METADATA = frozenset(
    field.value
    for field in (
        MetadataField.SCHEMA_VERSION,
        MetadataField.VENDOR,
        MetadataField.MS_LEVEL_FILE,
        MetadataField.PRECISION_MODE,
        MetadataField.ROW_GRANULARITY,
        MetadataField.SOURCE_FILENAME,
    )
)
OPTIONAL_METADATA = (
    frozenset(field.value for field in MetadataField) - REQUIRED_METADATA
)

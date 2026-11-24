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


class ColumnBitWidth(StrEnum):
    """Describe the bit width that the contract fixes for a float column."""

    PRECISION_MODE = "precision_mode"
    FLOAT32 = "float32"
    FLOAT64 = "float64"


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    """Describe one schema-v1 trace column.

    Attributes:
        name: Column name.
        logical_type: Logical type of the values.
        required: Whether every file contains the column. Required columns
            contain no nulls; in optional columns, a null marks a row for
            which the value could not be read.
        support: Whether the column is implemented or only reserved.
        unit: Unit of the values, or None if the column has no unit.
        files: The `ms_level_file` values of the files that may contain the
            column.
        width: Bit width that the contract fixes, or None if it fixes none.
            `PRECISION_MODE` means 32-bit in `low` and 64-bit in `high`
            precision mode.
    """

    name: str
    logical_type: ColumnLogicalType
    required: bool
    support: ColumnSupport = ColumnSupport.IMPLEMENTED
    unit: str | None = None
    files: tuple[str, ...] = ("ms1", "msn")
    width: ColumnBitWidth | None = None


TRACE_COLUMNS = (
    ColumnDefinition("scan_id", ColumnLogicalType.INTEGER, required=True),
    ColumnDefinition(
        "retention_time_sec",
        ColumnLogicalType.FLOAT,
        required=True,
        unit="seconds",
        width=ColumnBitWidth.PRECISION_MODE,
    ),
    ColumnDefinition("ms_level", ColumnLogicalType.INTEGER, required=True),
    ColumnDefinition(
        "total_ion_current",
        ColumnLogicalType.FLOAT,
        required=False,
        unit="intensity",
        width=ColumnBitWidth.PRECISION_MODE,
    ),
    ColumnDefinition(
        "base_peak_intensity",
        ColumnLogicalType.FLOAT,
        required=False,
        unit="intensity",
        width=ColumnBitWidth.PRECISION_MODE,
    ),
    ColumnDefinition(
        "faims_cv",
        ColumnLogicalType.FLOAT,
        required=False,
        unit="volts",
        width=ColumnBitWidth.FLOAT32,
    ),
    ColumnDefinition(
        "injection_time_ms",
        ColumnLogicalType.FLOAT,
        required=False,
        unit="milliseconds",
        width=ColumnBitWidth.FLOAT32,
    ),
    ColumnDefinition(
        "base_peak_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
        unit="m/z",
        width=ColumnBitWidth.FLOAT64,
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
        unit="m/z",
        files=("msn",),
        width=ColumnBitWidth.FLOAT64,
    ),
    ColumnDefinition(
        "isolation_window_lower_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
        unit="m/z",
        files=("msn",),
        width=ColumnBitWidth.FLOAT64,
    ),
    ColumnDefinition(
        "isolation_window_upper_mz",
        ColumnLogicalType.FLOAT,
        required=False,
        support=ColumnSupport.RESERVED,
        unit="m/z",
        files=("msn",),
        width=ColumnBitWidth.FLOAT64,
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


@dataclass(frozen=True, slots=True)
class MetadataDefinition:
    """Describe one schema-v1 Parquet metadata field.

    Attributes:
        field: Metadata key.
        required: Whether every file contains the field. Optional fields are
            recommended by the contract.
        allowed_values: The only values the field may have, or None if the
            contract does not restrict them.
    """

    field: MetadataField
    required: bool
    allowed_values: tuple[str, ...] | None = None


TRACE_METADATA = (
    MetadataDefinition(MetadataField.SCHEMA_VERSION, required=True),
    MetadataDefinition(MetadataField.VENDOR, required=True),
    MetadataDefinition(
        MetadataField.MS_LEVEL_FILE, required=True, allowed_values=("ms1", "msn")
    ),
    MetadataDefinition(
        MetadataField.PRECISION_MODE, required=True, allowed_values=("low", "high")
    ),
    MetadataDefinition(
        MetadataField.ROW_GRANULARITY,
        required=True,
        allowed_values=("spectrum", "frame-aggregate"),
    ),
    MetadataDefinition(MetadataField.SOURCE_FILENAME, required=True),
    MetadataDefinition(MetadataField.SOURCE_ID, required=False),
    MetadataDefinition(MetadataField.GENERATOR, required=False),
    MetadataDefinition(MetadataField.EXTRACTED_AT, required=False),
    MetadataDefinition(MetadataField.ACQUISITION_START_TIME, required=False),
    MetadataDefinition(MetadataField.ACQUISITION_PATH, required=False),
)

REQUIRED_METADATA = frozenset(
    definition.field.value for definition in TRACE_METADATA if definition.required
)
OPTIONAL_METADATA = frozenset(
    definition.field.value for definition in TRACE_METADATA if not definition.required
)

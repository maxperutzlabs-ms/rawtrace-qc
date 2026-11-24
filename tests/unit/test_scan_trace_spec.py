from __future__ import annotations

import re
from pathlib import Path

from rawtrace_qc.traces import TRACE_COLUMNS, TRACE_METADATA, ColumnBitWidth, ColumnSupport

_SPEC = Path(__file__).parents[2] / "docs" / "scan-trace-spec.md"
_COLUMN_SECTIONS = {
    "5.1": (True, ColumnSupport.IMPLEMENTED),
    "5.2": (False, ColumnSupport.IMPLEMENTED),
    "5.3": (False, ColumnSupport.RESERVED),
}


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^##+ {re.escape(heading)}\s.*?(?=^##)", text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, heading
    return match.group(0)


def _backticked(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def _line_starting_with(section: str, prefix: str) -> str:
    return next(line for line in section.splitlines() if line.startswith(prefix))


def _spec_widths(text: str) -> dict[str, ColumnBitWidth]:
    section = _section(text, "8.")
    precision_line = _line_starting_with(section, "`precision_mode` governs exactly three columns:")
    fixed_line = _line_starting_with(section, "Fixed-width regardless of mode:")
    fixed_32_bit, rest = fixed_line.split("always 32-bit", 1)
    fixed_64_bit = rest.split("always 64-bit", 1)[0]
    widths = dict.fromkeys(_backticked(precision_line.split(":", 1)[1]), ColumnBitWidth.PRECISION_MODE)
    widths |= dict.fromkeys(_backticked(fixed_32_bit), ColumnBitWidth.FLOAT32)
    widths |= dict.fromkeys(_backticked(fixed_64_bit), ColumnBitWidth.FLOAT64)
    return widths


def _spec_columns(text: str) -> dict[str, tuple[str, bool, ColumnSupport, tuple[str, ...], ColumnBitWidth | None]]:
    widths = _spec_widths(text)
    columns = {}
    for heading, (required, support) in _COLUMN_SECTIONS.items():
        for row in _section(text, heading).splitlines():
            if not row.startswith("| `"):
                continue
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            name = _backticked(cells[0])[0]
            files = tuple(file.strip() for file in cells[3].split(","))
            columns[name] = (cells[1].split()[0], required, support, files, widths.get(name))
    return columns


def _spec_metadata(text: str, label: str) -> set[str]:
    return set(_backticked(_line_starting_with(_section(text, "9."), f"**{label}:**")))


class TestScanTraceSpecification:
    def test_schema_columns_match_specification(self) -> None:
        text = _SPEC.read_text(encoding="utf-8")

        schema_columns = {
            column.name: (column.logical_type.value, column.required, column.support, column.files, column.width)
            for column in TRACE_COLUMNS
        }

        assert schema_columns == _spec_columns(text)

    def test_schema_metadata_fields_match_specification(self) -> None:
        text = _SPEC.read_text(encoding="utf-8")

        required = {definition.field.value for definition in TRACE_METADATA if definition.required}
        recommended = {definition.field.value for definition in TRACE_METADATA if not definition.required}

        assert (required, recommended) == (_spec_metadata(text, "Required"), _spec_metadata(text, "Recommended"))

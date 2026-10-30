"""Extract schema-v1 scan traces from Bruker timsTOF acquisitions."""

from __future__ import annotations

import importlib.metadata
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa

from rawtrace_qc.extractors.common import validate_extraction_options
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.traces import write_trace

PrecisionMode = Literal["low", "high"]


@dataclass(frozen=True, slots=True)
class _Frames:
    """Store the frame fields needed by the initial extractor."""

    scan_id: np.ndarray
    retention_time_sec: np.ndarray
    msms_type: np.ndarray
    total_ion_current: np.ndarray | None
    base_peak_intensity: np.ndarray | None


@dataclass(frozen=True, slots=True)
class _Summary:
    """Store normalized frame values before level-specific writing."""

    scan_id: np.ndarray
    retention_time_sec: np.ndarray
    ms_level: np.ndarray
    total_ion_current: np.ndarray | None
    base_peak_intensity: np.ndarray | None


class BrukerExtractor:
    """Create scan-table Parquet files from a Bruker timsTOF `.d` folder.

    The extractor reads native frame metadata from `analysis.tdf`, including
    total ion current and base-peak intensity when those columns are available.
    Bruker MSn rows remain frame aggregates because per-isolation-event data
    requires decoding `analysis.tdf_bin`.
    """

    def extract(
        self,
        input_path: Path,
        output_directory: Path | None = None,
        output_name: str | None = None,
        precision_mode: PrecisionMode = "low",
        *,
        select_ms1: bool = True,
        select_msn: bool = True,
    ) -> ExtractionResult:
        """Extract the selected Bruker scan levels.

        Args:
            input_path: Bruker `.d` acquisition folder.
            output_directory: Directory for output files. Defaults to the
                input folder's parent directory.
            output_name: Optional literal filename stem. Defaults to the input
                folder name, including `.d`.
            precision_mode: `low` for float32 trace fields, or `high` for
                float64 trace fields. Defaults to `low`.
            select_ms1: If True (default), write the MS1 artifact.
            select_msn: If True (default), write the MSn artifact when MSn rows
                are present.

        Returns:
            The paths created for the selected, available MS levels. When both
            selection flags are false, no output is created and both paths are
            None after basic input validation.

        Raises:
            FileNotFoundError: If `analysis.tdf` is missing.
            ValueError: If an argument or input path is invalid.
            RuntimeError: If an explicitly MSn-only selection has no MSn frames,
                or required frame data cannot form a valid table.
        """
        resolved_input = validate_extraction_options(
            input_path,
            output_name,
            precision_mode,
            expected_extension=".d",
            vendor_label="Bruker",
            expect_dir=True,
        )
        tdf_path = resolved_input / "analysis.tdf"
        if not tdf_path.is_file():
            raise FileNotFoundError(f"analysis.tdf not found in {resolved_input}")

        acquisition_start_time = self._read_acquisition_start_time(tdf_path)
        source_id = self._read_analysis_id(tdf_path)
        frames = self._read_frames(tdf_path)
        summary = self._build_summary(
            frames,
            self._read_dia_ms2_ids(tdf_path),
        )
        if not select_ms1 and not select_msn:
            return ExtractionResult()

        select_all_levels = select_ms1 and select_msn
        ms1_indices = np.flatnonzero(summary.ms_level == 1)
        msn_indices = np.flatnonzero(summary.ms_level > 1)
        if select_msn and not select_all_levels and not len(msn_indices):
            raise RuntimeError("The input folder contains no MSn frames.")

        destination_directory = (
            resolved_input.parent
            if output_directory is None
            else output_directory.expanduser().resolve()
        )
        destination_directory.mkdir(parents=True, exist_ok=True)
        file_stem = output_name or resolved_input.name
        extracted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        ms1_path = None
        msn_path = None

        if select_ms1:
            ms1_path = self._write_level(
                summary,
                ms1_indices,
                destination_directory / f"{file_stem}.ms1-trace.parquet",
                "ms1",
                precision_mode,
                "spectrum",
                resolved_input.name,
                extracted_at,
                acquisition_start_time,
                source_id,
            )
        if select_msn and len(msn_indices):
            msn_path = self._write_level(
                summary,
                msn_indices,
                destination_directory / f"{file_stem}.msn-trace.parquet",
                "msn",
                precision_mode,
                "frame-aggregate",
                resolved_input.name,
                extracted_at,
                acquisition_start_time,
                source_id,
            )

        return ExtractionResult(ms1_path=ms1_path, msn_path=msn_path)

    @staticmethod
    def _read_frames(tdf_path: Path) -> _Frames:
        with closing(sqlite3.connect(tdf_path)) as connection:
            available_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(Frames)")
            }
            required_columns = {"Id", "Time", "MsMsType"}
            missing_columns = required_columns - available_columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise RuntimeError(f"Frames is missing required columns: {missing}")
            tic_select = (
                ", SummedIntensities"
                if "SummedIntensities" in available_columns
                else ""
            )
            bpi_select = ", MaxIntensity" if "MaxIntensity" in available_columns else ""
            rows = connection.execute(
                f"SELECT Id, Time, MsMsType{tic_select}{bpi_select} "
                "FROM Frames ORDER BY Time, Id"
            ).fetchall()

        try:
            scan_ids = np.asarray(
                [_integer_value(row[0]) for row in rows], dtype=np.int32
            )
            retention_times = np.asarray(
                [_finite_float(row[1]) for row in rows], dtype=np.float64
            )
            msms_types = np.asarray(
                [_integer_value(row[2]) for row in rows], dtype=np.int64
            )
        except (TypeError, ValueError, OverflowError) as error:
            raise RuntimeError(
                "Frames contains invalid required scan-table values."
            ) from error
        unique_scan_ids, counts = np.unique(scan_ids, return_counts=True)
        duplicate_scan_ids = unique_scan_ids[counts > 1]
        if duplicate_scan_ids.size:
            raise RuntimeError(
                "Frames contains duplicate scan_id values: "
                f"{duplicate_scan_ids.tolist()!r}. Each Frames.Id must be unique."
            )
        total_ion_current = None
        base_peak_intensity = None
        optional_index = 3
        if tic_select:
            total_ion_current = np.asarray(
                [_nullable_float(row[optional_index]) for row in rows], dtype=np.float64
            )
            optional_index += 1
        if bpi_select:
            base_peak_intensity = np.asarray(
                [_nullable_float(row[optional_index]) for row in rows], dtype=np.float64
            )
        return _Frames(
            scan_ids,
            retention_times,
            msms_types,
            total_ion_current,
            base_peak_intensity,
        )

    @staticmethod
    def _read_acquisition_start_time(tdf_path: Path) -> str:
        with closing(sqlite3.connect(tdf_path)) as connection:
            available_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "GlobalMetadata" not in available_tables:
                raise RuntimeError("GlobalMetadata table is missing from analysis.tdf")
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(GlobalMetadata)")
            }
            missing_columns = {"Key", "Value"} - columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise RuntimeError(
                    f"GlobalMetadata is missing required columns: {missing}"
                )
            row = connection.execute(
                "SELECT Value FROM GlobalMetadata WHERE Key = ?",
                ("AcquisitionDateTime",),
            ).fetchone()

        if row is None or not str(row[0]).strip():
            raise RuntimeError("GlobalMetadata does not contain AcquisitionDateTime.")
        value = str(row[0]).strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            acquisition_time = datetime.fromisoformat(value)
        except ValueError as error:
            raise RuntimeError(
                "GlobalMetadata AcquisitionDateTime is not an ISO-8601 timestamp."
            ) from error
        if acquisition_time.tzinfo is None:
            raise RuntimeError(
                "GlobalMetadata AcquisitionDateTime must include a timezone."
            )
        return acquisition_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _read_analysis_id(tdf_path: Path) -> str | None:
        with closing(sqlite3.connect(tdf_path)) as connection:
            row = connection.execute(
                "SELECT Value FROM GlobalMetadata WHERE Key = ?",
                ("AnalysisId",),
            ).fetchone()

        if row is None or not str(row[0]).strip():
            return None
        return str(row[0]).strip()

    @staticmethod
    def _read_dia_ms2_ids(tdf_path: Path) -> set[int]:
        with closing(sqlite3.connect(tdf_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "DiaFrameMsMsInfo" not in tables:
                return set()
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(DiaFrameMsMsInfo)")
            }
            if "Frame" not in columns:
                raise RuntimeError("DiaFrameMsMsInfo is missing required column: Frame")
            return {
                _integer_value(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT Frame FROM DiaFrameMsMsInfo"
                )
            }

    @staticmethod
    def _build_summary(
        frames: _Frames,
        dia_ms2_ids: set[int],
    ) -> _Summary:
        ms_level = np.where(frames.msms_type == 0, 1, 2).astype(np.int8)
        if dia_ms2_ids:
            ms_level[np.isin(frames.scan_id, list(dia_ms2_ids))] = 2
        return _Summary(
            frames.scan_id,
            frames.retention_time_sec,
            ms_level,
            frames.total_ion_current,
            frames.base_peak_intensity,
        )

    @staticmethod
    def _write_level(
        summary: _Summary,
        indices: np.ndarray,
        output_path: Path,
        ms_level_file: Literal["ms1", "msn"],
        precision_mode: PrecisionMode,
        row_granularity: Literal["spectrum", "frame-aggregate"],
        source_filename: str,
        extracted_at: str,
        acquisition_start_time: str,
        source_id: str | None,
    ) -> Path:
        trace_type = pa.float32() if precision_mode == "low" else pa.float64()
        values: dict[str, pa.Array] = {
            "scan_id": pa.array(summary.scan_id[indices], type=pa.int32()),
            "retention_time_sec": pa.array(
                summary.retention_time_sec[indices], type=trace_type
            ),
            "ms_level": pa.array(summary.ms_level[indices], type=pa.int8()),
        }
        if summary.total_ion_current is not None:
            values["total_ion_current"] = _nullable_array(
                summary.total_ion_current[indices], trace_type
            )
        if summary.base_peak_intensity is not None:
            values["base_peak_intensity"] = _nullable_array(
                summary.base_peak_intensity[indices], trace_type
            )
        ordered_names = ["scan_id", "retention_time_sec", "ms_level"]
        ordered_names[1:1] = [
            name
            for name in ("total_ion_current", "base_peak_intensity")
            if name in values
        ]
        table = pa.Table.from_arrays(
            [values[name] for name in ordered_names], names=ordered_names
        )
        return write_trace(
            table,
            output_path,
            vendor="bruker",
            source_filename=source_filename,
            ms_level_file=ms_level_file,
            precision_mode=precision_mode,
            row_granularity=row_granularity,
            extracted_at=extracted_at,
            acquisition_start_time=acquisition_start_time,
            generator=f"rawtrace-qc-bruker/{_package_version()}",
            source_id=source_id,
        )


def _integer_value(value: int | float | str) -> int:
    number = float(value)
    if not np.isfinite(number) or not number.is_integer():
        raise ValueError(value)
    return int(number)


def _finite_float(value: int | float | str) -> float:
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(value)
    return number


def _nullable_float(value: object) -> float:
    if value is None:
        return np.nan
    if not isinstance(value, (int, float, str)):
        raise ValueError(value)
    return _finite_float(value)


def _nullable_array(values: np.ndarray, data_type: pa.DataType) -> pa.Array:
    return pa.array(
        [None if not np.isfinite(value) else float(value) for value in values],
        type=data_type,
    )


def _package_version() -> str:
    try:
        return importlib.metadata.version("rawtrace-qc")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"

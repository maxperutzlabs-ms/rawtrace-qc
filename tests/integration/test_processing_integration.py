from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
from rawtrace_qc.processing import process_traces
from rawtrace_qc.traces import load_trace, write_trace


def test_written_trace_can_be_loaded_and_processed(tmp_path: Path) -> None:
    ms1_path = write_trace(
        pa.table(
            {
                "scan_id": pa.array([1], type=pa.int32()),
                "retention_time_sec": pa.array([60.0]),
                "ms_level": pa.array([1], type=pa.int8()),
                "total_ion_current": pa.array([10.0]),
                "faims_cv": pa.array([-50.0], type=pa.float32()),
            }
        ),
        tmp_path / "integration-sample.d.ms1-trace.parquet",
        vendor="bruker",
        source_filename="integration-sample.d",
        source_id="78d629b2-0edc-4f60-b942-979a46b94ac8",
        ms_level_file="ms1",
        precision_mode="high",
        row_granularity="spectrum",
        extracted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        acquisition_start_time="2026-08-04T10:00:00Z",
        generator="integration-test/1.0",
    )
    msn_path = write_trace(
        pa.table(
            {
                "scan_id": pa.array([2, 3], type=pa.int32()),
                "retention_time_sec": pa.array([120.0, 180.0]),
                "ms_level": pa.array([2, 3], type=pa.int8()),
                "total_ion_current": pa.array([20.0, 30.0]),
                "faims_cv": pa.array([-50.0, -60.0], type=pa.float32()),
            }
        ),
        tmp_path / "integration-sample.d.msn-trace.parquet",
        vendor="bruker",
        source_filename="integration-sample.d",
        source_id="78d629b2-0edc-4f60-b942-979a46b94ac8",
        ms_level_file="msn",
        precision_mode="high",
        row_granularity="frame-aggregate",
        extracted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        acquisition_start_time="2026-08-04T10:00:00Z",
        generator="integration-test/1.0",
    )

    processed = process_traces([load_trace(ms1_path), load_trace(msn_path)])

    assert [(item.metadata.ms_level, item.metadata.faims_cv) for item in processed] == [(1, -50.0), (2, -50.0)]
    assert processed[0].metadata.rawfile_name == "integration-sample.d"
    assert processed[0].metadata.source_id == "78d629b2-0edc-4f60-b942-979a46b94ac8"
    assert processed[0].metadata.precision == "high"
    assert processed[0].table["retention_time_min"].to_pylist() == [1.0]

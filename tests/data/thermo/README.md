# exploris480_ms1_dia_3cycles.raw Test Fixture

This directory contains a small real Thermo Orbitrap Exploris 480 acquisition fixture: `exploris480_ms1_dia_3cycles.raw`.

## Instrument and Acquisition Details

- **Instrument Model:** Thermo Orbitrap Exploris 480
- **Serial Number / Source ID:** `MA10459C_20260930114656`
- **Acquisition Start Time:** `2026-09-30T11:46:56Z` (ISO-8601 UTC)
- **Experiment Type:** Data-Independent Acquisition (DIA), 3 cycles
- **FAIMS:** None (no FAIMS compensation voltage)

## Expected Scan Trace Output

When extracted with `ThermoScanHeaderExtractor` (or `ThermoExtractor`), the extraction yields:

### MS1 Trace (`<stem>.ms1-trace.parquet`)
- **Number of scans / rows:** 3
- **Scan IDs:** `[1, 14, 27]`
- **Retention times (sec):** `[240.211, 240.885, 241.533]`
- **MS level:** All 1 (`ms_level = 1`)
- **Metadata:**
  - `vendor`: `thermo`
  - `ms_level_file`: `ms1`
  - `row_granularity`: `spectrum`
  - `source_filename`: `exploris480_ms1_dia_3cycles.raw`
  - `source_id`: `MA10459C_20260930114656`
  - `acquisition_start_time`: `2026-09-30T11:46:56Z`

### MSn Trace (`<stem>.msn-trace.parquet`)
- **Number of scans / rows:** 36
- **Scan IDs:** 36 MS2 scans across the 3 cycles:
  - Cycle 1: scans `2` to `13` (12 DIA isolation windows)
  - Cycle 2: scans `15` to `26` (12 DIA isolation windows)
  - Cycle 3: scans `28` to `39` (12 DIA isolation windows)
- **MS level:** All 2 (`ms_level = 2`)
- **Metadata:**
  - `vendor`: `thermo`
  - `ms_level_file`: `msn`
  - `row_granularity`: `spectrum`
  - `source_filename`: `exploris480_ms1_dia_3cycles.raw`
  - `source_id`: `MA10459C_20260930114656`
  - `acquisition_start_time`: `2026-09-30T11:46:56Z`

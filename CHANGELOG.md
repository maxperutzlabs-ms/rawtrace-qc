# Changelog

## [Unreleased]

### Added
- The scan-trace specification in `docs/scan-trace-spec.md`.

### Changed
- The trace schema no longer reserves the columns `charge_state`, `collision_energy`, and `activation_type`. They are out of scope for now.
- Trace files may contain the optional `injection_time_ms` column, as the specification allows. Strict loading no longer rejects it as reserved.

### Removed
- **Breaking:** `ColumnLogicalType.TEXT`. It was only used by `activation_type`, which is no longer reserved, so no schema-v1 column has a text type.

## [0.1.0] - 2026-11-05

### Added
- Initial release of **rawtrace-qc**.
- Discovery of Thermo `.raw` files and Bruker timsTOF `.d` folders from files, folders, and glob patterns, with optional size and age checks.
- Extraction of scan traces with total ion current and base peak intensity to validated Parquet files. Bruker extraction is native, and Thermo extraction uses the separate `ThermoScanHeaderExtractor` tool.
- Interactive HTML reports in a single file that also opens offline, with TIC, BPC, and metadata tabs.
- Overlay, stacked, and pairwise report views with a selectable reference trace and selection by MS level and FAIMS compensation voltage.
- Desktop application for Windows (`gui` extra) with drag and drop, folder scans, filename patterns, a trace cache, and temporary or permanent reports.
- Command-line interface (`cli` extra) for batch trace extraction.
- Setup of the Thermo tool from the desktop application and the command line, with a pinned and checksum-verified download or local ZIP file and explicit license acceptance.
- Python library API for discovery, extraction, processing, and reporting.

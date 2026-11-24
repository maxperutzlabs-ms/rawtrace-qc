# Changelog

## [Unreleased]

### Added
- The scan-trace specification in `docs/scan-trace-spec.md`.
- `traces` describes the full contract: `ColumnDefinition` has a unit, the files that may contain the column, and a fixed bit width (`ColumnBitWidth`), and `TRACE_METADATA` describes each metadata field with `MetadataDefinition`.

### Changed
- rawtrace-qc now uses version 0.3.1 of the Thermo tool (`ThermoScanHeaderExtractor`) and supports Thermo files on Linux and macOS, including installation from the `.tar.gz` archives of these systems. Windows on Arm uses its own build instead of the x64 build. The new version comes with new Thermo license terms. Thermo trace files now give `acquisition_start_time` as the local clock time of the acquisition computer, without a trailing `Z`.
- The license state of the Thermo tool is read with its `--license-status` command. `ThermoHelperStatus` has the new field `license_marker_path`, and `query_license_status()` returns a `ThermoLicenseStatus`. If the Thermo tool cannot use its license folder, rawtrace-qc raises the new `ThermoHelperConfigError`.
- The trace schema no longer reserves the columns `charge_state`, `collision_energy`, and `activation_type`. They are out of scope for now.
- Trace files may contain the optional `injection_time_ms` column, as the specification allows. Strict loading no longer rejects it as reserved.
- Loading and writing a trace now rejects files without rows, with a repeated `scan_id`, or with rows that are not sorted by retention time and then by `scan_id`, as the specification requires.
- Loading and writing a trace now rejects float columns whose bit width the specification does not allow, for example a 64-bit `total_ion_current` in precision mode `low`.
- Error messages about a column with the wrong type now say which kind of numbers the column must contain.
- Extraction raises more specific errors: `AcquisitionAccessError` for a raw file that cannot be opened, `AcquisitionReadError` for one that is not readable, `NoScansError` for a raw file without scans of the requested MS levels, and `TraceWriteError` when the trace files cannot be written. They subclass `ExtractionError`. A run without any scans is now reported as such, and a timeout no longer says that the file may be corrupt.
- **Breaking:** A crash, an internal error or an unknown exit code of the Thermo tool now raises `ThermoHelperCommandError` instead of `ExtractionError`, and exit codes 4 and 5 during extraction raise `ThermoHelperLicenseError` and `ThermoHelperConfigError`. The new `is_thermo_setup_error()` tells setup problems of the Thermo tool from per-file failures.
- Error messages of the Thermo tool no longer contain its raw output. Only its last message line is shown.
- rawtrace-qc keeps the license acceptance of the Thermo tool in its own data folder, separately for each version of the Thermo tool. After this update, you accept the new Thermo license once more. The new `thermo_config_directory()` returns this folder. If `THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR` is set, the Thermo tool uses that folder instead.

### Removed
- **Breaking:** The `--data-directory` option of `rawtrace-qc thermo status`, `thermo install` and `thermo accept-license`. These commands now always use the application data folder of the user account, which `extract` and the desktop application also use.
- **Breaking:** `RUNTIME_FALLBACKS`. Every supported runtime now has its own pinned build, so there is nothing to replace it with.
- **Breaking:** `is_license_accepted()`. Use `query_license_status(executable).accepted` instead.
- **Breaking:** `ColumnLogicalType.TEXT`. It was only used by `activation_type`, which is no longer reserved, so no schema-v1 column has a text type.

### Fixed
- If the Thermo tool cannot be started, the message now explains why: on Linux and macOS, a file without execute permission is reported as "not executable", and on Linux, a missing program loader is reported as a system without glibc.
- Trace files whose `faims_cv` column is null in only some rows now load, as the specification allows, and `extract` writes them. Reports still leave such a file out, with a message that the FAIMS CV is missing for some scans.

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

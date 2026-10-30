# rawtrace-qc Documentation

## Purpose

`rawtrace-qc` is a vendor-neutral Python library for discovering mass-spectrometry raw acquisitions, extracting scan-level traces, validating trace artifacts, and preparing interactive QC reports.

The current implementation supports Bruker timsTOF `.d` and Thermo `.raw` discovery and scan-trace extraction. Thermo extraction is powered by the external `ThermoScanHeaderExtractor` helper.

The package is library-first. Applications such as a command-line tool or GUI should call the public library services rather than implement vendor-specific filesystem or processing logic themselves.

## Features

- [x] Vendor-aware raw-file discovery for Bruker timsTOF `.d` directories and Thermo `.raw` files
- [x] Bruker scan-trace extraction
- [x] Thermo scan-trace extraction
- [x] Scan-trace validation

- [x] Scan-trace processing
    - [ ] FAIMS "combined" mode
    - [ ] Optimize dtype and precision for compact HTML serialization
    - [ ] Process filters requested channels by using `ProcessingOptions`
- [x] Multi-tab HTML report generation
- [x] Cyclopts command-line interface
- [x] Thermo helper status, installation, and explicit license setup
- [ ] Graphical user interface (pyside6)

## Library API

The public library is organized around services that can be used by any application. Applications should provide input directories and options, call the relevant service, and present the returned models to users. Filesystem traversal, vendor recognition, validation, and error handling belong in the library.

The public services currently include `rawtrace_qc.discovery.discover`, `rawtrace_qc.extractors.BrukerExtractor`, `rawtrace_qc.extractors.ThermoExtractor`, Thermo helper locating and setup services in `rawtrace_qc.thermo`, and the trace artifact functions in `rawtrace_qc.traces`. The CLI and GUI call these same services and do not own vendor-specific extraction or installation behavior.


## File Discovery

Use `discover()` to find valid raw acquisitions below a source directory. By default it examines direct children, uses the built-in Thermo and Bruker validators, requires files to be at least 1 MiB, and requires the relevant recording data to be at least 10 minutes old.

Use `discover_inputs()` when inputs may be individual files, directories, or glob patterns. Patterns support `*`, `?`, character classes such as `[ab]`, and recursive `**`. Unmatched patterns and nonexistent literal paths are returned as `DiscoveryResult.issues`; path resolution does not validate acquisition formats. `**` expansion is recursive regardless of `DiscoveryOptions.scope`. The scope controls traversal inside concrete directories that are not already valid acquisitions, and a directly validated acquisition is never traversed.

Set `DiscoveryScope.RECURSIVE` to inspect descendants. Recursive traversal does not follow symlinks. A directory ending in `.d` that contains a regular `.tdf` or `.tdf_bin` file is treated as a possible Bruker acquisition and is not traversed further. This prevents files inside an acquisition from being reported as separate acquisitions.

The result contains valid candidates and traversal issues:

- `DiscoveryResult.candidates` contains only complete acquisitions.
- `DiscoveryResult.issues` contains non-fatal problems encountered below the source directory.
- An invalid, inaccessible, symlinked, or non-directory source raises `DiscoveryError`.

Thermo candidates must be non-empty regular files with a case-insensitive `.raw` suffix. Bruker candidates must be directories with a case-insensitive `.d` suffix containing at least one non-empty `.tdf` file and one non-empty, sufficiently old `.tdf_bin` file. Bruker member basenames are arbitrary.

The thresholds and clock are configurable through `DiscoveryOptions`. Additional vendors can be added by registering a validator on `DiscoveryRegistry`. A validator receives the traversed files and directories, the configured thresholds, and the current Unix timestamp. It returns only paths that are valid for that vendor.

### Input Pattern Example

```python
from rawtrace_qc.discovery import DiscoveryOptions, DiscoveryScope, discover_inputs

result = discover_inputs(
	["/data/**/*.raw", "/data/run.d"],
	DiscoveryOptions(scope=DiscoveryScope.RECURSIVE),
)
```

### Basic Example

```python
from pathlib import Path

from rawtrace_qc.discovery import DiscoveryOptions, DiscoveryScope, discover

result = discover(
	Path("/data/raw"),
	DiscoveryOptions(scope=DiscoveryScope.RECURSIVE),
)

for candidate in result.candidates:
	print(candidate.vendor, candidate.format, candidate.path)

for issue in result.issues:
	print(f"Could not inspect {issue.path}: {issue.message}")
```

## Application Integration

An application should treat discovery as an input-review step before extraction or reporting:

1. Ask the user for a source directory and discovery scope.
2. Call `discover()` with the selected options.
3. Show valid candidates to the user or pass them to an extractor.
4. Log or display traversal issues without treating them as valid acquisitions.
5. Handle `DiscoveryError` as an input-level failure that requires user action.

The application should not walk raw-file directories itself, inspect vendor-specific member files, or infer validity from filename suffixes. Those rules belong to the discovery service so that the command-line interface, GUI, and other library consumers behave consistently.

For a single file or acquisition folder supplied by a file dialog or drag and drop, use `validate_path(path, options)`. It applies the same built-in validators and thresholds as `discover()` and returns one `DiscoveryCandidate` or `None` without traversing the parent directory.

## Scan-Trace Extraction

`BrukerExtractor.extract()` reads native frame metadata from `analysis.tdf`, including `Frames.SummedIntensities` for total ion current and `Frames.MaxIntensity` for base-peak intensity when those optional columns are available. It writes schema-v1 Snappy Parquet artifacts using the naming convention `<run-name>.ms1-trace.parquet` and `<run-name>.msn-trace.parquet`.

Both `select_ms1` and `select_msn` default to `True`. This writes every available level: an MS1 artifact is written when MS1 rows exist, and an MSn artifact is written only when MSn rows exist. Selecting only one level writes only that level. Selecting a level that does not exist raises an error, except that an all-level request omits unavailable levels. When both flags are `False`, the input is structurally checked and no output is created.

Bruker MSn rows have `row_granularity` set to `frame-aggregate`. A frame can contain multiple precursor isolation events, so these rows must not be interpreted as individual precursor spectra.

### Basic Extraction Example

```python
from pathlib import Path

from rawtrace_qc.extractors import BrukerExtractor
from rawtrace_qc.traces import load_trace

result = BrukerExtractor().extract(
	Path("/data/raw/sample.d"),
	output_directory=Path("/data/traces"),
	precision_mode="high",
)

if result.ms1_path is not None:
	ms1 = load_trace(result.ms1_path)
	print(ms1.table.num_rows, ms1.metadata["vendor"])

if result.msn_path is not None:
	msn = load_trace(result.msn_path)
	print(msn.metadata["row_granularity"])
```

The extractor overwrites existing artifacts with the same destination path. It currently emits `scan_id`, `retention_time_sec`, `ms_level`, and the available native `total_ion_current` and `base_peak_intensity` columns. Each artifact records the input folder name, including its `.d` suffix, as the required `source_filename` metadata field. The test SQLite fixture retains additional frame fields such as `AccumulationTime` for future extraction work, but `injection_time_ms` is not emitted yet.

Bruker extraction records `GlobalMetadata.AcquisitionDateTime` as the recommended `acquisition_start_time` metadata field, normalized to an ISO-8601 UTC timestamp and shared by the MS1 and MSn artifacts. It records `GlobalMetadata.AnalysisId` as the recommended `source_id` metadata field when present.

### Thermo Extraction Example

`ThermoExtractor.extract()` extracts compact scan-header metadata from Thermo `.raw` files by executing the external `ThermoScanHeaderExtractor` helper. It produces schema-v1 Snappy Parquet artifacts following the same naming convention (`<run-name>.ms1-trace.parquet` and `<run-name>.msn-trace.parquet`) and passes output through the same schema and trace validation.

```python
from pathlib import Path

from rawtrace_qc.extractors import ThermoExtractor
from rawtrace_qc.traces import load_trace

extractor = ThermoExtractor()
result = extractor.extract(
	Path("/data/raw/sample.raw"),
	output_directory=Path("/data/traces"),
	precision_mode="low",
)

if result.ms1_path is not None:
	ms1 = load_trace(result.ms1_path)
	print(ms1.table.num_rows, ms1.metadata["vendor"])

if result.msn_path is not None:
	msn = load_trace(result.msn_path)
	print(msn.table.num_rows, msn.metadata["row_granularity"])
```

## Thermo Helper Integration (ThermoScanHeaderExtractor)


Thermo `.raw` scan-header extraction relies on an external Windows command-line utility named `ThermoScanHeaderExtractor`. The library manages specification pinning, helper location, status inspection, and license verification.

The helper remains separate because it uses Thermo's Windows-specific RAW access stack and its own license agreement. It is not bundled in the Python package or wheel. Installing the Python CLI does not install the helper, and extracting or reporting a `.raw` file never installs the helper or accepts its license automatically.

### Pinned Release Specification

The expected helper release is pinned in `rawtrace_qc.thermo.THERMO_HELPER_SPECIFICATION`. This specification defines the exact expected release version (`0.2.0`), asset archive name, official download URL, SHA-256 checksum digest, and executable name (`ThermoScanHeaderExtractor.exe`).

### Install the Helper

Call `install_thermo_helper()` to download and install the pinned release. For offline or restricted environments, pass a local ZIP archive instead:

```python
from pathlib import Path

from rawtrace_qc.thermo import install_thermo_helper

executable = install_thermo_helper()
# Or install_thermo_helper(Path("/media/helper/ThermoScanHeaderExtractor-v0.2.0-win-x64.zip"))
```

Both sources are checked against the pinned SHA-256 digest before extraction and installed through a temporary staging directory. The completed helper is atomically moved to `<user_data_dir>/tools/thermoscanheaderextractor/<version>/ThermoScanHeaderExtractor.exe`. Reinstalling the same archive is safe; an existing directory that does not match the pinned installation is left untouched and causes an installation conflict. Installation never executes the helper or accepts the Thermo license. Review and record explicit agreement through the library API described below.

### Helper Locating and Resolution Priority

The library locates the helper without side effects, searching in strict priority order:

1. **Explicit path**: A user-supplied path to the executable or its containing directory (via `explicit_path`).
2. **Managed user data directory**: The pinned release directory in the per-user application data directory, located at `<user_data_dir>/tools/thermoscanheaderextractor/<version>/ThermoScanHeaderExtractor.exe`.

`find_thermo_helper_path()` checks these locations on disk without executing any process. If neither candidate exists, it returns `None`.

### Status and License Verification

`get_thermo_helper_status()` inspects the helper state without side effects, returning a `ThermoHelperStatus` object. When no helper executable exists on disk, it returns immediately without running any subprocess. When an executable is present, it verifies the reported version by executing `--version` and, if the version matches, asks the helper whether the Thermo license has been accepted.

The helper is the sole authority on its license state; rawtrace-qc does not inspect where or how acceptance is recorded (since helper v0.2.0 it is recorded per user). `is_license_accepted()` invokes the helper without arguments: the helper checks acceptance before parsing arguments and exits with code `4` when the terms have not been accepted, or with its usage exit code `1` otherwise. This check never accepts the terms or changes the license state.

The status distinguishes at least:

- `ThermoHelperState.NOT_INSTALLED`: No helper executable was found at the prioritized locations. No subprocess is executed.
- `ThermoHelperState.UNSUPPORTED_PLATFORM`: The current platform is not Windows.
- `ThermoHelperState.UNLICENSED`: The helper is installed and its version matches, but it reports that the Thermo license has not been accepted, or its license state could not be determined.
- `ThermoHelperState.INVALID_VERSION`: The helper is installed but returned an unreadable version, crashed, timed out, or reported a version that does not match the pinned specification.
- `ThermoHelperState.READY`: The helper is installed, matches the expected version, and reports the Thermo license as accepted.

### License Review and Acceptance

Use `get_thermo_license_text()` to retrieve the agreement for display without accepting it. After the user has reviewed the agreement and explicitly agreed to it, call `accept_thermo_license()`. This library function invokes the helper's `--agree-to-terms` command when the helper does not already report the license as accepted, then asks the helper again to confirm the acceptance. Both functions use the prioritized helper locations by default and support an explicit helper path.

```python
from rawtrace_qc.thermo import accept_thermo_license, get_thermo_license_text

license_text = get_thermo_license_text()
print(license_text)

# Call only after the user has reviewed and accepted the agreement.
accept_thermo_license()
```

## Command-Line Interface

Install the optional CLI dependency and run `rawtrace-qc`:

```bash
uv sync --extra cli
rawtrace-qc thermo status
```

### Batch Trace Extraction

Use `extract` to process one or more acquisition paths:

```bash
rawtrace-qc extract sample.raw run.d
rawtrace-qc extract /data/acquisitions --recursive --output-dir /data/traces --precision high --no-msn
```

For each supplied path, the library first validates it as one complete acquisition. A valid Thermo `.raw` file or Bruker `.d` directory is processed directly. Any path that is not a valid acquisition is treated as a directory to scan; a path that cannot be scanned is reported as a discovery issue. By default, directory scans inspect direct children. `--recursive` includes descendants, while discovery still treats a complete Bruker `.d` directory as one acquisition rather than scanning inside it.

The command also accepts quoted glob patterns, for example `rawtrace-qc extract "/data/**/*.raw"`. The pattern is expanded by the library, so `**` matches recursively regardless of `--recursive`; that flag only controls traversal of matched directories that are not complete acquisitions. An unmatched pattern or nonexistent literal path is reported as a discovery issue.

Without `--output-dir`, each acquisition's traces are written beside that acquisition. The default names retain the source name, including `.raw` or `.d`, followed by `.ms1-trace.parquet` or `.msn-trace.parquet`. `--output-dir DIR` sends every candidate's artifacts to the shared directory. Existing artifacts with the same destination name are overwritten by the extractors.

With no MS-level flags, both levels are selected. `--ms1` selects only MS1, `--msn` selects only MSn, and supplying both flags selects both. A single-level selection can fail for an acquisition that does not contain that level. `--precision low` (the default) stores trace values as float32; `--precision high` stores them as float64.

The command reports one `succeeded`, `skipped`, or `failed` outcome for each discovered candidate, with output paths or a reason. Discovery and traversal issues are listed separately because those paths were not extracted candidates. In a mixed-vendor batch, Thermo helper readiness is checked once before Thermo extraction. If it is not ready, each Thermo candidate is reported as skipped with the relevant setup guidance, while Bruker candidates continue normally. The command exits with code `0` only if every candidate succeeded and there were no discovery issues; it exits nonzero for any skip, extraction failure, or discovery issue, so scripts can use the exit code while parsing the per-candidate summary for detail.

`thermo status` is read-only. It exits successfully only when the pinned helper is installed, its version matches, and it reports the Thermo license as accepted. For an incomplete setup it prints the state and the corresponding setup command.

Install the pinned release from its configured download URL, or provide a local archive for an offline installation:

```bash
rawtrace-qc thermo install
rawtrace-qc thermo install --from-zip D:\offline\ThermoScanHeaderExtractor-v0.2.0-win-x64.zip
```

Installation verifies the pinned SHA-256 checksum and does not run the helper or accept its license. After reviewing Thermo's agreement, run the explicit acceptance command. It displays the agreement returned by the helper and has the helper record acceptance, which since helper v0.2.0 applies to the current user account rather than to one helper installation:

```bash
rawtrace-qc thermo accept-license
```

For a centrally managed installation, either install into a shared data root and pass the same `--data-directory` to status and acceptance, or point commands directly at the shared executable with `--helper-path`. A helper installed from a shared root is stored below `tools/thermoscanheaderextractor/<version>/`; a direct executable path may also name its containing directory. Because acceptance is recorded per user, every account that runs extractions, including service accounts, must accept the terms once.

```bash
rawtrace-qc thermo install --data-directory \\server\rawtrace-tools
rawtrace-qc thermo status --data-directory \\server\rawtrace-tools
rawtrace-qc thermo accept-license --data-directory \\server\rawtrace-tools
rawtrace-qc thermo status --helper-path \\server\tools\ThermoScanHeaderExtractor.exe
rawtrace-qc thermo accept-license --helper-path \\server\tools\ThermoScanHeaderExtractor.exe
```

The helper's release version, asset, and checksum are pinned by the installed `rawtrace-qc` release. To upgrade the helper, upgrade `rawtrace-qc` to a release with the newer pin, then run `rawtrace-qc thermo install`; use `--from-zip` when the matching release archive must be transferred offline. Versioned installations are kept separate, and a conflicting existing installation is not silently overwritten. Run `rawtrace-qc thermo status` after upgrading and accept the Thermo agreement again if the helper reports it as not accepted; acceptance recorded by helper v0.1.0 is not carried over to v0.2.0.

### Locating a Usable Helper

`locate_thermo_helper()` returns the validated `Path` to a ready helper executable. If the helper is not ready or the platform is unsupported, it raises a specific, actionable exception:

- `UnsupportedPlatformError`: Raised on non-Windows platforms (`sys.platform != "win32"`).
- `ThermoHelperNotFoundError`: Raised when no executable is found at the prioritized locations, with searched paths and installation guidance.
- `ThermoHelperVersionError`: Raised when the helper reports a mismatched version or fails to report a readable version.
- `ThermoHelperLicenseError`: Raised when the Thermo license agreement has not been accepted via `ThermoScanHeaderExtractor.exe --agree-to-terms`.

### Basic Helper Example

```python
from pathlib import Path

from rawtrace_qc.thermo import (
	ThermoHelperState,
	get_thermo_helper_status,
	locate_thermo_helper,
)

# Inspect helper status without raising exceptions
status = get_thermo_helper_status()
print(status.state, status.message)

if status.state is ThermoHelperState.READY:
	print(f"Helper is ready at: {status.path} (version {status.version})")

# Locate helper for extraction, raising dedicated exceptions on problems
try:
	executable = locate_thermo_helper()
	print(f"Usable helper executable: {executable}")
except Exception as error:
	print(f"Cannot use helper: {error}")
```

## Scan-Trace Import and Validation

`load_trace(path)` reads a Parquet artifact into an Arrow table and validates its required columns, metadata, MS-level contents, and Snappy compression before returning a `TraceArtifact`. The same table and metadata contract is available through `validate_trace(table, metadata)` for callers that construct artifacts in memory. Arrow tables are immutable, so transformations such as filtering, casting, adding columns, and dropping columns return new tables. Later processing code can keep using Arrow or convert to pandas only when a pandas-specific operation or report library requires it.

Validation is strict by default and rejects columns that are not implemented by this package. Use `load_trace(path, strict=False)` when consuming artifacts that contain contract-defined future columns or additional producer columns. Known future columns are still type-checked in non-strict mode; unknown columns are ignored.

The artifact contract requires `scan_id`, `retention_time_sec`, and `ms_level`. Optional columns may be omitted when unavailable, while null values in present optional columns represent row-level extraction failure. Required columns cannot contain null values. A `faims_cv` column must contain either only null values or a finite numeric value for every row.

The required Parquet metadata fields are `schema_version`, `vendor`, `ms_level_file`, `precision_mode`, `row_granularity`, and `source_filename`. The recommended fields `source_id`, `generator`, `extracted_at`, `acquisition_start_time`, and `acquisition_path` may be absent from a file. `load_trace()` exposes every recommended field in `TraceArtifact.metadata`, using `None` when a field is absent; processing preserves those missing values in `ProcessedTableMetadata`.

## Scan-Trace Processing

`process_traces()` prepares one or more loaded `TraceArtifact` instances for report generation without depending on Plotly, pandas, or another report library. It returns a tuple of immutable `ProcessedTable` objects. Each object contains a report-ready Arrow table and a `ProcessedTableMetadata` dataclass.

The default processing options select MS1 and MS2, split tables by FAIMS compensation voltage when `faims_cv` contains values, and convert retention time from seconds to minutes. An MSn artifact containing several levels is therefore split into one processed table per selected MS level and FAIMS partition. Global FAIMS mode is ignored for tables without FAIMS values. `FaimsProcessingMode.COMBINED` is reserved for a future implementation and raises `NotImplementedError` for FAIMS-bearing tables. Set `minimum_faims_percentage` to a value from 0 to 100 to omit FAIMS partitions containing fewer than that percentage of rows in their selected MS-level table.

Processed tables contain `retention_time_min` and the available `total_ion_current` and `base_peak_intensity` columns. The retention-time unit is recorded as `time_unit="min"`. `scan_id`, `ms_level`, and `faims_cv` are removed from the processed table because they are represented in the table metadata. Provenance fields such as the source filename, source ID, vendor, generator, extraction time, acquisition start time, precision, and row granularity are copied into `ProcessedTableMetadata`; the source filename and source ID are read from the artifact metadata rather than inferred from the trace path.

Labels initially equal the raw-file name. Use `relabel_tables()` to create new processed-table instances with shortened or otherwise customized display labels without mutating the original results. Plotly figures, colors, line styles, channel controls, and HTML serialization belong to the later report layer.

### Processing Example

```python
from pathlib import Path

from rawtrace_qc.processing import process_traces, relabel_tables
from rawtrace_qc.traces import load_trace

artifacts = [
	load_trace(Path("/data/traces/sample.ms1-trace.parquet")),
	load_trace(Path("/data/traces/sample.msn-trace.parquet")),
]
processed = process_traces(artifacts)
processed = relabel_tables(processed, [table.metadata.rawfile_name for table in processed])

for item in processed:
	print(item.metadata.label, item.metadata.ms_level)
	print(item.table.column_names)
```

The current processor expects valid schema-v1 artifacts; `validate_trace()` owns source-contract checks before partitioning begins. Precision reduction for compact HTML serialization is reserved for a later implementation because its exact representation depends on the report serializer.

## HTML Reporting

`rawtrace_qc.report` accepts only `ProcessedTable` instances and report configuration. It does not load Parquet files, inspect raw acquisitions, or repeat MS-level and FAIMS partitioning. `build_report()` creates a renderer-neutral `ReportDocument`, while `render_html()` returns a complete HTML string and `write_html()` writes it to disk.

The generated report is one HTML file with a dynamically populated tab bar. Each selected available channel gets a plot tab, followed by a metadata tab containing one row per `ProcessedTable`. The default channel registry labels `total_ion_current` as TIC and `base_peak_intensity` as BPC. Future channels can use a `ChannelSpec` supplied through `ReportOptions`. By default, all channels advertised by `ProcessedTableMetadata.channels` are selected; explicit `ReportOptions(channels=...)` restricts the report and fails clearly when a requested channel is unavailable.

The plot tabs share MS-level, FAIMS CV, view, and reference-trace controls. Only MS levels present in the processed tables are offered, and the first available level is selected initially. Reports initially sort by ascending `acquisition_start_time`, followed by ascending `rawfile_name`; unavailable or blank acquisition times fall back to raw-file order. Overlay and stacked views expose a `Selected traces` checkbox popover with `Select all` and `Select none` actions. The reference is always plotted in these views, while the selected-trace control filters the other visible traces; the reference is omitted from that control while selected. Pairwise view instead exposes a `Comparison trace` selector and previous/next buttons, and plots only the reference and comparison trace. Up and left arrow keys select the previous comparison trace; down and right select the next one while the comparison selector is focused. Pairwise requires a reference and cycles candidates in the current sorted trace order. The reference control offers `None` or the traces currently visible in the figure; selecting a reference overrides only that trace's assigned color with the reserved facility red and renders it last in overlay and Pairwise views so it appears on top of the other traces. Stacked view keeps the current sorted trace order while still applying the reference color. Changing or clearing the reference recomputes the relevant view state from the current sorted trace order. Trace colors are stable per source ID or raw-file name, legends identify the source and optional FAIMS CV, and plot traces use solid lines with small square legend swatches. The palette starts with the facility dark blue and turquoise, uses distinct non-red colors for additional traces, and reserves facility red for references. Stacked view gives each active trace a fixed-height subplot so traces remain inspectable as their number grows. The metadata tab displays selected fields from `ProcessedTableMetadata`; click a metadata header to cycle through ascending sort, descending sort, and no sort. Multiple headers can be active at once and are applied in the order they were first clicked. The same order controls the metadata rows, plots, and trace selectors. `acquisition_path` is available but intentionally not included in the default field list. Use `ReportOptions(metadata_fields=...)` to choose a different set.

The plotting area includes an icon-only fullscreen button with a tooltip that expands the plots, legends, and Plotly toolbar; pressing Escape exits fullscreen. Stacked views become scrollable when their fixed-height subplots exceed the available plot region. Pairwise arrow-key navigation also works when the comparison selector is not focused, provided another form field is not receiving keyboard input.

Reports embed Plotly JavaScript by default so the output can be opened without network access. Use `ReportOptions(asset_mode="cdn")` for a smaller report that loads the matching Plotly version from the public CDN.

### Report Example

```python
from pathlib import Path

from rawtrace_qc.processing import process_traces
from rawtrace_qc.report import ReportOptions, write_html
from rawtrace_qc.traces import load_trace

processed = process_traces(
	[
		load_trace(Path("/data/traces/sample.ms1-trace.parquet")),
		load_trace(Path("/data/traces/sample.msn-trace.parquet")),
	]
)

write_html(
	processed,
	Path("/data/reports/sample-qc.html"),
	options=ReportOptions(
		channels=("total_ion_current", "base_peak_intensity"),
		metadata_fields=("label", "vendor", "ms_level", "faims_cv", "row_granularity"),
	),
)
```
The report package is deliberately separated into report models, channel definitions, data preparation, and the Plotly HTML renderer. A later report type can reuse `ProcessedTable` and the preparation contract while providing a different renderer or HTML shell.

## Desktop GUI

The optional PySide6 desktop application combines discovery, raw-file selection, cached extraction, and one-button HTML report generation. Install it with the `gui` extra and launch it with the packaged entry point:

```bash
uv sync --extra gui
rawtrace-qc-gui
```

The extra is named `gui` because it contains the desktop interface dependency. An `app` extra can remain available later for a broader application bundle without making the meaning of the current optional dependency ambiguous.

Choose a source folder and scan either direct children or descendants. Selecting a new source clears the candidate list before discovery begins. The discovery service removes invalid `.raw` files and `.d` folders before they reach the candidate review window. Candidate names are shown with their full paths in tooltips. The review window supports configured filename patterns and session-only custom patterns. Include patterns are ORed, exclude patterns are ORed, and any matching exclude pattern wins. Included candidates are shown first with active checkboxes; excluded candidates are shown below in a muted style.

The selected raw-file list keeps unique resolved paths, supports multi-selection removal, select-all/select-none controls, drag and drop, and file or folder dialogs. Each selected path has an active checkbox, and only active paths participate in report generation.

GUI settings are stored as JSON in the platform user configuration directory. They include discovery thresholds in megabytes and minutes (converted internally to bytes and seconds for discovery), recursive/direct scope, preconfigured patterns, the trace-cache directory, the permanent-report directory, and ThermScanHeaderExtractor settings. Trace cache keys include source metadata, the vendor, extractor type, precision, and selected MS levels; each key uses the first 16 hexadecimal characters of its SHA-256 digest. Cached artifacts use short filenames (`trace.ms1-trace.parquet` and `trace.msn-trace.parquet`), while their metadata retains the original raw filename. Invalid or incomplete Parquet cache entries are rebuilt through the extractor and validated before use.

Reports can be temporary, in which case the GUI owns their temporary directories until it closes, or permanent, in which case the selected report directory is used. The default report uses embedded Plotly assets and can be opened immediately in the default browser.

Thermo GUI reports use the same `ThermoExtractor` and trace cache as the CLI. The GUI does not silently install the helper or accept its license; configure an explicit helper executable in GUI settings or use the library's managed installation path.

## Developer Guide

The project uses `uv` for dependency management and command execution. Install the project and development dependencies with:

```bash
uv sync
```

Run the test suite with:

```bash
uv run pytest
```

Source files use Ruff for linting and formatting. Tests use Ruff for formatting with a 120-character line length; test linting is not enforced.

```bash
uv run ruff check src
uv run ruff format --check src
uv run ruff format --check tests
uv run pyrefly check
```

Source formatting uses the project configuration in `pyproject.toml`. Test formatting uses `tests/ruff.toml`.

## Documentation Maintenance

This document describes behavior that exists in the package. Update it when public APIs, supported formats, configuration, workflows, or known limitations change.
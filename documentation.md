# rawtrace-qc developer documentation

This document is for developers and AI agents who change rawtrace-qc. It describes the design, the conventions, and the behavior that a change must keep. End-user instructions belong in `README.md`.

## Rules for every change

Follow these rules first, because the rest of the design depends on them:

- **Put behavior in the library.** The GUI and the CLI present results to the user. Filesystem traversal, vendor rules, validation, and error classification belong in the library, so that all clients behave in the same way.
- **Never accept the Thermo license for the user.** Extraction and installation must not accept it. Tests must not run `--agree-to-terms` against the real helper, because acceptance applies to the whole user account.
- **Validate every trace artifact.** Producers and consumers use the contract in `rawtrace_qc.traces`, so an invalid artifact fails with `ArtifactValidationError`.
- **Keep optional dependencies optional.** The core package must import without Cyclopts and without PySide6.
- **Do not guess scientific meaning.** For example, a Bruker MSn row is a frame aggregate and not one precursor spectrum.
- **Run everything through `uv`.** Do not add a dependency without the agreement of the maintainer.
- **Run the checks and add tests.** See [Checks](#checks) and [Testing](#testing).

## Terms

Use these terms consistently in code and in documentation:

| Term | Meaning |
|---|---|
| Acquisition | One Thermo `.raw` file or one Bruker `.d` folder. User-facing text calls it a raw file. |
| Candidate | An acquisition that discovery accepted. |
| Trace artifact | A schema-v1 Snappy Parquet file with one row for each scan or frame. |
| Processed table | A report-ready Arrow table for one acquisition, one MS level, and one FAIMS CV. |
| Channel | A plotted value, such as `total_ion_current`. The report labels it TIC or BPC. |
| Helper | The external `ThermoScanHeaderExtractor` program. User-facing text calls it the Thermo tool. |
| Managed helper | The helper in the application data folder, which rawtrace-qc installs itself. |

## Architecture

Data moves through five stages, and each stage only uses the output of the previous stage:

1. `discovery` turns input paths into candidates.
2. `extractors` turn a candidate into trace artifacts.
3. `traces` loads a trace artifact into a validated `TraceArtifact`.
4. `processing` turns a `TraceArtifact` into processed tables.
5. `report` turns processed tables into one HTML file.

The packages in `src/rawtrace_qc` have these responsibilities:

| Package | Responsibility | Internal imports |
|---|---|---|
| `errors`, `models`, `environment` | Shared exceptions, `ExtractionResult`, and application data paths. | None |
| `discovery` | Finds and validates acquisitions. Knows nothing about extraction. | `errors` |
| `traces` | Defines, reads, writes, and validates the schema-v1 contract. | `errors` |
| `thermo` | Pins, installs, locates, checks, and runs the helper. | `environment`, `errors` |
| `extractors` | Vendor extractors that write trace artifacts. | `errors`, `models`, `thermo`, `traces` |
| `workflows` | Batch extraction and `create_extractor()`. | `discovery`, `errors`, `extractors`, `models`, `thermo` |
| `processing` | Splits artifacts into processed tables. Knows nothing about plots. | `errors`, `traces` |
| `report` | Builds a renderer-neutral document and renders the HTML. Reads no files. | `errors`, `processing` |
| `cli` | Cyclopts commands. Clients only. | `discovery`, `errors`, `thermo`, `workflows` |
| `gui` | PySide6 application and its services. Clients only. | All of the above except `cli` |

Do not add an import that goes against this table. `thermo.runner` imports a type from `extractors` only under `TYPE_CHECKING`, so there is no import cycle at runtime.

The GUI package currently contains services without any Qt dependency: `cache.py`, `reporting.py`, `workflow.py`, `patterns.py`, and `config.py`. Because `TraceCache` and `generate_report()` live there, other clients cannot use them without importing from `gui`. See [Add reports to the CLI](#add-reports-to-the-cli).

## Checks

Install all dependencies, including both extras:

```bash
uv sync --all-extras
```

After a code change, apply the formatter and the linter, and then run the type checker and the tests:

```bash
uv run ruff format
uv run ruff check --fix
uv run pyrefly check
uv run pytest
```

CI in `.github/workflows/ci.yml` runs the following checks with the locked dependencies, so a change must pass all of them:

- `ruff check .` and `ruff format --check .`.
- `pyrefly check`, which covers only `src`.
- `pytest --cov` on Ubuntu, Windows, and macOS with Python 3.12, 3.13, and 3.14.

Ruff settings differ between source and tests. Source files use 88 characters and the rules `E`, `F`, `I`, `UP`, and `B`. Because `tests/ruff.toml` replaces this configuration, tests use 120 characters and the default Ruff rules.

## Testing

Tests are in `tests/unit` and `tests/integration`. A collection hook adds the `unit` or `integration` marker from the folder, while tests that need the network carry an explicit `network` marker.

```bash
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m "not network"
```

The `network` marker also appears on tests in `tests/unit`, so only `-m "not network"` excludes all network access.

Write tests in this way:

- Group test methods in a class named after the tested function or class, such as `class TestDiscover:`.
- Use a descriptive method name, and do not add docstrings or comments to test methods.
- Put helpers and fixtures before the tests, which is the opposite of the module order in source files.
- Put shared helpers in `tests/support`.

Some test fixtures have special rules:

- **Bruker:** The `bruker_fixture` in `tests/conftest.py` builds a small SQLite `analysis.tdf`, so these tests need no external files.
- **Thermo:** `tests/data/thermo/exploris480_ms1_dia_3cycles.raw` is a real acquisition. Its `README.md` lists the expected output.
- **Mock helper:** Unit tests use `MockThermoHelper`, which keeps the license state in memory and writes nothing to disk.
- **Real helper:** Integration tests use the `thermo_helper_executable` fixture. It uses the managed helper if that is ready, and otherwise it installs the helper in `tests/.cache`. The fixture skips the test on an unsupported system or if the user has not accepted the license. A separate session fixture purges `tests/.cache` after 24 hours.
- **Network:** Use `urlopen_or_skip()` from `tests/support/network.py`. It skips on network and proxy failures, but it fails on a missing asset.
- **Qt:** GUI tests use `pytest.importorskip` and the `offscreen` Qt platform, so they run without a display.

Because helper v0.2.0 records the license state for each user, and on Windows that location cannot be redirected, tests cannot create an unaccepted state with the real helper. Mock tests therefore cover the unaccepted state and the acceptance flow. CI accepts the license on Windows on purpose, so that the real Thermo integration tests run there.

## Code conventions

- Put `from __future__ import annotations` as the first import in every module.
- Order a module from high to low abstraction: public API first, private helpers last.
- Do not add a trailing comma only to force a multiline layout. Let `ruff format` decide.
- Use frozen dataclasses with slots for models, and validate options in `__post_init__`.
- Use `StrEnum` for fixed sets of values.
- Export the public API from the `__init__.py` of each package.
- Write Google-style docstrings in American English with ASCII characters. They must work with `mkdocstrings`.
- Describe defaults in docstrings in a fixed form, such as `If True (default), ...` or `Defaults to 3.`.

Error messages must help a user who is not a developer. Say what went wrong, name the invalid value with `!r`, and say how to fix it:

```python
raise ConfigurationError(f"Invalid mode {mode!r}. Must be one of 'read' or 'write'.")
```

Expected failures derive from `RawtraceError` in `errors.py`. Clients catch this base class and show its message. The main subclasses are these:

- `ConfigurationError` for invalid options.
- `DiscoveryError` for a source that discovery cannot traverse.
- `ExtractionError` for a problem with one acquisition. Its `path` attribute names that acquisition.
- `ArtifactValidationError` for a contract violation.
- `ProcessingError` and `ReportError` for invalid input to those stages.
- `ThermoHelperError` and its subclasses for a problem with the machine rather than the file.
- `OperationCancelledError` for a cancellation by the caller.

Git commits use the Conventional Commits format with a scope where it helps, such as `fix(gui): ...` or `feat(thermo): ...`. Write the summary as an imperative sentence.

## Discovery

`discovery` provides these entry points:

- `discover(source, options)` scans one directory.
- `discover_inputs(inputs, options)` accepts files, directories, and glob patterns. Patterns support `*`, `?`, `[ab]`, and a recursive `**`.
- `inspect_path(path, options)` checks one path and also returns the reason for a skip.
- `validate_path(path, options)` checks one path and returns only the candidate or `None`.

Results keep three outcomes apart, so that clients can explain each of them:

- `candidates` are complete acquisitions.
- `skipped` are recognized acquisitions that were not accepted. The reason is `too_recent`, `too_small`, `incomplete`, or `inaccessible`.
- `issues` are problems with an input or with traversal. An input without candidates gets the code `no_ready_candidates` if it contains skipped acquisitions, and `no_candidates` otherwise.

An invalid or symlinked source raises `DiscoveryError`. Other file types are not acquisitions, so discovery does not report them.

Discovery applies these rules:

- Suffixes match in upper and lower case.
- A Thermo candidate is a regular file with a `.raw` suffix.
- A Bruker candidate is a `.d` directory with a non-empty `.tdf` file and a `.tdf_bin` file. The size and age checks apply to the `.tdf_bin` file.
- Recursive traversal does not follow symlinks. It also does not enter a `.d` directory that contains a `.tdf` or `.tdf_bin` file, even if discovery does not accept that directory.
- `**` is always recursive. `DiscoveryScope` only controls the traversal of concrete directories.
- `DiscoveryOptions` defaults to no size check and no age check. A check with the value `0` is off. The GUI uses 1 MB and 2 minutes by default.

## Extraction

Both extractors implement the `Extractor` protocol, and `create_extractor()` selects one by vendor. `extract_batch()` adds discovery and checks the helper state once for a batch. If the helper is not ready, it skips Thermo candidates and still processes Bruker candidates.

All extractors share this behavior:

- The output names are `<name>.ms1-trace.parquet` and `<name>.msn-trace.parquet`, where `<name>` keeps the `.raw` or `.d` suffix by default.
- Both levels are selected by default, and an unavailable level is then left out.
- If you select one level and the acquisition does not have it, the extractor raises `ExtractionError`.
- If you select no level, the extractor checks the input and writes nothing.
- Precision `low` writes float32 trace values, and `high` writes float64.
- An existing output with the same name is overwritten.

`tests/unit/test_extractor_contract.py` runs for every extractor, but it only covers a selection without levels and invalid options. Each extractor has its own tests for the other shared behavior.

`BrukerExtractor` reads SQLite tables directly, with these rules:

- It requires a file named `analysis.tdf`, although discovery accepts any `.tdf` name.
- `Frames` must contain `Id`, `Time`, and `MsMsType`. `SummedIntensities` becomes the TIC, and `MaxIntensity` becomes the base peak intensity if they exist.
- `GlobalMetadata.AcquisitionDateTime` is required and must contain a timezone. `AnalysisId` becomes `source_id` if it exists.
- `MsMsType` 0 is MS1, and all other values are MS2. Frames in `DiaFrameMsMsInfo` are also MS2.
- MSn rows have the granularity `frame-aggregate`, because one frame can contain several precursor isolation events.
- We use the native `MaxIntensity` and not the interpolated BPC trace. The BPC trace follows only MS1 frames, so it differs strongly from `MaxIntensity` for MSn frames.
- It does not write a `faims_cv` column, and it does not read the `.tdf_bin` file.

`ThermoExtractor` runs the helper in a temporary folder in the destination, validates the result, and only then moves the files to their final names. A failure therefore leaves no partial output. The default timeout is 600 seconds, and the `cancel` event stops a running helper immediately.

## Trace artifacts

`traces/schema.py` is the source of truth for the schema-v1 contract. `load_trace()`, `write_trace()`, and `validate_trace()` enforce it.

| Column | Status |
|---|---|
| `scan_id`, `retention_time_sec`, `ms_level` | Required, no nulls |
| `total_ion_current`, `base_peak_intensity` | Optional, a null means a failed row |
| `faims_cv` | Optional, either all null or all finite numbers |
| `injection_time_ms`, `base_peak_mz`, `polarity`, `precursor_mz`, `isolation_window_lower_mz`, `isolation_window_upper_mz`, `charge_state`, `collision_energy`, `activation_type` | Reserved, not implemented |

Parquet metadata has required and optional fields:

- **Required:** `schema_version`, `vendor`, `source_filename`, `ms_level_file`, `precision_mode`, and `row_granularity`.
- **Optional:** `generator`, `extracted_at`, `acquisition_start_time`, `source_id`, and `acquisition_path`. `load_trace()` returns `None` for a missing field.

Other rules apply as well:

- Files must use Snappy compression.
- An `ms1` file contains only level 1, and an `msn` file contains only levels 2 and higher.
- `strict=True` rejects reserved and unknown columns. `strict=False` checks the type of known columns and ignores unknown columns.
- `source_filename` is the original raw-file name and does not depend on the output name.

## Processing

`process_traces()` turns artifacts into one `ProcessedTable` for each MS level and FAIMS CV. It sorts rows by retention time, converts the time to minutes, and moves the MS level, the CV, and the provenance into `ProcessedTableMetadata`. It reads only the channels in `_REPORT_CHANNELS` in `process.py`.

The default options select MS levels 1 and 2, so MS3 rows and higher do not reach the report. `FaimsProcessingMode.SPLIT` is the only implemented mode, and `COMBINED` raises `NotImplementedError` for tables with FAIMS values. `minimum_faims_percentage` removes CVs with too few rows.

## Reports

`build_report()` creates a renderer-neutral `ReportDocument`, so that another renderer can reuse it. `render_html()` and `write_html()` take processed tables, call `build_report()`, and then return or write the HTML.

`report/html.py` contains the page template and its JavaScript, and the plots are built in the browser. Python uses Plotly only to embed `plotly.js`. Reports embed it by default, so they work offline, whereas `asset_mode="cdn"` loads it from the Plotly CDN.

Keep this behavior when you change the report:

- **Input:** The report accepts only `ProcessedTable` instances. A non-finite value raises `ReportError`, while a null value stays a gap in the trace.
- **Channels:** All available channels are selected by default. A requested channel that is not available raises `ConfigurationError`.
- **Order:** The default order is `acquisition_start_time`, then `rawfile_name`. Sorting in the **Metadata** tab also controls the order of the plots and the selectors.
- **Colors:** A trace color stays the same for a source, which is identified by `source_id` or else by the raw-file name. Facility red is reserved for the reference trace.
- **Reference:** The reference overrides the color of its trace. Overlay draws it last, so it appears on top, while Pairwise draws it first, so it stays behind the comparison trace. Stacked keeps the sort order.
- **Pairwise:** This view requires a reference and plots it with one comparison trace. The arrow keys move through the traces unless another form field has the keyboard input.
- **Metadata:** `ReportOptions(metadata_fields=...)` selects the fields. `acquisition_path` is available but not shown by default.

## Thermo helper

The helper is a separate program with its own Thermo license, so we do not bundle it. `thermo/specification.py` pins its version and the SHA-256 digest of each archive. It is available upstream for Windows, Linux, and macOS, while rawtrace-qc currently pins only `win-x64`. Windows on Arm uses that build through emulation.

Rawtrace-qc finds the helper in one of two ways:

- A caller can give an explicit path to the executable or to its folder. If this path does not lead to the executable, rawtrace-qc raises `ThermoHelperNotFoundError` and does not use the managed helper instead.
- Without an explicit path, rawtrace-qc uses the managed helper in `<user_data_dir>/tools/thermoscanheaderextractor/<version>/<runtime>/`.

`get_thermo_helper_status()` has no side effects and returns one of these states: `READY`, `NOT_INSTALLED`, `UNLICENSED`, `INVALID_VERSION`, or `UNSUPPORTED_PLATFORM`. It reports an unusable explicit path as `NOT_INSTALLED`. In contrast, `locate_thermo_helper()` returns the executable or raises a specific `ThermoHelperError`.

`install_thermo_helper()` verifies the digest before it extracts the archive, and it installs through a temporary staging folder. It never runs the helper and never accepts the license. It raises an error on a conflicting installation unless the caller passes `overwrite=True`.

The helper is the only authority on the license state:

- A call without arguments exits with code 4 if the terms are not accepted, and with code 1 (usage) if they are. `is_license_accepted()` uses this probe. The order of these checks is an implementation detail of the helper, so re-check it when you change the pin.
- `--thermo-license` prints the terms without accepting them.
- `--agree-to-terms` records acceptance for the current user account. `accept_thermo_license()` returns early if the probe already reports acceptance. Otherwise, it runs this command and confirms the state with the probe.

`ThermoExtractor` keeps exit codes 4 and 5 as setup problems, and it reports other non-zero exit codes and timeouts as `ExtractionError`. Other helper failures, such as an executable that cannot start, stay a `ThermoHelperError`. The helper uses these exit codes:

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Invalid arguments or a failed extraction |
| 2 | Missing input file |
| 3 | The input is not a readable `.raw` file |
| 4 | The license is not accepted |
| 5 | License handling failed |

## CLI

`rawtrace-qc` has the commands `extract` and `thermo` (`status`, `install`, and `accept-license`). Run them with `--help` to see the options. The optional dependency is imported inside `main()`, so a missing Cyclopts gives a clear message with exit code 2.

`extract` prints one entry for each acquisition, then any Thermo setup problems and discovery issues, and finally a summary. Its exit code is 1 if any acquisition did not succeed or if discovery reported any issue. The first case includes Thermo acquisitions that were skipped because the helper was not ready. Acquisitions that discovery skipped do not change the exit code unless they leave an input without candidates.

## GUI

Most Qt code is in `app.py`, `thermo_tool.py`, and `theme.py`. These modules load PySide6 with `import_module` and pass the Qt modules as arguments, so that importing them does not require PySide6. Long tasks run as `QRunnable` workers in the global thread pool.

The other modules hold logic that you can test without Qt:

- `workflow.py` holds the selection state and the reasons for excluding a file.
- `patterns.py` filters candidates by name. Include patterns are combined with OR, and any matching exclude pattern wins.
- `config.py` stores settings in `<user_data_dir>/config.json`.
- `reporting.py` coordinates cached extraction, processing, and report writing.
- `cache.py` stores trace artifacts.

`generate_report()` leaves out a file that fails and continues with the others. It raises `ConfigurationError` only if no file remains. Cancelling keeps finished extractions in the cache and does not exclude the current file.

The GUI always uses the managed helper. While the helper is not ready, all Thermo files are excluded, even if their traces are cached, and they return automatically when the helper becomes ready.

`TraceCache` keeps entries in `<cache_directory>/<major>.<minor>/<key>/`, so that patch releases share entries while other versions extract again. The cache does not delete old folders. The key is the first 16 hexadecimal characters of a SHA-256 digest over these values:

- The cache layout, the resolved source path, the vendor, and the format.
- The extractor class, the precision, and the selected MS levels.
- The size and modification time of the source and, for a folder, of its direct member files.

An entry appears only after the extraction has finished, because `TraceCache` first writes to a staging folder. An entry with an invalid Parquet file counts as a cache miss. Change `_CACHE_LAYOUT` if existing entries must not be used again.

## Common changes

### Add a vendor

1. Add the values to `Vendor` and `FileFormat`, and add a validator to `discovery/policies.py`.
2. Add the validator to the default registration in `discovery/discover.py`.
3. Write an extractor that implements `Extractor` and writes through `write_trace()`.
4. Add it to `create_extractor()`.
5. Add it to the parameters of `tests/unit/test_extractor_contract.py`.
6. Add tests for the other shared behavior in [Extraction](#extraction), because the contract tests do not cover it.

### Add a channel

1. Add the column as implemented in `traces/schema.py`, and let the extractors write it.
2. Add it to `_REPORT_CHANNELS` in `processing/process.py`.
3. Add a display definition to `CHANNEL_SPECS` in `report/channels.py`.

### Change the helper version

1. Update the version, the asset names, and the digests in `thermo/specification.py`.
2. Update the unit tests that contain the old version, which you can find with a search in `tests/unit`.
3. Run the tests with the `network` marker, which compare the pinned digests with the GitHub release.
4. Check that the license probe still behaves as described in [Thermo helper](#thermo-helper).

### Support Thermo files on another platform

Upstream archives exist for Linux and macOS on x64 and arm64, so these steps should be sufficient. We have not tried them yet.

1. Pin the assets in `thermo/specification.py`. The executable has no `.exe` extension on these platforms.
2. Add `.tar.gz` support, because `ArchiveFormat` and the extraction code currently handle only ZIP files.
3. Extend the Thermo install step in `ci.yml`, which currently runs only on Windows.

### Add reports to the CLI

Move `TraceCache` and `generate_report()` from `gui` into `workflows`, because they do not need Qt. `ExclusionReason` and `FileExclusion` must move too, since `reporting.py` uses them. Then call the workflow from a new command in `cli`.

### Add media to the documentation

Media files are on the separate `media` branch in `docs/screenshots/`, so that they do not increase the size of `main`. Name a file `<subject>-v<N>.<ext>`, and never change a published file. Link to it with a full `raw.githubusercontent.com` URL, because PyPI cannot display relative links.

## Known gaps

- FAIMS runs are split by CV, and the combined mode is not implemented.
- MS2 traces are of limited use, and a better presentation is planned.
- `ProcessingOptions` has no channel filter. The report selects the channels.
- Precision is not reduced for compact HTML output.
- The cache key does not contain the helper version, so a helper change within one `major.minor` version reuses existing entries.

## Maintain this document

Update this document in the same change when a public API, a contract, a convention, or a known gap changes. Describe the current behavior only, and put plans in [Known gaps](#known-gaps). Do not insert hard line breaks in Markdown paragraphs.

Before a release, check that the version in `pyproject.toml` and the fallback version in `src/rawtrace_qc/__init__.py` agree.

# rawtrace-qc

`rawtrace-qc` is a Python library for extracting mass-spectrometry scan traces and generating interactive HTML QC reports from vendor raw-file formats.

The library supports Bruker timsTOF `.d` directories with a native Python extractor and Thermo `.raw` files through the separate `ThermoScanHeaderExtractor` helper (currently supported runtimes: `win-x64`; Windows on Arm runs it under x64 emulation). The helper is not bundled; its setup and license acceptance are explicit commands.

The project is being developed library-first. File discovery, extraction, validated Parquet artifacts, trace processing, report generation, and the optional GUI are implemented as clients of the same service layers.

Install the optional command-line interface and inspect Thermo helper setup with:

```bash
uv sync --extra cli
rawtrace-qc thermo status
```

The CLI supports helper installation from the pinned download or a local ZIP, explicit license acceptance, and trace extraction. HTML reports are generated through the library or the GUI. See `documentation.md` for offline setup, shared helper paths, license handling, and upgrade details.

## Development

Install the project and development dependencies with:

```bash
uv sync
```

Run the unit tests, source lint and formatter checks, test formatting check, and type checker with:

```bash
uv run pytest
uv run ruff check src
uv run ruff format --check src
uv run ruff format --check tests
uv run pyrefly check
```

Install the optional PySide6 desktop GUI with:

```bash
uv sync --extra gui
rawtrace-qc-gui
```

Ruff formatting is applied to tests with the separate 120-character test configuration. Test linting is intentionally not enforced.

See `documentation.md` for the project design and current workflows.

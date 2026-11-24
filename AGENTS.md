# Agent instructions for rawtrace-qc

These instructions add to the global agent instructions and take precedence where they conflict. Read `documentation.md` before you change code: it describes the design, the conventions and the behavior that a change must keep.

## Design

- Put behavior in the library. `cli` and `gui` only present results; filesystem traversal, vendor rules, validation and error classification belong in the library, so that all clients behave in the same way.
- Keep the internal imports of the package table in `documentation.md`. The core package must import without Cyclopts and PySide6.
- Do not guess scientific meaning. For example, a Bruker MSn row is a frame aggregate and not one precursor spectrum.
- Do not write code comments, except for something that the code and docstring alone do not explain.

## Thermo license

- Never accept the Thermo license for the user. Only an explicit user action runs `--agree-to-terms`: `accept_thermo_license()`, `rawtrace-qc thermo accept-license` or the GUI's Accept license button.
- Tests must use the real helper for the license flow, including acceptance, but only with `THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR` set to a temporary folder. The test suite sets it for the whole session, so tests never read or change the user's own acceptance file.
- Prefer the real helper to `MockThermoHelper`. Use the mock where the real helper cannot be used, for example in unit tests or for failures it cannot produce on demand.

## Trace contract

- `docs/scan-trace-spec.md` is the contract with ThermoScanHeaderExtractor, and `traces/schema.py` with `validate_trace` is its reference implementation. Change them together. Whether to raise `document_version` is the owner's decision; ask. By convention it goes up once per release when a release is near, and with each change when no release is planned.
- Read, write and validate trace artifacts only through `load_trace`, `write_trace` and `validate_trace`.

## Errors

- Raise a subclass of `RawtraceError` from the `errors` module for an expected failure that clients catch and show to the user, such as an unreadable acquisition, an invalid trace artifact or a helper problem. Use the most specific existing class that fits. If none fits, do not add a new one; report it instead.
- Built-in exceptions such as `ValueError` or `TypeError` are fine for an invalid argument.

## Workflow

- Python conventions and checks: `python-dev` skill. Docstrings: `python-docstrings` skill. Tests: `python-unit-tests` skill.
- Mark tests that need the network with `network`, and check that `uv run pytest -m "not network"` passes.
- Update `documentation.md` in the same change when a public API, a contract, a convention or a known gap changes, and `README.md` when user-facing behavior changes.
- Every user-facing change needs an entry in `CHANGELOG.md` under `[Unreleased]`.
- Use Conventional Commits with a scope where it helps, such as `fix(gui): ...`. Mark a breaking change with `!` after the tag (for example `feat!:`) and start its changelog entry with `**Breaking:**`. Say what callers must change.

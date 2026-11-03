"""Batch raw-acquisition extraction command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from cyclopts import Parameter, validators

from rawtrace_qc.cli.errors import (
    CHECK_THERMO_SETUP,
    print_cli_error,
    thermo_setup_hint,
)
from rawtrace_qc.discovery import DiscoveryOptions
from rawtrace_qc.errors import RawtraceError, ThermoHelperError
from rawtrace_qc.workflows import (
    BatchExtractionOutcome,
    BatchExtractionResult,
    ExtractionOutcomeStatus,
    extract_batch,
)

_BYTES_PER_MB = 1024 * 1024


def extract(
    paths: Annotated[list[Path], Parameter(name="PATH")],
    /,
    *,
    recursive: Annotated[bool, Parameter(negative_bool=(), show_default=False)] = False,
    output_dir: Path | None = None,
    precision: Literal["low", "high"] = "low",
    ms1: Annotated[bool, Parameter(negative_bool=(), show_default=False)] = False,
    msn: Annotated[bool, Parameter(negative_bool=(), show_default=False)] = False,
    min_age_minutes: Annotated[
        float, Parameter(validator=validators.Number(gte=0))
    ] = 0,
    min_size_mb: Annotated[float, Parameter(validator=validators.Number(gte=0))] = 0,
) -> int:
    """Extract scan traces from acquisition paths or directories.

    With neither MS-level flag, both levels are selected. Setting both flags
    also selects both levels.

    Args:
        paths: Acquisition files, folders, or quoted glob patterns.
        recursive: Also scan subfolders.
        output_dir: Write all traces to this folder. By default, traces are
            written beside each acquisition.
        precision: Trace precision: `low` (float32) or `high` (float64).
        ms1: Extract only MS1 traces. By default, both MS1 and MSn are extracted.
        msn: Extract only MSn traces. By default, both MS1 and MSn are extracted.
        min_age_minutes: Skip acquisitions modified less than this many minutes
            ago. `0` turns the check off.
        min_size_mb: Skip acquisitions smaller than this many MB. `0` turns the
            check off.

    Returns:
        Exit code zero only when all candidates succeed and there are no
        discovery issues. Acquisitions skipped by discovery are reported without
        affecting the exit code, unless they leave an input with no candidates.
    """
    select_both_levels = not ms1 and not msn
    try:
        result = extract_batch(
            paths,
            recursive=recursive,
            output_directory=output_dir,
            precision_mode=precision,
            select_ms1=ms1 or select_both_levels,
            select_msn=msn or select_both_levels,
            discovery_options=DiscoveryOptions(
                min_size_bytes=int(min_size_mb * _BYTES_PER_MB),
                min_age_seconds=min_age_minutes * 60,
            ),
        )
    except RawtraceError as error:
        print_cli_error(error)
        return 1

    _print_batch_result(result)
    return result.exit_code


def _print_batch_result(result: BatchExtractionResult) -> None:
    rows = [(skip.path, "skipped", [skip.message]) for skip in result.discovery_skips]
    helper_errors: dict[type[Exception], Exception] = {}
    for outcome in result.outcomes:
        rows.append(
            (outcome.candidate.path, outcome.status.value, _outcome_details(outcome))
        )
        if outcome.error is not None and _is_helper_problem(outcome):
            helper_errors.setdefault(type(outcome.error), outcome.error)

    for path, status, details in sorted(rows, key=lambda row: row[0]):
        print(f"{status}: {path}")
        for detail in details:
            print(f"  {detail}")

    if helper_errors:
        print("Thermo setup:")
        for error in helper_errors.values():
            print(f"  {error}")
            print(f"  {thermo_setup_hint(error) or CHECK_THERMO_SETUP}")

    for issue in result.discovery_issues:
        print(f"{issue.path}: {issue.message}")

    succeeded = sum(
        outcome.status is ExtractionOutcomeStatus.SUCCEEDED
        for outcome in result.outcomes
    )
    skipped = len(result.discovery_skips) + sum(
        outcome.status is ExtractionOutcomeStatus.SKIPPED for outcome in result.outcomes
    )
    failed = sum(
        outcome.status is ExtractionOutcomeStatus.FAILED for outcome in result.outcomes
    )
    print(
        f"Summary: {succeeded} succeeded, {skipped} skipped, {failed} failed, "
        f"{len(result.discovery_issues)} discovery issue(s)."
    )


def _outcome_details(outcome: BatchExtractionOutcome) -> list[str]:
    if _is_helper_problem(outcome):
        return ["Thermo helper is not ready."]
    if outcome.error is not None:
        return [str(outcome.error)]
    if outcome.result is None:
        return []
    details = []
    if outcome.result.ms1_path is not None:
        details.append(f"MS1: {outcome.result.ms1_path}")
    if outcome.result.msn_path is not None:
        details.append(f"MSn: {outcome.result.msn_path}")
    return details


def _is_helper_problem(outcome: BatchExtractionOutcome) -> bool:
    return outcome.status is ExtractionOutcomeStatus.SKIPPED or isinstance(
        outcome.error, ThermoHelperError
    )

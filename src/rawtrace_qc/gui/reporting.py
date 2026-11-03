"""Coordinate cached extraction, processing, and HTML report generation."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from rawtrace_qc.discovery import DiscoveryCandidate, Vendor
from rawtrace_qc.errors import (
    ConfigurationError,
    OperationCancelledError,
    RawtraceError,
)
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.gui.cache import TraceCache
from rawtrace_qc.gui.workflow import ExclusionReason, FileExclusion
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.processing import ProcessedTable, process_traces
from rawtrace_qc.report import ReportOptions, write_html
from rawtrace_qc.traces import load_trace


class ReportStage(StrEnum):
    """Name the consecutive stages of report generation."""

    EXTRACTING = "extracting"
    PROCESSING = "processing"
    WRITING = "writing"


@dataclass(frozen=True, slots=True)
class ReportProgress:
    """Describe the step report generation is about to start.

    `current` counts every file of a stage, including files that end up excluded.
    It is zero for the writing stage, which does not work per file.
    """

    stage: ReportStage
    current: int = 0
    total: int = 0
    file_name: str = ""
    cache_hits: int = 0

    @property
    def message(self) -> str:
        """Return a short status text for this step."""
        if self.stage is ReportStage.EXTRACTING:
            cached = f" ({self.cache_hits} cached)" if self.cache_hits else ""
            return (
                f"Extracting {self.current} of {self.total}{cached}: {self.file_name}"
            )
        if self.stage is ReportStage.PROCESSING:
            return f"Processing traces {self.current} of {self.total}"
        return "Writing report..."


@dataclass(frozen=True, slots=True)
class ExcludedFile:
    """Name a raw file left out of a report and the reason."""

    candidate: DiscoveryCandidate
    exclusion: FileExclusion


class ReportStorageMode(StrEnum):
    """Choose whether a generated report is temporary or retained."""

    TEMPORARY = "temporary"
    PERMANENT = "permanent"


@dataclass(frozen=True, slots=True)
class ReportGenerationOptions:
    """Configure extraction precision, report storage, and HTML options."""

    storage_mode: ReportStorageMode = ReportStorageMode.TEMPORARY
    output_directory: Path | None = None
    output_name: str | None = None
    precision_mode: Literal["low", "high"] = "low"
    report_options: ReportOptions = ReportOptions()

    def __post_init__(self) -> None:
        """Validate report storage and extraction options."""
        try:
            storage_mode = ReportStorageMode(self.storage_mode)
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                f"Report storage_mode {self.storage_mode!r} is invalid; choose "
                "'temporary' or 'permanent'."
            ) from error
        if self.precision_mode not in {"low", "high"}:
            raise ConfigurationError(
                f"Report precision_mode {self.precision_mode!r} must be 'low' "
                "or 'high'."
            )
        if self.output_name is not None and (
            not self.output_name.strip()
            or any(character in self.output_name for character in '\\/:*?"<>|')
        ):
            raise ConfigurationError(
                "Report output_name must be a valid filename without path separators."
            )
        if not isinstance(self.report_options, ReportOptions):
            raise ConfigurationError("report_options must be a ReportOptions instance.")
        object.__setattr__(self, "storage_mode", storage_mode)
        if self.output_directory is not None:
            object.__setattr__(self, "output_directory", Path(self.output_directory))


@dataclass(frozen=True, slots=True)
class ReportGenerationResult:
    """Describe a generated report, its cache use, and the files it contains."""

    output_path: Path
    processed_table_count: int
    cache_hits: int
    included: tuple[DiscoveryCandidate, ...] = ()
    excluded: tuple[ExcludedFile, ...] = ()


class ReportWorkspace:
    """Own temporary report directories until the GUI application closes."""

    def __init__(self) -> None:
        """Create an empty temporary-workspace registry."""
        self._temporary_directories: list[Path] = []

    def create_temporary_directory(self) -> Path:
        """Create and retain one temporary report directory."""
        directory = Path(tempfile.mkdtemp(prefix="rawtrace-qc-report-"))
        self._temporary_directories.append(directory)
        return directory

    def cleanup(self) -> None:
        """Remove temporary report directories owned by this workspace."""
        for directory in self._temporary_directories:
            shutil.rmtree(directory, ignore_errors=True)
        self._temporary_directories.clear()


def generate_report(
    candidates: tuple[DiscoveryCandidate, ...],
    cache: TraceCache,
    *,
    options: ReportGenerationOptions | None = None,
    workspace: ReportWorkspace | None = None,
    on_progress: Callable[[ReportProgress], None] | None = None,
    on_excluded: Callable[[ExcludedFile], None] | None = None,
    cancel: threading.Event | None = None,
) -> ReportGenerationResult:
    """Extract active candidates and write one combined HTML report.

    Bruker and Thermo candidates use their library extractors and the same cache.
    Thermo extraction only locates and runs an installed, licensed helper; it
    never installs the helper or accepts its license.

    A file that cannot be extracted or processed is left out and the
    report continues with the remaining files. Cancelling keeps finished
    extractions in the cache and does not exclude the file being worked on.

    Args:
        candidates: Active, validated raw acquisitions in report order.
        cache: Trace cache used for vendor extraction.
        options: Report and extraction settings. Defaults to a temporary,
            embedded-Plotly report using low precision.
        workspace: Temporary-directory owner. Required only when callers need
            temporary reports to remain available after this function returns.
        on_progress: Optional callback that receives each step before it
            starts. Called on the thread running this function. Defaults to None.
        on_excluded: Optional callback that receives each file as soon as it is
            left out. Called on the thread running this function. Defaults to
            None.
        cancel: Optional event that stops generation when set from another
            thread. A running Thermo helper is stopped immediately; other work
            stops at the next file. Defaults to None.

    Returns:
        The generated report path, processed table count, cache hits, and the
        files included in and excluded from the report.

    Raises:
        ConfigurationError: If no candidates are active or no file could be
            used for the report.
        OperationCancelledError: If `cancel` was set.
    """
    selected_options = options or ReportGenerationOptions()
    selected_candidates = tuple(candidates)
    if not selected_candidates:
        raise ConfigurationError(
            "Select at least one valid raw file before generating a report."
        )

    excluded: list[ExcludedFile] = []

    def report(progress: ReportProgress) -> None:
        if cancel is not None and cancel.is_set():
            raise OperationCancelledError("Report generation was cancelled.")
        if on_progress is not None:
            on_progress(progress)

    def exclude(
        candidate: DiscoveryCandidate, reason: ExclusionReason, detail: str
    ) -> None:
        file = ExcludedFile(candidate, FileExclusion(reason, detail))
        excluded.append(file)
        if on_excluded is not None:
            on_excluded(file)

    extractions: list[tuple[DiscoveryCandidate, ExtractionResult]] = []
    cache_hits = 0
    total = len(selected_candidates)
    for index, candidate in enumerate(selected_candidates, start=1):
        report(
            ReportProgress(
                ReportStage.EXTRACTING, index, total, candidate.path.name, cache_hits
            )
        )
        try:
            cached = cache.extract(
                candidate,
                _extractor_for(candidate, cancel),
                precision_mode=selected_options.precision_mode,
            )
        except OperationCancelledError:
            raise
        except Exception as error:
            exclude(candidate, ExclusionReason.EXTRACTION_FAILED, _error_detail(error))
            continue
        cache_hits += int(cached.cache_hit)
        extractions.append((candidate, cached.extraction))

    included: list[DiscoveryCandidate] = []
    processed: list[ProcessedTable] = []
    total = len(extractions)
    for index, (candidate, extraction) in enumerate(extractions, start=1):
        report(
            ReportProgress(ReportStage.PROCESSING, index, total, candidate.path.name)
        )
        try:
            tables = process_traces(
                [
                    load_trace(path)
                    for path in (extraction.ms1_path, extraction.msn_path)
                    if path is not None
                ]
            )
        except Exception as error:
            exclude(candidate, ExclusionReason.PROCESSING_FAILED, _error_detail(error))
            continue
        if not tables:
            exclude(
                candidate,
                ExclusionReason.PROCESSING_FAILED,
                "The file contains no MS1 or MS2 scans.",
            )
            continue
        included.append(candidate)
        processed.extend(tables)

    if not processed:
        raise ConfigurationError(
            f"None of the {len(selected_candidates)} selected file(s) could be "
            "used. Check why each one was excluded and select other files."
        )

    report(ReportProgress(ReportStage.WRITING))
    output_directory = _output_directory(selected_options, workspace)
    output_path = output_directory / _output_name(selected_options)
    write_html(processed, output_path, options=selected_options.report_options)
    return ReportGenerationResult(
        output_path, len(processed), cache_hits, tuple(included), tuple(excluded)
    )


def _error_detail(error: Exception) -> str:
    if isinstance(error, RawtraceError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _extractor_for(
    candidate: DiscoveryCandidate, cancel: threading.Event | None
) -> BrukerExtractor | ThermoExtractor:
    if candidate.vendor == Vendor.BRUKER:
        return BrukerExtractor()
    if candidate.vendor == Vendor.THERMO:
        return ThermoExtractor(cancel=cancel)
    raise ConfigurationError(
        f"No GUI extractor is registered for vendor {candidate.vendor!r}."
    )


def _output_directory(
    options: ReportGenerationOptions,
    workspace: ReportWorkspace | None,
) -> Path:
    if options.storage_mode is ReportStorageMode.PERMANENT:
        directory = options.output_directory or Path.home() / "rawtrace-qc-reports"
    else:
        if workspace is None:
            workspace = ReportWorkspace()
        directory = workspace.create_temporary_directory()
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _output_name(options: ReportGenerationOptions) -> str:
    if options.output_name is not None:
        return options.output_name
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"rawtrace-qc-{timestamp}.html"

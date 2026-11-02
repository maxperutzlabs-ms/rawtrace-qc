"""Coordinate cached extraction, processing, and HTML report generation."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from rawtrace_qc.discovery import DiscoveryCandidate, Vendor
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.gui.cache import TraceCache
from rawtrace_qc.processing import process_traces
from rawtrace_qc.report import ReportOptions, write_html
from rawtrace_qc.traces import load_trace


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
    """Describe a generated report and the cache entries used to create it."""

    output_path: Path
    processed_table_count: int
    cache_hits: int


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
) -> ReportGenerationResult:
    """Extract active candidates and write one combined HTML report.

    Bruker and Thermo candidates use their library extractors and the same cache.
    Thermo extraction only locates and runs an installed, licensed helper; it
    never installs the helper or accepts its license.

    Args:
        candidates: Active, validated raw acquisitions in report order.
        cache: Trace cache used for vendor extraction.
        options: Report and extraction settings. Defaults to a temporary,
            embedded-Plotly report using low precision.
        workspace: Temporary-directory owner. Required only when callers need
            temporary reports to remain available after this function returns.

    Returns:
        The generated report path, processed table count, and cache hits.

    Raises:
        ConfigurationError: If no candidates are active, a vendor is not
            supported, or extraction produces no reportable artifacts.
    """
    selected_options = options or ReportGenerationOptions()
    selected_candidates = tuple(candidates)
    if not selected_candidates:
        raise ConfigurationError(
            "Select at least one valid raw file before generating a report."
        )

    artifacts = []
    cache_hits = 0
    for candidate in selected_candidates:
        if candidate.vendor == Vendor.BRUKER:
            extractor = BrukerExtractor()
        elif candidate.vendor == Vendor.THERMO:
            extractor = ThermoExtractor()
        else:
            raise ConfigurationError(
                f"No GUI extractor is registered for vendor {candidate.vendor!r}."
            )

        cached = cache.extract(
            candidate,
            extractor,
            precision_mode=selected_options.precision_mode,
        )
        cache_hits += int(cached.cache_hit)
        artifacts.extend(
            load_trace(path)
            for path in (cached.extraction.ms1_path, cached.extraction.msn_path)
            if path is not None
        )

    if not artifacts:
        raise ConfigurationError(
            "The selected acquisitions produced no scan-trace artifacts."
        )
    processed = process_traces(artifacts)
    if not processed:
        raise ConfigurationError(
            "The selected trace artifacts contain no reportable rows."
        )

    output_directory = _output_directory(selected_options, workspace)
    output_path = output_directory / _output_name(selected_options)
    write_html(processed, output_path, options=selected_options.report_options)
    return ReportGenerationResult(output_path, len(processed), cache_hits)


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

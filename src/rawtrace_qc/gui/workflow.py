"""Pure selection workflow used by the rawtrace-qc desktop interface."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from rawtrace_qc.discovery import (
    DiscoveryCandidate,
    DiscoveryOptions,
    SkippedAcquisition,
    Vendor,
    inspect_path,
)
from rawtrace_qc.gui.config import GuiSettings
from rawtrace_qc.gui.patterns import FilenamePattern, filter_candidates

THERMO_SETUP_STEP = (
    "Set it up with the Thermo Tool button in the window header. "
    "The file returns automatically."
)


class ExclusionReason(StrEnum):
    """Name why a selected raw file cannot be part of a report."""

    THERMO_NOT_READY = "Thermo tool not ready"
    THERMO_UNSUPPORTED = "Thermo not supported"
    EXTRACTION_FAILED = "Extraction failed"
    PROCESSING_FAILED = "Processing failed"


@dataclass(frozen=True, slots=True)
class FileExclusion:
    """Store why a selected raw file is excluded, with the underlying message."""

    reason: ExclusionReason
    detail: str = ""

    @property
    def caused_by_thermo_tool(self) -> bool:
        """Return whether this exclusion follows from the Thermo helper state."""
        return self.reason in {
            ExclusionReason.THERMO_NOT_READY,
            ExclusionReason.THERMO_UNSUPPORTED,
        }

    @property
    def next_step(self) -> str:
        """Return what the user can do about this exclusion."""
        if self.reason is ExclusionReason.THERMO_NOT_READY:
            return THERMO_SETUP_STEP
        if self.reason is ExclusionReason.THERMO_UNSUPPORTED:
            return "Thermo .raw files cannot be read on this system."
        return "Remove the file and add it again to retry."


@dataclass(frozen=True, slots=True)
class PathValidationResult:
    """Store paths accepted or rejected while populating the selection.

    `rejected` holds every path that was not accepted. `skipped` holds the
    reasons for those rejected paths that are recognized acquisitions.
    """

    accepted: tuple[DiscoveryCandidate, ...] = ()
    rejected: tuple[Path, ...] = ()
    skipped: tuple[SkippedAcquisition, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    """Store one candidate's filter state and current active checkbox state."""

    candidate: DiscoveryCandidate
    included: bool
    active: bool
    matched_pattern_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedEntry:
    """Store one unique selected raw file and its report state.

    An excluded entry never takes part in a report, whatever its `active` state.
    """

    candidate: DiscoveryCandidate
    active: bool = True
    exclusion: FileExclusion | None = None


class RawFileSelection:
    """Manage discovered candidates and unique report input selections."""

    def __init__(self, options: DiscoveryOptions | None = None) -> None:
        """Create an empty selection using the supplied discovery options."""
        self.options = options or GuiSettings().discovery_options()
        self._candidate_entries: tuple[CandidateEntry, ...] = ()
        self._candidate_paths: tuple[DiscoveryCandidate, ...] = ()
        self._patterns: tuple[FilenamePattern, ...] = ()
        self._selected: dict[str, SelectedEntry] = {}
        self._thermo_exclusion: FileExclusion | None = None

    @property
    def candidates(self) -> tuple[CandidateEntry, ...]:
        """Return candidates in active-first display order."""
        return self._candidate_entries

    @property
    def selected(self) -> tuple[SelectedEntry, ...]:
        """Return unique selected entries in insertion order."""
        return tuple(self._selected.values())

    def set_candidates(
        self,
        candidates: tuple[DiscoveryCandidate, ...],
    ) -> tuple[CandidateEntry, ...]:
        """Replace the candidate list and apply the current filename patterns."""
        unique: dict[str, DiscoveryCandidate] = {}
        for candidate in candidates:
            unique.setdefault(_path_key(candidate.path), candidate)
        self._candidate_paths = tuple(unique.values())
        return self.apply_patterns(self._patterns)

    def apply_patterns(
        self,
        patterns: tuple[FilenamePattern, ...],
    ) -> tuple[CandidateEntry, ...]:
        """Reclassify candidates and activate all currently included entries."""
        self._patterns = tuple(patterns)
        filtered = filter_candidates(self._candidate_paths, self._patterns)
        self._candidate_entries = tuple(
            CandidateEntry(
                item.candidate,
                item.included,
                item.included,
                item.matched_pattern_names,
            )
            for item in filtered
        )
        return self._candidate_entries

    def set_candidate_active(self, path: Path, active: bool) -> None:
        """Set the candidate checkbox state for one included path."""
        key = _path_key(path)
        self._candidate_entries = tuple(
            CandidateEntry(
                item.candidate,
                item.included,
                (
                    active
                    if _path_key(item.candidate.path) == key and item.included
                    else item.active
                ),
                item.matched_pattern_names,
            )
            for item in self._candidate_entries
        )

    def promote_active_candidates(self) -> tuple[SelectedEntry, ...]:
        """Add checked, included candidates to the unique selected list."""
        additions = tuple(
            item.candidate
            for item in self._candidate_entries
            if item.included and item.active
        )
        self._add_candidates(additions)
        return self.selected

    def add_paths(self, paths: tuple[Path, ...]) -> PathValidationResult:
        """Validate and add file-dialog or drag-and-drop paths uniquely."""
        accepted: list[DiscoveryCandidate] = []
        rejected: list[Path] = []
        skipped: list[SkippedAcquisition] = []
        for path in paths:
            candidate, skip = inspect_path(path, self.options)
            if candidate is None:
                rejected.append(Path(path).expanduser().resolve())
                if skip is not None:
                    skipped.append(skip)
            else:
                accepted.append(candidate)
        self._add_candidates(tuple(accepted))
        return PathValidationResult(tuple(accepted), tuple(rejected), tuple(skipped))

    def remove_selected(self, paths: tuple[Path, ...]) -> None:
        """Remove selected-list entries matching `paths`.

        Adding a removed file again gives it a fresh start, which is how a file
        excluded by a failed extraction can be retried.
        """
        for path in paths:
            self._selected.pop(_path_key(path), None)

    def set_selected_active(self, path: Path, active: bool) -> None:
        """Set whether one selected raw file participates in report generation."""
        key = _path_key(path)
        item = self._selected.get(key)
        if item is not None and item.exclusion is None:
            self._selected[key] = replace(item, active=active)

    def set_all_selected_active(self, active: bool) -> None:
        """Set the report-active state for every selected raw file not excluded."""
        self._selected = {
            key: item if item.exclusion is not None else replace(item, active=active)
            for key, item in self._selected.items()
        }

    def active_selected(self) -> tuple[DiscoveryCandidate, ...]:
        """Return selected candidates that will take part in the next report."""
        return tuple(
            item.candidate
            for item in self._selected.values()
            if item.active and item.exclusion is None
        )

    def excluded_selected(self) -> tuple[SelectedEntry, ...]:
        """Return selected entries that are excluded from reports."""
        return tuple(
            item for item in self._selected.values() if item.exclusion is not None
        )

    def exclude(self, path: Path, exclusion: FileExclusion) -> None:
        """Exclude one selected raw file from reports until it is added again.

        A path that is no longer selected is ignored, because the user can
        remove files while a report is running.

        Args:
            path: Path of the selected raw file.
            exclusion: Why the file cannot be used.
        """
        key = _path_key(path)
        item = self._selected.get(key)
        if item is not None:
            self._selected[key] = replace(item, exclusion=exclusion)

    @property
    def thermo_exclusion(self) -> FileExclusion | None:
        """Return the exclusion applied to Thermo files, or None if they can be used."""
        return self._thermo_exclusion

    def set_thermo_ready(
        self, ready: bool, detail: str = "", *, supported: bool = True
    ) -> int:
        """Exclude or restore Thermo files according to the helper state.

        While the helper is not ready, every selected Thermo file is excluded,
        including files added later. Once it is ready, those files return with
        their previous checkbox state. Files excluded for other reasons stay
        excluded.

        Args:
            ready: Whether the Thermo helper can be used.
            detail: Message explaining why the helper is not ready.
            supported: If True (default), the user can set up the helper on this
                system. Otherwise the exclusion says that it cannot be resolved.

        Returns:
            The number of files that were newly excluded or restored.
        """
        reason = (
            ExclusionReason.THERMO_NOT_READY
            if supported
            else ExclusionReason.THERMO_UNSUPPORTED
        )
        self._thermo_exclusion = None if ready else FileExclusion(reason, detail)
        changed = 0
        for key, item in self._selected.items():
            excluded_by_thermo = (
                item.exclusion is not None and item.exclusion.caused_by_thermo_tool
            )
            if ready and excluded_by_thermo:
                self._selected[key] = replace(item, exclusion=None)
                changed += 1
            elif (
                not ready
                and item.candidate.vendor == Vendor.THERMO
                and (item.exclusion is None or excluded_by_thermo)
            ):
                self._selected[key] = replace(item, exclusion=self._thermo_exclusion)
                changed += int(item.exclusion is None)
        return changed

    def _add_candidates(self, candidates: tuple[DiscoveryCandidate, ...]) -> None:
        for candidate in candidates:
            self._selected.setdefault(
                _path_key(candidate.path),
                SelectedEntry(
                    candidate,
                    exclusion=(
                        self._thermo_exclusion
                        if candidate.vendor == Vendor.THERMO
                        else None
                    ),
                ),
            )


def _path_key(path: Path) -> str:
    return os.path.normcase(Path(path).expanduser().resolve())

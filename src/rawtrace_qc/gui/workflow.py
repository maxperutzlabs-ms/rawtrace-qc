"""Pure selection workflow used by the rawtrace-qc desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rawtrace_qc.discovery import (
    DiscoveryCandidate,
    DiscoveryOptions,
    DiscoveryResult,
    discover,
    validate_path,
)
from rawtrace_qc.gui.config import GuiSettings
from rawtrace_qc.gui.patterns import FilenamePattern, filter_candidates


@dataclass(frozen=True, slots=True)
class PathValidationResult:
    """Store paths accepted or rejected while populating the selection."""

    accepted: tuple[DiscoveryCandidate, ...] = ()
    rejected: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateEntry:
    """Store one candidate's filter state and current active checkbox state."""

    candidate: DiscoveryCandidate
    included: bool
    active: bool
    matched_pattern_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedEntry:
    """Store one unique selected raw file and its report-active state."""

    candidate: DiscoveryCandidate
    active: bool = True


class RawFileSelection:
    """Manage discovered candidates and unique report input selections."""

    def __init__(self, options: DiscoveryOptions | None = None) -> None:
        """Create an empty selection using the supplied discovery options."""
        self.options = options or GuiSettings().discovery_options()
        self._candidate_entries: tuple[CandidateEntry, ...] = ()
        self._candidate_paths: tuple[DiscoveryCandidate, ...] = ()
        self._patterns: tuple[FilenamePattern, ...] = ()
        self._selected: dict[str, SelectedEntry] = {}
        self._issues = ()

    @property
    def candidates(self) -> tuple[CandidateEntry, ...]:
        """Return candidates in active-first display order."""
        return self._candidate_entries

    @property
    def selected(self) -> tuple[SelectedEntry, ...]:
        """Return unique selected entries in insertion order."""
        return tuple(self._selected.values())

    @property
    def issues(self):
        """Return traversal issues from the most recent folder discovery."""
        return self._issues

    def discover_folder(self, source: Path) -> DiscoveryResult:
        """Replace candidates with valid acquisitions found below `source`."""
        result = discover(source, self.options)
        self._issues = result.issues
        self.set_candidates(result.candidates)
        return result

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
        for path in paths:
            candidate = validate_path(path, self.options)
            if candidate is None:
                rejected.append(Path(path).expanduser().resolve())
            else:
                accepted.append(candidate)
        self._add_candidates(tuple(accepted))
        return PathValidationResult(tuple(accepted), tuple(rejected))

    def remove_selected(self, paths: tuple[Path, ...]) -> None:
        """Remove selected-list entries matching `paths`."""
        for path in paths:
            self._selected.pop(_path_key(path), None)

    def set_selected_active(self, path: Path, active: bool) -> None:
        """Set whether one selected raw file participates in report generation."""
        key = _path_key(path)
        item = self._selected.get(key)
        if item is not None:
            self._selected[key] = SelectedEntry(item.candidate, active)

    def set_all_selected_active(self, active: bool) -> None:
        """Set the report-active state for every selected raw file."""
        self._selected = {
            key: SelectedEntry(item.candidate, active)
            for key, item in self._selected.items()
        }

    def active_selected(self) -> tuple[DiscoveryCandidate, ...]:
        """Return selected candidates whose report checkbox is active."""
        return tuple(item.candidate for item in self._selected.values() if item.active)

    def _add_candidates(self, candidates: tuple[DiscoveryCandidate, ...]) -> None:
        for candidate in candidates:
            self._selected.setdefault(
                _path_key(candidate.path),
                SelectedEntry(candidate),
            )


def _path_key(path: Path) -> str:
    return str(Path(path).expanduser().resolve()).casefold()

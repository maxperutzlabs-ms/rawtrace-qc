"""Typed models used by the vendor-aware discovery workflow."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rawtrace_qc.errors import ConfigurationError


class DiscoveryScope(StrEnum):
    """Select whether discovery examines direct children or descendants."""

    DIRECT = "direct"
    RECURSIVE = "recursive"


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    """Describe an input-resolution or filesystem traversal problem."""

    path: Path
    message: str
    code: str | None = None


@dataclass(frozen=True, slots=True, init=False)
class TraversalIssue(DiscoveryIssue):
    """Describe a filesystem problem encountered below the source directory."""

    def __init__(self, path: Path, code: str, message: str) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class TraversalTree:
    """Store accessible entries and issues found during filesystem traversal."""

    files: tuple[Path, ...] = ()
    directories: tuple[Path, ...] = ()
    issues: tuple[TraversalIssue, ...] = ()


class SkipReason(StrEnum):
    """Explain why a recognized acquisition is not a candidate."""

    TOO_SMALL = "too_small"
    TOO_RECENT = "too_recent"
    INCOMPLETE = "incomplete"
    INACCESSIBLE = "inaccessible"


@dataclass(frozen=True, slots=True)
class SkippedAcquisition:
    """Describe a recognized acquisition that discovery did not accept."""

    path: Path
    reason: SkipReason
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Return the paths a vendor validator accepted and skipped."""

    valid: tuple[Path, ...] = ()
    skipped: tuple[SkippedAcquisition, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    """Describe a valid acquisition identified by a vendor detector."""

    path: Path
    vendor: str
    format: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Return valid candidates, non-fatal issues, and skipped acquisitions."""

    candidates: tuple[DiscoveryCandidate, ...] = ()
    issues: tuple[DiscoveryIssue, ...] = ()
    skipped: tuple[SkippedAcquisition, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryOptions:
    """Configure traversal scope, vendor selection, validation thresholds, and time."""

    scope: DiscoveryScope = DiscoveryScope.DIRECT
    vendors: frozenset[str] | None = None
    min_size_bytes: int = 1024 * 1024
    min_age_seconds: float = 120
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        """Reject invalid vendor filters and negative thresholds."""
        if self.vendors is not None and any(
            not isinstance(vendor, str) or not vendor.strip() for vendor in self.vendors
        ):
            raise ConfigurationError("Vendor filters must contain non-empty strings.")
        if self.min_size_bytes < 0:
            raise ConfigurationError(
                f"Minimum size {self.min_size_bytes!r} must be non-negative."
            )
        if self.min_age_seconds < 0:
            raise ConfigurationError(
                f"Minimum age {self.min_age_seconds!r} must be non-negative."
            )

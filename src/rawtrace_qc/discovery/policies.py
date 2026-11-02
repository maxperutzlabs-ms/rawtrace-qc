"""Vendor-specific completeness checks for discovered filesystem entries."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from rawtrace_qc.discovery.models import (
    SkippedAcquisition,
    SkipReason,
    TraversalTree,
    ValidationResult,
)


class Vendor(StrEnum):
    """Identify a supported raw-file vendor."""

    BRUKER = "bruker"
    THERMO = "thermo"


class FileFormat(StrEnum):
    """Identify a supported raw-file extension or directory format."""

    D = "d"
    RAW = "raw"


def validate_thermo(
    tree: TraversalTree,
    min_size_bytes: int,
    min_age_seconds: float,
    now: float,
) -> ValidationResult:
    """Separate complete Thermo `.raw` files from skipped ones.

    Args:
        tree: Files and directories found by generic traversal.
        min_size_bytes: Minimum accepted file size in bytes. `0` disables the
            size check.
        min_age_seconds: Minimum time since modification in seconds. `0`
            disables the age check.
        now: Current Unix timestamp used for the age check.

    Returns:
        Sufficiently large and old `.raw` files, and the remaining `.raw` files
        with the reason they were skipped.
    """
    valid: list[Path] = []
    skipped: list[SkippedAcquisition] = []
    for path in tree.files:
        if path.suffix.casefold() != ".raw":
            continue
        try:
            metadata = os.stat(path, follow_symlinks=False)
        except OSError as error:
            skipped.append(_inaccessible(path, error))
            continue
        skip = _threshold_skip(path, metadata, min_size_bytes, min_age_seconds, now)
        if skip is None:
            valid.append(path)
        else:
            skipped.append(skip)
    return ValidationResult(tuple(valid), tuple(skipped))


def validate_bruker(
    tree: TraversalTree,
    min_size_bytes: int,
    min_age_seconds: float,
    now: float,
) -> ValidationResult:
    """Separate complete Bruker `.d` directories from skipped ones.

    A `.d` directory without any `.tdf` or `.tdf_bin` member is not a Bruker
    acquisition and is neither accepted nor reported.

    Args:
        tree: Files and directories found by generic traversal.
        min_size_bytes: Minimum accepted `.tdf_bin` size in bytes. `0` disables
            the size check.
        min_age_seconds: Minimum time since `.tdf_bin` modification in seconds.
            `0` disables the age check.
        now: Current Unix timestamp used for the age check.

    Returns:
        Directories containing a non-empty `.tdf` and a complete `.tdf_bin`, and
        the remaining Bruker directories with the reason they were skipped.
    """
    valid: list[Path] = []
    skipped: list[SkippedAcquisition] = []
    for path in tree.directories:
        if path.suffix.casefold() != ".d":
            continue
        try:
            tdf_members, tdf_bin_members = _bruker_members(path)
        except OSError as error:
            skipped.append(_inaccessible(path, error))
            continue
        if not tdf_members and not tdf_bin_members:
            continue
        if not any(metadata.st_size > 0 for metadata in tdf_members):
            skipped.append(
                SkippedAcquisition(
                    path, SkipReason.INCOMPLETE, "No non-empty .tdf file was found."
                )
            )
            continue
        if not tdf_bin_members:
            skipped.append(
                SkippedAcquisition(
                    path, SkipReason.INCOMPLETE, "No .tdf_bin file was found."
                )
            )
            continue
        member_skips = [
            _threshold_skip(path, metadata, min_size_bytes, min_age_seconds, now)
            for metadata in tdf_bin_members
        ]
        if None in member_skips:
            valid.append(path)
        else:
            skipped.append(next(skip for skip in member_skips if skip is not None))
    return ValidationResult(tuple(valid), tuple(skipped))


def _bruker_members(path: Path) -> tuple[list[os.stat_result], list[os.stat_result]]:
    tdf_members: list[os.stat_result] = []
    tdf_bin_members: list[os.stat_result] = []
    with os.scandir(path) as scan:
        for member in scan:
            if member.is_symlink() or not member.is_file(follow_symlinks=False):
                continue
            name = member.name.casefold()
            if name.endswith(".tdf"):
                members = tdf_members
            elif name.endswith(".tdf_bin"):
                members = tdf_bin_members
            else:
                continue
            members.append(os.stat(member.path, follow_symlinks=False))
    return tdf_members, tdf_bin_members


def _threshold_skip(
    path: Path,
    metadata: os.stat_result,
    min_size_bytes: int,
    min_age_seconds: float,
    now: float,
) -> SkippedAcquisition | None:
    age_seconds = now - metadata.st_mtime
    if min_age_seconds and age_seconds < min_age_seconds:
        modified = (
            f"Modified {_format_elapsed(age_seconds)} ago"
            if age_seconds >= 0
            else "Modified time is in the future"
        )
        minimum = _format_minimum_age(min_age_seconds)
        return SkippedAcquisition(
            path, SkipReason.TOO_RECENT, f"{modified} (minimum {minimum})."
        )
    if metadata.st_size < min_size_bytes:
        size = _format_megabytes(metadata.st_size)
        minimum = _format_megabytes(min_size_bytes)
        return SkippedAcquisition(
            path, SkipReason.TOO_SMALL, f"Size is {size} (minimum {minimum})."
        )
    return None


def _inaccessible(path: Path, error: OSError) -> SkippedAcquisition:
    return SkippedAcquisition(
        path, SkipReason.INACCESSIBLE, f"Cannot inspect: {error.strerror or error}."
    )


def _format_elapsed(seconds: float) -> str:
    if seconds < 120:
        return f"{int(seconds)} s"
    return f"{int(seconds // 60)} min"


def _format_minimum_age(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:g} s"
    return f"{seconds / 60:g} min"


def _format_megabytes(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.2f} MB"

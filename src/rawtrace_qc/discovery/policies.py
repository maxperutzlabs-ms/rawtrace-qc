"""Vendor-specific completeness checks for discovered filesystem entries."""

from __future__ import annotations

import os
import stat
from enum import StrEnum
from pathlib import Path

from rawtrace_qc.discovery.models import TraversalTree


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
) -> tuple[Path, ...]:
    """Return complete Thermo `.raw` files from a traversal tree.

    Args:
        tree: Files and directories found by generic traversal.
        min_size_bytes: Minimum accepted file size in bytes.
        min_age_seconds: Minimum time since modification in seconds.
        now: Current Unix timestamp used for the age check.

    Returns:
        Regular, sufficiently large, and sufficiently old `.raw` files.
    """
    return tuple(
        path
        for path in tree.files
        if path.suffix.casefold() == ".raw"
        and _valid_file(path, min_size_bytes, min_age_seconds, now)
    )


def validate_bruker(
    tree: TraversalTree,
    min_size_bytes: int,
    min_age_seconds: float,
    now: float,
) -> tuple[Path, ...]:
    """Return complete Bruker `.d` directories from a traversal tree.

    Args:
        tree: Files and directories found by generic traversal.
        min_size_bytes: Minimum accepted `.tdf_bin` size in bytes.
        min_age_seconds: Minimum time since `.tdf_bin` modification in seconds.
        now: Current Unix timestamp used for the age check.

    Returns:
        Directories containing a non-empty `.tdf` and a complete `.tdf_bin`.
    """
    return tuple(
        path
        for path in tree.directories
        if path.suffix.casefold() == ".d"
        and _valid_bruker_directory(path, min_size_bytes, min_age_seconds, now)
    )


def _valid_file(
    path: Path, min_size_bytes: int, min_age_seconds: float, now: float
) -> bool:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_size > 0
        and metadata.st_size >= min_size_bytes
        and _meets_age_threshold(metadata.st_mtime, min_age_seconds, now)
    )


def _meets_age_threshold(
    modified_at: float, min_age_seconds: float, now: float
) -> bool:
    return min_age_seconds == 0 or now - modified_at >= min_age_seconds


def _valid_bruker_directory(
    path: Path, min_size_bytes: int, min_age_seconds: float, now: float
) -> bool:
    try:
        metadata = os.stat(path, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode):
            return False
        with os.scandir(path) as scan:
            members = tuple(scan)
    except OSError:
        return False

    has_tdf = False
    has_complete_tdf_bin = False
    for member in members:
        try:
            if member.is_symlink() or not member.is_file(follow_symlinks=False):
                continue
            member_metadata = os.stat(member.path, follow_symlinks=False)
        except OSError:
            continue
        suffix = member.name.casefold()
        if suffix.endswith(".tdf"):
            has_tdf = has_tdf or member_metadata.st_size > 0
        elif suffix.endswith(".tdf_bin"):
            has_complete_tdf_bin = has_complete_tdf_bin or (
                member_metadata.st_size > 0
                and member_metadata.st_size >= min_size_bytes
                and _meets_age_threshold(member_metadata.st_mtime, min_age_seconds, now)
            )
    return has_tdf and has_complete_tdf_bin

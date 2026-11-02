"""Implement generic traversal and vendor-aware candidate discovery."""

from __future__ import annotations

import glob
import os
import stat
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from rawtrace_qc.discovery.models import (
    DiscoveryCandidate,
    DiscoveryIssue,
    DiscoveryOptions,
    DiscoveryResult,
    DiscoveryScope,
    SkippedAcquisition,
    TraversalIssue,
    TraversalTree,
)
from rawtrace_qc.discovery.policies import (
    FileFormat,
    Vendor,
    validate_bruker,
    validate_thermo,
)
from rawtrace_qc.discovery.registry import DiscoveryRegistry
from rawtrace_qc.errors import ConfigurationError, DiscoveryError


def discover_inputs(
    inputs: Iterable[str | os.PathLike[str]],
    options: DiscoveryOptions | None = None,
    registry: DiscoveryRegistry | None = None,
) -> DiscoveryResult:
    """Resolve paths and glob patterns, then discover supported acquisitions.

    Each input is expanded independently of the discovery scope. Glob patterns
    support `*`, `?`, character classes, and recursive `**`. Each matching path
    is first validated as a complete acquisition; paths that are not
    acquisitions are scanned only when they are directories. An input that
    yields no candidates produces one `no_ready_candidates` issue when
    acquisitions were skipped and one `no_candidates` issue otherwise, unless it
    already has another issue or lies below a root traversed for a different
    input. A skipped acquisition is not scanned as a directory. Candidates and
    skipped acquisitions found through multiple inputs are included once. In
    recursive scope, supplied directories are processed ancestor-first, and
    nested directories beneath a traversed input root are not traversed
    repeatedly.

    All non-fatal input-resolution and traversal issues are returned.

    Examples:
        ```python
        from rawtrace_qc.discovery import DiscoveryOptions, DiscoveryScope
        from rawtrace_qc.discovery import discover_inputs

        result = discover_inputs(
            ["/data/**/*.raw", "/data/run.d"],
            DiscoveryOptions(scope=DiscoveryScope.RECURSIVE),
        )
        ```

    Args:
        inputs: Acquisition paths, directories, or glob patterns to resolve.
        options: Discovery configuration. If None (default), uses direct
            discovery, all built-in vendors, default thresholds, and the system
            clock.
        registry: Validator registry. If None (default), uses Bruker and Thermo.

    Returns:
        Deduplicated valid candidates, skipped acquisitions, and non-fatal input
        or traversal issues.

    Raises:
        ConfigurationError: If no input paths are supplied.
    """
    normalized_inputs = tuple(Path(path).expanduser().absolute() for path in inputs)
    if not normalized_inputs:
        raise ConfigurationError("At least one input path is required.")

    selected = options or DiscoveryOptions()
    input_discoveries = _resolve_inputs(normalized_inputs, selected, registry)
    _discover_resolved_directories(input_discoveries, selected, registry)
    return _build_discovery_result(input_discoveries)


def resolve_input_path_pattern(input_path: str | os.PathLike[str]) -> list[Path]:
    """Return existing paths matched by a literal path or glob pattern.

    Glob patterns support `*`, `?`, character classes, and recursive `**`.
    This function resolves filesystem paths only and does not validate
    acquisition formats.

    Args:
        input_path: File path, directory path, or glob pattern to resolve.

    Returns:
        Matching existing paths as absolute `Path` objects, or an empty list
        when the path does not exist or the pattern has no matches.
    """
    normalized_path = Path(input_path).expanduser().absolute()
    pattern = os.fspath(normalized_path)
    if not glob.has_magic(pattern):
        return [normalized_path] if os.path.lexists(normalized_path) else []

    matches: list[Path] = []
    seen: set[str] = set()
    for match in glob.iglob(pattern, recursive=True):
        path = Path(match).absolute()
        key = _path_key(path)
        if key in seen or not os.path.lexists(path):
            continue
        seen.add(key)
        matches.append(path)
    return sorted(matches, key=_path_key)


def discover(
    source: Path,
    options: DiscoveryOptions | None = None,
    registry: DiscoveryRegistry | None = None,
) -> DiscoveryResult:
    """Discover valid raw acquisitions below a directory.

    Symlinks are never followed. In recursive mode, a `.d` directory
    containing a case-insensitive `.tdf` or `.tdf_bin` file is recorded but
    pruned so its contents are not treated as separate acquisitions. An
    inaccessible descendant is returned as a traversal issue; an inaccessible,
    missing, symlinked, or non-directory source raises `DiscoveryError`.

    Args:
        source: Directory whose children or descendants should be examined.
        options: Discovery configuration. If None (default), uses direct
            discovery, all built-in vendors, default thresholds, and the system
            clock.
        registry: Validator registry. If None (default), uses Bruker and Thermo.

    Returns:
        Valid candidates and skipped acquisitions in deterministic path order
        and non-fatal traversal issues encountered below the source directory.

    Raises:
        DiscoveryError: If the source cannot be used as a real directory.
    """
    selected = options or DiscoveryOptions()
    source = Path(source)
    _validate_source(source)
    tree = _traverse(source, selected.scope)

    validated_candidates, validated_skips = _validate_tree(tree, selected, registry)
    candidates: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    for candidate in validated_candidates:
        key = _path_key(candidate.path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            _path_key(candidate.path),
            candidate.vendor,
            candidate.format,
        )
    )
    skipped = sorted(
        _unique_skips(validated_skips), key=lambda skip: _path_key(skip.path)
    )
    return DiscoveryResult(tuple(candidates), tree.issues, tuple(skipped))


def validate_path(
    path: Path,
    options: DiscoveryOptions | None = None,
    registry: DiscoveryRegistry | None = None,
) -> DiscoveryCandidate | None:
    """Validate one possible acquisition path.

    This is the single-path counterpart to `discover()` for workflows such as
    drag and drop or file-dialog selection. Symlinks, unsupported path types,
    and paths rejected by every registered validator return `None`.

    Args:
        path: File or directory to validate.
        options: Discovery configuration. If None (default), uses the default
            thresholds and the system clock.
        registry: Validator registry. If None (default), uses Bruker and
            Thermo validators.

    Returns:
        A valid acquisition candidate, or `None` when the path is not a
        supported complete acquisition.
    """
    return _inspect_path(path, options, registry)[0]


@dataclass
class _PathDiscovery:
    """Store validation and traversal results for one resolved input path."""

    input_path: Path
    path: Path
    validated_candidate: DiscoveryCandidate | None = None
    validated_skip: SkippedAcquisition | None = None
    discovered_candidates: list[DiscoveryCandidate] = field(default_factory=list)
    discovered_skips: list[SkippedAcquisition] = field(default_factory=list)
    issues: list[DiscoveryIssue] = field(default_factory=list)
    covered: bool = False


@dataclass
class _InputDiscovery:
    """Store resolved paths and resolution issues for one supplied input."""

    path: Path
    resolved_paths: list[_PathDiscovery] = field(default_factory=list)
    issue: DiscoveryIssue | None = None


def _resolve_inputs(
    input_paths: tuple[Path, ...],
    options: DiscoveryOptions,
    registry: DiscoveryRegistry | None,
) -> list[_InputDiscovery]:
    """Resolve supplied paths and patterns into discovery records.

    Args:
        input_paths: Normalized paths supplied to `discover_inputs`.
        options: Discovery configuration used for validation.
        registry: Validator registry, or `None` for the built-in registry.

    Returns:
        Input records containing resolved paths, validated candidates, or
        resolution issues.
    """
    discoveries: list[_InputDiscovery] = []
    for input_path in input_paths:
        resolved_paths = resolve_input_path_pattern(input_path)
        if not resolved_paths:
            if glob.has_magic(os.fspath(input_path)):
                issue = DiscoveryIssue(
                    input_path,
                    f"No paths matched input pattern {input_path!r}.",
                    code="pattern_no_matches",
                )
            else:
                issue = DiscoveryIssue(
                    input_path,
                    f"Input path {input_path!r} does not exist.",
                    code="path_not_found",
                )
            discoveries.append(_InputDiscovery(input_path, issue=issue))
            continue

        path_discoveries = [
            _PathDiscovery(input_path, path, *_inspect_path(path, options, registry))
            for path in resolved_paths
        ]
        discoveries.append(_InputDiscovery(input_path, path_discoveries))
    return discoveries


def _discover_resolved_directories(
    input_discoveries: list[_InputDiscovery],
    options: DiscoveryOptions,
    registry: DiscoveryRegistry | None,
) -> None:
    """Discover directories while pruning roots already covered recursively.

    Args:
        input_discoveries: Resolved inputs whose directories may be discovered.
        options: Discovery configuration, including traversal scope.
        registry: Validator registry, or `None` for the built-in registry.
    """
    resolved_paths = [
        path_discovery
        for input_discovery in input_discoveries
        for path_discovery in input_discovery.resolved_paths
    ]
    if options.scope is DiscoveryScope.RECURSIVE:
        resolved_paths.sort(key=lambda result: len(result.path.parts))

    scanned_roots: list[_PathDiscovery] = []
    for path_discovery in resolved_paths:
        if (
            path_discovery.validated_candidate is not None
            or path_discovery.validated_skip is not None
            or not path_discovery.path.is_dir()
        ):
            continue
        if options.scope is DiscoveryScope.RECURSIVE:
            covering_roots = [
                root
                for root in scanned_roots
                if path_discovery.path.is_relative_to(root.path)
            ]
            if covering_roots:
                path_discovery.covered = any(
                    root.input_path != path_discovery.input_path
                    for root in covering_roots
                )
                continue
        try:
            discovery_result = discover(path_discovery.path, options, registry)
        except DiscoveryError as error:
            path_discovery.issues.append(
                DiscoveryIssue(path_discovery.path, str(error), code="input_resolution")
            )
            continue

        scanned_roots.append(path_discovery)
        path_discovery.issues.extend(
            DiscoveryIssue(issue.path, issue.message, issue.code)
            for issue in discovery_result.issues
        )
        path_discovery.discovered_candidates.extend(discovery_result.candidates)
        path_discovery.discovered_skips.extend(discovery_result.skipped)


def _build_discovery_result(
    input_discoveries: list[_InputDiscovery],
) -> DiscoveryResult:
    """Collect results in input order and deduplicate candidate paths.

    Args:
        input_discoveries: Resolved inputs with their accumulated results.

    Returns:
        Candidates, issues, and skipped acquisitions ordered by their original
        input paths.
    """
    candidates: list[DiscoveryCandidate] = []
    issues: list[DiscoveryIssue] = []
    skips: list[SkippedAcquisition] = []
    seen: set[str] = set()

    for input_discovery in input_discoveries:
        if input_discovery.issue is not None:
            issues.append(input_discovery.issue)
        for path_discovery in input_discovery.resolved_paths:
            issues.extend(path_discovery.issues)
            skips.extend(_path_skips(path_discovery))
            path_candidates = path_discovery.discovered_candidates
            if path_discovery.validated_candidate is not None:
                path_candidates = [path_discovery.validated_candidate, *path_candidates]
            for candidate in path_candidates:
                key = _path_key(candidate.path)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
        issue = _no_candidates_issue(input_discovery)
        if issue is not None:
            issues.append(issue)

    return DiscoveryResult(
        tuple(candidates), tuple(issues), tuple(_unique_skips(skips))
    )


def _path_skips(path_discovery: _PathDiscovery) -> list[SkippedAcquisition]:
    if path_discovery.validated_skip is None:
        return path_discovery.discovered_skips
    return [path_discovery.validated_skip, *path_discovery.discovered_skips]


def _unique_skips(skips: Iterable[SkippedAcquisition]) -> list[SkippedAcquisition]:
    unique: dict[str, SkippedAcquisition] = {}
    for skip in skips:
        unique.setdefault(_path_key(skip.path), skip)
    return list(unique.values())


def _no_candidates_issue(input_discovery: _InputDiscovery) -> DiscoveryIssue | None:
    if input_discovery.issue is not None or any(
        path_discovery.covered
        or path_discovery.issues
        or path_discovery.validated_candidate is not None
        or path_discovery.discovered_candidates
        for path_discovery in input_discovery.resolved_paths
    ):
        return None
    skip_count = len(
        _unique_skips(
            skip
            for path_discovery in input_discovery.resolved_paths
            for skip in _path_skips(path_discovery)
        )
    )
    if skip_count:
        return DiscoveryIssue(
            input_discovery.path,
            f"No acquisitions are ready; {skip_count} skipped.",
            code="no_ready_candidates",
        )
    return DiscoveryIssue(
        input_discovery.path,
        "No supported complete acquisitions were found.",
        code="no_candidates",
    )


def _inspect_path(
    path: Path,
    options: DiscoveryOptions | None,
    registry: DiscoveryRegistry | None,
) -> tuple[DiscoveryCandidate | None, SkippedAcquisition | None]:
    """Validate one path and keep the reason when it is skipped.

    Args:
        path: File or directory to validate.
        options: Discovery configuration, or `None` for the defaults.
        registry: Validator registry, or `None` for the built-in registry.

    Returns:
        The candidate for an accepted path, the skipped entry for a recognized
        but rejected path, or neither for an unsupported path. A candidate takes
        precedence when validators disagree.
    """
    selected = options or DiscoveryOptions()
    normalized_path = Path(path).expanduser().absolute()
    try:
        metadata = os.lstat(normalized_path)
    except OSError:
        return None, None
    if stat.S_ISLNK(metadata.st_mode):
        return None, None

    if stat.S_ISREG(metadata.st_mode):
        tree = TraversalTree(files=(normalized_path,))
    elif stat.S_ISDIR(metadata.st_mode):
        tree = TraversalTree(directories=(normalized_path,))
    else:
        return None, None

    candidates, skips = _validate_tree(tree, selected, registry)
    if candidates:
        return candidates[0], None
    return None, skips[0] if skips else None


def _validate_tree(
    tree: TraversalTree,
    options: DiscoveryOptions,
    registry: DiscoveryRegistry | None,
) -> tuple[list[DiscoveryCandidate], list[SkippedAcquisition]]:
    """Run the selected validators over a traversal tree.

    Args:
        tree: Files and directories supplied to each validator.
        options: Vendor filter and validation thresholds.
        registry: Validator registry, or `None` for the built-in registry.

    Returns:
        Candidates accepted and acquisitions skipped by the selected validators.
    """
    active_registry = registry or _default_registry()
    now = options.clock()
    candidates: list[DiscoveryCandidate] = []
    skips: list[SkippedAcquisition] = []
    for vendor, format, validator in active_registry:
        if options.vendors is not None and vendor not in options.vendors:
            continue
        result = validator(tree, options.min_size_bytes, options.min_age_seconds, now)
        candidates.extend(
            DiscoveryCandidate(path, vendor, format) for path in result.valid
        )
        skips.extend(result.skipped)
    return candidates, skips


def _default_registry() -> DiscoveryRegistry:
    registry = DiscoveryRegistry()
    registry.register(Vendor.THERMO, FileFormat.RAW, validate_thermo)
    registry.register(Vendor.BRUKER, FileFormat.D, validate_bruker)
    return registry


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _has_bruker_marker(path: Path) -> tuple[bool, TraversalIssue | None]:
    try:
        with os.scandir(path) as scan:
            for member in scan:
                if member.is_symlink() or not member.is_file(follow_symlinks=False):
                    continue
                suffix = member.name.casefold()
                if suffix.endswith(".tdf") or suffix.endswith(".tdf_bin"):
                    return True, None
    except OSError as error:
        return False, TraversalIssue(
            path,
            "inaccessible",
            f"Cannot inspect {path!r} while deciding whether to prune it: "
            f"{error.strerror or error}.",
        )
    return False, None


def _traverse(source: Path, scope: DiscoveryScope) -> TraversalTree:
    files: list[Path] = []
    directories: list[Path] = []
    issues: list[TraversalIssue] = []
    pending = deque([source])
    visited = {_path_key(source)}

    while pending:
        current = pending.popleft()
        try:
            with os.scandir(current) as scan:
                entries = sorted(tuple(scan), key=lambda entry: entry.name.casefold())
        except OSError as error:
            if current == source:
                raise DiscoveryError(
                    f"Cannot access discovery source {source!r}: "
                    f"{error.strerror or error}."
                ) from error
            issues.append(
                TraversalIssue(
                    current,
                    "inaccessible",
                    f"Cannot access directory {current!r}: {error.strerror or error}.",
                )
            )
            continue

        for entry in entries:
            entry_path = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file(follow_symlinks=False):
                    files.append(entry_path)
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    continue
                directories.append(entry_path)
                if scope is DiscoveryScope.DIRECT:
                    continue
                if entry.name.casefold().endswith(".d"):
                    has_marker, issue = _has_bruker_marker(entry_path)
                    if issue is not None:
                        issues.append(issue)
                    if has_marker or issue is not None:
                        continue
                if _path_key(entry_path) not in visited:
                    visited.add(_path_key(entry_path))
                    pending.append(entry_path)
            except OSError as error:
                issues.append(
                    TraversalIssue(
                        entry_path,
                        "inaccessible",
                        f"Cannot inspect filesystem entry {entry_path!r}: "
                        f"{error.strerror or error}.",
                    )
                )
    return TraversalTree(tuple(files), tuple(directories), tuple(issues))


def _validate_source(source: Path) -> None:
    try:
        metadata = os.lstat(source)
    except OSError as error:
        raise DiscoveryError(
            f"Cannot access discovery source {source!r}: {error.strerror or error}."
        ) from error
    if stat.S_ISLNK(metadata.st_mode):
        raise DiscoveryError(
            f"Discovery source {source!r} is a symlink; provide a real directory."
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise DiscoveryError(f"Discovery source {source!r} is not a directory.")

"""Unit tests for vendor-aware discovery."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rawtrace_qc.discovery import (
    DiscoveryCandidate,
    DiscoveryIssue,
    DiscoveryOptions,
    DiscoveryRegistry,
    DiscoveryResult,
    DiscoveryScope,
    FileFormat,
    TraversalIssue,
    TraversalTree,
    Vendor,
    discover,
    discover_inputs,
    resolve_input_path_pattern,
    validate_bruker,
    validate_path,
    validate_thermo,
)
from rawtrace_qc.errors import ConfigurationError, DiscoveryError

NOW = datetime(2026, 8, 4, tzinfo=UTC).timestamp()


def _write_file(path: Path, size: int, modified_at: float = NOW - 601) -> Path:
    path.write_bytes(b"x" * size)
    os.utime(path, (modified_at, modified_at))
    return path


def _write_bruker(path: Path, size: int = 8) -> Path:
    path.mkdir()
    _write_file(path / "metadata.TDF", 1)
    _write_file(path / "binary.TDF_BIN", size)
    return path


def _options(**kwargs: object) -> DiscoveryOptions:
    values: dict[str, object] = {
        "scope": DiscoveryScope.RECURSIVE,
        "min_size_bytes": 1,
        "min_age_seconds": 600,
        "clock": lambda: NOW,
    }
    values.update(kwargs)
    return DiscoveryOptions(**values)  # type: ignore[arg-type]


def _future_validator(tree: TraversalTree, min_size_bytes: int, min_age_seconds: float, now: float) -> tuple[Path, ...]:
    del min_size_bytes, min_age_seconds, now
    return tree.files


class TestDiscoveryModels:
    def test_enums_expose_builtin_vendor_and_format_values(self) -> None:
        assert Vendor.BRUKER == "bruker"
        assert Vendor.THERMO == "thermo"
        assert FileFormat.D == "d"
        assert FileFormat.RAW == "raw"

    def test_models_store_discovery_data(self, tmp_path: Path) -> None:
        issue = TraversalIssue(tmp_path, "inaccessible", "permission denied")
        tree = TraversalTree(files=(tmp_path / "a.raw",), issues=(issue,))
        candidate = DiscoveryCandidate(tmp_path / "a.raw", Vendor.THERMO, FileFormat.RAW)
        result = DiscoveryResult((candidate,), (issue,))

        assert tree.files == (tmp_path / "a.raw",)
        assert result.candidates == (candidate,)
        assert result.issues == (issue,)

    def test_options_have_expected_defaults(self) -> None:
        options = DiscoveryOptions()

        assert options.scope is DiscoveryScope.DIRECT
        assert options.min_size_bytes == 1024 * 1024
        assert options.min_age_seconds == 600

    @pytest.mark.parametrize("threshold", ["min_size_bytes", "min_age_seconds"])
    def test_options_reject_negative_thresholds(self, threshold: str) -> None:
        with pytest.raises(ConfigurationError):
            if threshold == "min_size_bytes":
                DiscoveryOptions(min_size_bytes=-1)
            else:
                DiscoveryOptions(min_age_seconds=-1)


class TestDiscoveryRegistry:
    def test_register_and_iterate_custom_vendor(self) -> None:
        registry = DiscoveryRegistry()
        registration = ("future", "raw", _future_validator)

        registry.register(*registration)

        assert tuple(registry) == (registration,)

    def test_register_rejects_duplicate_vendor_and_format(self) -> None:
        registry = DiscoveryRegistry()
        registry.register("future", "raw", _future_validator)

        with pytest.raises(ConfigurationError):
            registry.register("future", "raw", _future_validator)


class TestVendorValidators:
    def test_validate_thermo_returns_old_enough_files_at_threshold(self, tmp_path: Path) -> None:
        valid = _write_file(tmp_path / "sample.RAW", 1, NOW - 600)
        tree = TraversalTree(files=(valid,))

        assert validate_thermo(tree, 1, 600, NOW) == (valid,)

    def test_validate_thermo_omits_small_and_recent_files(self, tmp_path: Path) -> None:
        small = _write_file(tmp_path / "small.raw", 0)
        recent = _write_file(tmp_path / "recent.raw", 1, NOW - 599)
        tree = TraversalTree(files=(small, recent))

        assert validate_thermo(tree, 1, 600, NOW) == ()

    def test_validators_always_omit_empty_files_when_minimum_size_is_zero(self, tmp_path: Path) -> None:
        thermo = _write_file(tmp_path / "empty.raw", 0)
        bruker = tmp_path / "empty.d"
        bruker.mkdir()
        _write_file(bruker / "metadata.tdf", 1)
        _write_file(bruker / "binary.tdf_bin", 0)

        assert validate_thermo(TraversalTree(files=(thermo,)), 0, 600, NOW) == ()
        assert validate_bruker(TraversalTree(directories=(bruker,)), 0, 600, NOW) == ()

    def test_validate_bruker_accepts_arbitrary_case_insensitive_member_names(self, tmp_path: Path) -> None:
        valid = _write_bruker(tmp_path / "run.D")
        tree = TraversalTree(directories=(valid,))

        assert validate_bruker(tree, 1, 600, NOW) == (valid,)

    def test_validate_bruker_requires_nonempty_tdf_and_complete_tdf_bin(self, tmp_path: Path) -> None:
        missing_tdf = tmp_path / "missing_tdf.d"
        missing_tdf.mkdir()
        _write_file(missing_tdf / "binary.tdf_bin", 1)
        empty_tdf = tmp_path / "empty_tdf.d"
        empty_tdf.mkdir()
        _write_file(empty_tdf / "metadata.tdf", 0)
        _write_file(empty_tdf / "binary.tdf_bin", 1)
        tree = TraversalTree(directories=(missing_tdf, empty_tdf))

        assert validate_bruker(tree, 1, 600, NOW) == ()


class TestDiscover:
    def test_discovers_valid_candidates_in_deterministic_order(self, tmp_path: Path) -> None:
        _write_file(tmp_path / "z.raw", 1)
        _write_bruker(tmp_path / "a.d")

        result = discover(tmp_path, _options())

        assert [candidate.path.name for candidate in result.candidates] == ["a.d", "z.raw"]

    def test_direct_scope_omits_descendants(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested"
        nested.mkdir()
        _write_file(nested / "sample.raw", 1)

        result = discover(tmp_path, _options(scope=DiscoveryScope.DIRECT))

        assert result.candidates == ()

    def test_recursive_scope_prunes_bruker_contents(self, tmp_path: Path) -> None:
        bruker = _write_bruker(tmp_path / "run.d")
        _write_file(bruker / "nested.raw", 1)

        result = discover(tmp_path, _options())

        assert [candidate.path for candidate in result.candidates] == [bruker]

    def test_vendor_filter_limits_candidates(self, tmp_path: Path) -> None:
        bruker = _write_bruker(tmp_path / "run.d")
        thermo = _write_file(tmp_path / "sample.raw", 1)

        result = discover(tmp_path, _options(vendors=frozenset({Vendor.THERMO})))

        assert [candidate.path for candidate in result.candidates] == [thermo]
        assert result.candidates[0].vendor is Vendor.THERMO
        assert bruker not in [candidate.path for candidate in result.candidates]

    def test_custom_registry_validates_the_traversal_tree(self, tmp_path: Path) -> None:
        sample = _write_file(tmp_path / "sample.future", 1)
        registry = DiscoveryRegistry()
        registry.register("future", "future", _future_validator)

        result = discover(tmp_path, _options(), registry)

        assert result.candidates == (DiscoveryCandidate(sample, "future", "future"),)

    def test_inaccessible_descendant_is_returned_as_an_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        accessible = _write_file(tmp_path / "accessible.raw", 1)
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        discover_module = importlib.import_module("rawtrace_qc.discovery.discover")
        original_scandir = discover_module.os.scandir

        def scandir(path: object) -> object:
            if Path(path) == blocked:  # type: ignore[arg-type]
                raise PermissionError("denied")
            return original_scandir(path)  # type: ignore[arg-type]

        monkeypatch.setattr(discover_module.os, "scandir", scandir)

        result = discover(tmp_path, _options())

        assert result.candidates[0].path == accessible
        assert result.issues[0].path == blocked
        assert discover_inputs((tmp_path,), _options()).issues[0].path == blocked

    def test_source_must_be_an_accessible_real_directory(self, tmp_path: Path) -> None:
        source_file = _write_file(tmp_path / "source.raw", 1)

        with pytest.raises(DiscoveryError):
            discover(source_file)

    def test_symlinked_entries_are_not_followed(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        _write_file(target / "sample.raw", 1)
        link = root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlinks are unavailable: {error}")

        assert discover(root, _options()).candidates == ()


class TestValidatePath:
    def test_validates_complete_files_and_directories(self, tmp_path: Path) -> None:
        sample = _write_file(tmp_path / "sample.raw", 1)
        bruker = _write_bruker(tmp_path / "run.d")

        assert validate_path(sample, _options()) == DiscoveryCandidate(sample, Vendor.THERMO, FileFormat.RAW)
        assert validate_path(bruker, _options()) == DiscoveryCandidate(bruker, Vendor.BRUKER, FileFormat.D)

    def test_rejects_symlinked_paths(self, tmp_path: Path) -> None:
        target = _write_file(tmp_path / "target.raw", 1)
        link = tmp_path / "link.raw"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            pytest.skip(f"symlinks are unavailable: {error}")

        assert validate_path(link, _options()) is None


class TestDiscoverInputs:
    def test_resolves_files_and_directories_and_deduplicates_candidates(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        raw_file = _write_file(source / "sample.raw", 1)
        bruker_directory = _write_bruker(source / "run.d")

        result = discover_inputs((str(raw_file), source, bruker_directory), _options())

        assert [candidate.path for candidate in result.candidates] == [raw_file, bruker_directory]
        assert result.issues == ()

    def test_recursive_scope_scans_parent_before_child_without_redundant_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "source"
        child = source / "nested"
        child.mkdir(parents=True)
        raw_file = _write_file(source / "sample.raw", 1)
        discover_module = importlib.import_module("rawtrace_qc.discovery.discover")
        original_discover = discover_module.discover
        scanned: list[Path] = []

        def recording_discover(
            root: Path,
            options: DiscoveryOptions | None = None,
            registry: DiscoveryRegistry | None = None,
        ) -> DiscoveryResult:
            scanned.append(root)
            return original_discover(root, options, registry)

        monkeypatch.setattr(discover_module, "discover", recording_discover)

        result = discover_inputs((child, source), _options())

        assert scanned == [source]
        assert [candidate.path for candidate in result.candidates] == [raw_file]
        assert result.issues == ()

    def test_accumulates_empty_scan_and_input_resolution_issues(self, tmp_path: Path) -> None:
        empty_directory = tmp_path / "empty"
        empty_directory.mkdir()
        missing_path = tmp_path / "missing"

        result = discover_inputs((empty_directory, str(missing_path)), _options())

        assert result.candidates == ()
        assert [issue.path for issue in result.issues] == [empty_directory, missing_path]
        assert [issue.code for issue in result.issues] == ["no_candidates", "path_not_found"]
        assert all(isinstance(issue, DiscoveryIssue) for issue in result.issues)
        assert "No supported" in result.issues[0].message

    def test_ignores_non_acquisition_files_matched_by_glob(self, tmp_path: Path) -> None:
        raw_file = _write_file(tmp_path / "sample.raw", 1)
        (tmp_path / "notes.txt").write_text("not an acquisition")

        result = discover_inputs((tmp_path / "*",), _options())

        assert [candidate.path for candidate in result.candidates] == [raw_file]
        assert result.issues == ()

    def test_creates_no_issues_when_glob_matches_only_non_acquisition_files(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not an acquisition")

        result = discover_inputs((tmp_path / "*.txt",), _options())

        assert result.candidates == ()
        assert result.issues == ()

    def test_reports_non_acquisition_literal_file_without_directory_error(self, tmp_path: Path) -> None:
        unsupported_file = tmp_path / "notes.txt"
        unsupported_file.write_text("not an acquisition")

        result = discover_inputs((unsupported_file,), _options())

        assert result.candidates == ()
        assert len(result.issues) == 1
        assert result.issues[0].path == unsupported_file
        assert result.issues[0].code == "no_candidates"
        assert "not a directory" not in result.issues[0].message

    def test_reports_unmatched_glob_pattern(self, tmp_path: Path) -> None:
        pattern = tmp_path / "*.raw"

        result = discover_inputs((pattern,), _options())

        assert result.candidates == ()
        assert len(result.issues) == 1
        assert result.issues[0].path == pattern.absolute()
        assert result.issues[0].code == "pattern_no_matches"
        assert "No paths matched" in result.issues[0].message

    def test_requires_at_least_one_input(self) -> None:
        with pytest.raises(ConfigurationError, match="At least one input path"):
            discover_inputs(())


class TestResolveInputPathPattern:
    def test_returns_existing_files_and_directories_without_format_validation(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        source.mkdir()
        text_file = source / "notes.txt"
        text_file.write_text("not an acquisition")

        assert resolve_input_path_pattern(text_file) == [text_file.absolute()]
        assert resolve_input_path_pattern(str(text_file)) == [text_file.absolute()]
        assert resolve_input_path_pattern(source) == [source.absolute()]

    def test_returns_empty_list_for_missing_plain_path(self, tmp_path: Path) -> None:
        assert resolve_input_path_pattern(tmp_path / "missing.raw") == []

    def test_expands_star_question_mark_character_class_and_recursive_patterns(self, tmp_path: Path) -> None:
        root_files = [tmp_path / "run-a.raw", tmp_path / "run-b.raw", tmp_path / "run-12.raw"]
        nested_file = tmp_path / "nested" / "run-c.raw"
        nested_file.parent.mkdir()
        for path in (*root_files, nested_file):
            path.write_bytes(b"data")

        assert resolve_input_path_pattern(tmp_path / "run-*.raw") == [
            tmp_path / "run-12.raw",
            tmp_path / "run-a.raw",
            tmp_path / "run-b.raw",
        ]
        assert resolve_input_path_pattern(tmp_path / "run-?.raw") == root_files[:2]
        assert resolve_input_path_pattern(tmp_path / "run-[ab].raw") == root_files[:2]
        recursive_matches = resolve_input_path_pattern(tmp_path / "**" / "run-?.raw")
        assert set(recursive_matches) == {root_files[0], root_files[1], nested_file}

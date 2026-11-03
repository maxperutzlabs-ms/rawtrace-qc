"""Unit tests for GUI extraction, cache, helper, and report services."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path

import pytest
from rawtrace_qc.discovery import DiscoveryCandidate, FileFormat, Vendor
from rawtrace_qc.errors import ConfigurationError, OperationCancelledError, ProcessingError
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.gui.cache import CacheResult, TraceCache
from rawtrace_qc.gui.config import GuiSettings, load_settings, save_settings
from rawtrace_qc.gui.reporting import (
    ExcludedFile,
    ReportGenerationOptions,
    ReportProgress,
    ReportStage,
    ReportStorageMode,
    generate_report,
)
from rawtrace_qc.gui.workflow import ExclusionReason
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.report import ReportAssetMode, ReportOptions
from rawtrace_qc.traces import load_trace


def _bruker_candidate(path: Path) -> DiscoveryCandidate:
    return DiscoveryCandidate(path, Vendor.BRUKER, FileFormat.D)


class TestGuiSettings:
    def test_theme_mode_defaults_to_system(self) -> None:
        assert GuiSettings().theme_mode == "system"

    @pytest.mark.parametrize("theme_mode", ("system", "light", "dark"))
    def test_accepts_supported_theme_modes(self, theme_mode: str) -> None:
        assert GuiSettings(theme_mode=theme_mode).theme_mode == theme_mode

    def test_rejects_unsupported_theme_mode(self) -> None:
        with pytest.raises(ConfigurationError, match="GUI theme mode"):
            GuiSettings(theme_mode="sepia")

    def test_persists_and_loads_theme_mode(self, tmp_path: Path) -> None:
        config_path = tmp_path / "settings.json"

        save_settings(GuiSettings(theme_mode="dark"), config_path)

        assert load_settings(config_path).theme_mode == "dark"

    def test_uses_system_theme_mode_for_legacy_settings(self, tmp_path: Path) -> None:
        config_path = tmp_path / "settings.json"
        config_path.write_text("{}", encoding="utf-8")

        assert load_settings(config_path).theme_mode == "system"


class TestTraceCache:
    def test_extracts_once_and_loads_valid_artifacts_on_second_call(self, bruker_fixture: Path, tmp_path: Path) -> None:
        cache = TraceCache(tmp_path / "cache")
        candidate = _bruker_candidate(bruker_fixture)

        first = cache.extract(candidate, BrukerExtractor(), select_msn=False)
        second = cache.extract(candidate, BrukerExtractor(), select_msn=False)

        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.extraction == first.extraction
        assert second.extraction.ms1_path is not None
        assert second.extraction.ms1_path.is_file()
        assert len(second.extraction.ms1_path.parent.name) == 16
        assert second.extraction.ms1_path.name == "trace.ms1-trace.parquet"
        assert load_trace(second.extraction.ms1_path).metadata["source_filename"] == bruker_fixture.name

    def test_partial_cache_is_rebuilt_when_both_levels_are_requested(
        self, bruker_fixture: Path, tmp_path: Path
    ) -> None:
        cache = TraceCache(tmp_path / "cache")
        candidate = _bruker_candidate(bruker_fixture)
        first = cache.extract(candidate, BrukerExtractor())
        assert first.extraction.msn_path is not None
        first.extraction.msn_path.unlink()

        second = cache.extract(candidate, BrukerExtractor())

        assert second.cache_hit is False
        assert second.extraction.msn_path is not None
        assert second.extraction.msn_path.is_file()


class TestReportGeneration:
    def test_generates_a_permanent_report_and_reuses_the_cache(self, bruker_fixture: Path, tmp_path: Path) -> None:
        candidate = _bruker_candidate(bruker_fixture)
        options = ReportGenerationOptions(
            storage_mode=ReportStorageMode.PERMANENT,
            output_directory=tmp_path / "reports",
            output_name="qc.html",
            report_options=ReportOptions(asset_mode=ReportAssetMode.CDN),
        )
        cache = TraceCache(tmp_path / "cache")

        first = generate_report((candidate,), cache, options=options)
        second = generate_report((candidate,), cache, options=options)

        assert first.output_path == (tmp_path / "reports" / "qc.html").resolve()
        assert first.output_path.is_file()
        assert first.processed_table_count == 2
        assert first.cache_hits == 0
        assert second.cache_hits == 1

    def test_thermo_generation_uses_extractor_with_managed_helper(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source_path = tmp_path / "sample.raw"
        source_path.touch()
        candidate = DiscoveryCandidate(source_path, Vendor.THERMO, FileFormat.RAW)
        trace_path = tmp_path / "cache" / "sample.raw.ms1-trace.parquet"
        options = ReportGenerationOptions(
            storage_mode=ReportStorageMode.PERMANENT,
            output_directory=tmp_path / "reports",
            output_name="thermo.html",
        )
        cache = TraceCache(tmp_path / "cache")
        helper_paths: list[Path | None] = []

        def fake_cache_extract(
            cached_candidate: DiscoveryCandidate,
            extractor: ThermoExtractor,
            **_kwargs: object,
        ) -> CacheResult:
            assert cached_candidate == candidate
            assert isinstance(extractor, ThermoExtractor)
            helper_paths.append(extractor._helper_path)
            return CacheResult(ExtractionResult(ms1_path=trace_path), False)

        monkeypatch.setattr(cache, "extract", fake_cache_extract)
        monkeypatch.setattr("rawtrace_qc.gui.reporting.load_trace", lambda _path: object())
        monkeypatch.setattr("rawtrace_qc.gui.reporting.process_traces", lambda artifacts: tuple(artifacts))
        monkeypatch.setattr(
            "rawtrace_qc.gui.reporting.write_html",
            lambda _tables, path, *, options: path,
        )

        result = generate_report((candidate,), cache, options=options)

        assert helper_paths == [None]
        assert result.output_path == tmp_path / "reports" / "thermo.html"
        assert result.processed_table_count == 1


class TestReportGenerationWithBadFiles:
    def _candidates(self, tmp_path: Path, *names: str) -> tuple[DiscoveryCandidate, ...]:
        return tuple(DiscoveryCandidate(tmp_path / name, Vendor.THERMO, FileFormat.RAW) for name in names)

    def _options(self, tmp_path: Path) -> ReportGenerationOptions:
        return ReportGenerationOptions(
            storage_mode=ReportStorageMode.PERMANENT,
            output_directory=tmp_path / "reports",
            output_name="qc.html",
        )

    def _cache(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        bad_extract: Iterable[str] = (),
        no_artifacts: Iterable[str] = (),
        bad_load: Iterable[str] = (),
        bad_process: Iterable[str] = (),
        no_rows: Iterable[str] = (),
    ) -> TraceCache:
        cache = TraceCache(tmp_path / "cache")
        bad_extract, no_artifacts = set(bad_extract), set(no_artifacts)
        bad_load, bad_process, no_rows = set(bad_load), set(bad_process), set(no_rows)

        def fake_extract(candidate: DiscoveryCandidate, _extractor: object, **_kwargs: object) -> CacheResult:
            name = candidate.path.name
            if name in bad_extract:
                raise OSError(f"cannot read {name}")
            if name in no_artifacts:
                return CacheResult(ExtractionResult(), False)
            return CacheResult(ExtractionResult(ms1_path=candidate.path), name.startswith("cached"))

        def fake_load(path: Path) -> str:
            if path.name in bad_load:
                raise ValueError(f"cannot load {path.name}")
            return path.name

        def fake_process(artifacts: list[str]) -> tuple[str, ...]:
            if bad_process.intersection(artifacts):
                raise ProcessingError(f"cannot process {artifacts[0]}")
            return () if no_rows.intersection(artifacts) else tuple(artifacts)

        written: list[object] = []

        def fake_write(tables: list[str], path: Path, *, options: object) -> Path:
            written.extend(tables)
            return path

        monkeypatch.setattr(cache, "extract", fake_extract)
        monkeypatch.setattr("rawtrace_qc.gui.reporting.load_trace", fake_load)
        monkeypatch.setattr("rawtrace_qc.gui.reporting.process_traces", fake_process)
        monkeypatch.setattr("rawtrace_qc.gui.reporting.write_html", fake_write)
        self.written = written
        return cache

    @pytest.mark.parametrize(
        ("failure", "reason", "detail"),
        [
            ("bad_extract", ExclusionReason.EXTRACTION_FAILED, "cannot read bad.raw"),
            ("no_artifacts", ExclusionReason.PROCESSING_FAILED, "no MS1 or MS2 scans"),
            ("bad_load", ExclusionReason.PROCESSING_FAILED, "cannot load bad.raw"),
            ("bad_process", ExclusionReason.PROCESSING_FAILED, "cannot process bad.raw"),
            ("no_rows", ExclusionReason.PROCESSING_FAILED, "no MS1 or MS2 scans"),
        ],
    )
    def test_bad_file_is_excluded_and_the_report_contains_the_other_files_in_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, reason: ExclusionReason, detail: str
    ) -> None:
        candidates = self._candidates(tmp_path, "first.raw", "bad.raw", "last.raw")
        cache = self._cache(tmp_path, monkeypatch, **{failure: ("bad.raw",)})
        notified: list[ExcludedFile] = []

        result = generate_report(candidates, cache, options=self._options(tmp_path), on_excluded=notified.append)

        assert result.included == (candidates[0], candidates[2])
        assert self.written == ["first.raw", "last.raw"]
        assert result.processed_table_count == 2
        assert result.excluded == tuple(notified)
        assert notified[0].candidate == candidates[1]
        assert notified[0].exclusion.reason is reason
        assert detail in notified[0].exclusion.detail

    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            ("bad_extract", "OSError: cannot read bad.raw"),
            ("bad_load", "ValueError: cannot load bad.raw"),
            ("bad_process", "cannot process bad.raw"),
        ],
    )
    def test_detail_names_the_type_of_unexpected_errors_but_not_of_library_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, expected: str
    ) -> None:
        candidates = self._candidates(tmp_path, "good.raw", "bad.raw")
        cache = self._cache(tmp_path, monkeypatch, **{failure: ("bad.raw",)})

        result = generate_report(candidates, cache, options=self._options(tmp_path))

        assert result.excluded[0].exclusion.detail == expected

    def test_raises_when_every_file_is_excluded_and_writes_no_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidates = self._candidates(tmp_path, "a.raw", "b.raw")
        cache = self._cache(tmp_path, monkeypatch, bad_extract=("a.raw",), bad_load=("b.raw",))
        notified: list[ExcludedFile] = []

        with pytest.raises(ConfigurationError, match="None of the 2 selected file"):
            generate_report(candidates, cache, options=self._options(tmp_path), on_excluded=notified.append)

        assert len(notified) == 2
        assert self.written == []

    def test_progress_counts_every_file_including_bad_ones_through_all_stages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidates = self._candidates(tmp_path, "cached.raw", "bad.raw", "last.raw")
        cache = self._cache(tmp_path, monkeypatch, bad_extract=("bad.raw",))
        progress: list[ReportProgress] = []

        generate_report(candidates, cache, options=self._options(tmp_path), on_progress=progress.append)

        assert [(item.stage, item.current, item.total) for item in progress] == [
            (ReportStage.EXTRACTING, 1, 3),
            (ReportStage.EXTRACTING, 2, 3),
            (ReportStage.EXTRACTING, 3, 3),
            (ReportStage.PROCESSING, 1, 2),
            (ReportStage.PROCESSING, 2, 2),
            (ReportStage.WRITING, 0, 0),
        ]
        assert progress[2].cache_hits == 1

    def test_setting_cancel_stops_before_the_next_file_without_excluding_or_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidates = self._candidates(tmp_path, "a.raw", "b.raw")
        cache = self._cache(tmp_path, monkeypatch)
        cancel = threading.Event()
        progress: list[ReportProgress] = []
        notified: list[ExcludedFile] = []

        def cancel_after_first(item: ReportProgress) -> None:
            progress.append(item)
            cancel.set()

        with pytest.raises(OperationCancelledError):
            generate_report(
                candidates,
                cache,
                options=self._options(tmp_path),
                on_progress=cancel_after_first,
                on_excluded=notified.append,
                cancel=cancel,
            )

        assert len(progress) == 1
        assert notified == []
        assert self.written == []

    def test_cancelled_extraction_is_not_treated_as_a_bad_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidates = self._candidates(tmp_path, "a.raw")
        cache = self._cache(tmp_path, monkeypatch)
        notified: list[ExcludedFile] = []

        def cancelled_extract(*_args: object, **_kwargs: object) -> CacheResult:
            raise OperationCancelledError("stopped")

        monkeypatch.setattr(cache, "extract", cancelled_extract)

        with pytest.raises(OperationCancelledError):
            generate_report(candidates, cache, options=self._options(tmp_path), on_excluded=notified.append)

        assert notified == []

    def test_thermo_extractor_receives_the_cancel_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        candidates = self._candidates(tmp_path, "a.raw")
        cache = self._cache(tmp_path, monkeypatch)
        cancel = threading.Event()
        received: list[object] = []

        def recording_extract(
            candidate: DiscoveryCandidate, extractor: ThermoExtractor, **_kwargs: object
        ) -> CacheResult:
            received.append(extractor._cancel)
            return CacheResult(ExtractionResult(ms1_path=candidate.path), False)

        monkeypatch.setattr(cache, "extract", recording_extract)

        generate_report(candidates, cache, options=self._options(tmp_path), cancel=cancel)

        assert received == [cancel]


class TestReportProgressMessage:
    @pytest.mark.parametrize(
        ("progress", "expected"),
        [
            (ReportProgress(ReportStage.EXTRACTING, 3, 12, "s.raw"), "Extracting 3 of 12: s.raw"),
            (ReportProgress(ReportStage.EXTRACTING, 3, 12, "s.raw", 2), "Extracting 3 of 12 (2 cached): s.raw"),
            (ReportProgress(ReportStage.PROCESSING, 2, 2, "s.raw"), "Processing traces 2 of 2"),
            (ReportProgress(ReportStage.WRITING), "Writing report..."),
        ],
    )
    def test_describes_each_stage(self, progress: ReportProgress, expected: str) -> None:
        assert progress.message == expected

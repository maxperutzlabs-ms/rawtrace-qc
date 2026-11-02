"""Unit tests for GUI extraction, cache, helper, and report services."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.discovery import DiscoveryCandidate, FileFormat, Vendor
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.gui.cache import CacheResult, TraceCache
from rawtrace_qc.gui.config import GuiSettings, load_settings, save_settings
from rawtrace_qc.gui.reporting import ReportGenerationOptions, ReportStorageMode, generate_report
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

"""Unit tests for GUI extraction, cache, helper, and report services."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from rawtrace_qc.discovery import DiscoveryCandidate, FileFormat, Vendor
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.extractors import BrukerExtractor, ThermoExtractor
from rawtrace_qc.gui.cache import CacheResult, TraceCache
from rawtrace_qc.gui.config import GuiSettings, ThermoToolSettings, load_settings, save_settings
from rawtrace_qc.gui.reporting import ReportGenerationOptions, ReportStorageMode, generate_report
from rawtrace_qc.gui.thermo import ThermoToolManager
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.report import ReportAssetMode, ReportOptions
from rawtrace_qc.traces import load_trace
from tests.support.thermo_helper import WIN_X64_SPECIFICATION


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


class TestThermoToolManager:
    def test_default_install_directory_uses_pinned_helper_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data_directory = tmp_path / "appdata"
        monkeypatch.setattr(
            "rawtrace_qc.environment.user_data_dir",
            lambda **_kwargs: str(data_directory),
        )

        manager = ThermoToolManager(ThermoToolSettings())

        assert (
            manager.install_directory
            == (
                data_directory / "tools" / "thermoscanheaderextractor" / WIN_X64_SPECIFICATION.version / "win-x64"
            ).resolve()
        )
        assert not data_directory.exists()

    def test_downloads_verifies_and_extracts_the_pinned_archive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable_payload = b"thermo helper executable"
        archive_buffer = BytesIO()
        with ZipFile(archive_buffer, "w") as archive:
            archive.writestr(WIN_X64_SPECIFICATION.executable_name, executable_payload)
        archive_payload = archive_buffer.getvalue()
        test_specification = replace(
            WIN_X64_SPECIFICATION,
            download_url="https://example.test/pinned-helper.zip",
            sha256=hashlib.sha256(archive_payload).hexdigest(),
        )
        monkeypatch.setattr("rawtrace_qc.gui.thermo.THERMO_HELPER_SPECIFICATION", test_specification)
        requested_urls: list[str] = []

        def open_archive(url: str, timeout: int) -> BytesIO:
            requested_urls.append(url)
            return BytesIO(archive_payload)

        monkeypatch.setattr("rawtrace_qc.gui.thermo.urlopen", open_archive)

        path = ThermoToolManager(ThermoToolSettings(), tmp_path / "tools").ensure_available()

        assert requested_urls == [test_specification.download_url]
        assert path.name == test_specification.executable_name
        assert path.read_bytes() == executable_payload

    def test_rejects_pinned_archive_with_incorrect_checksum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_payload = b"not the pinned archive"
        test_specification = replace(
            WIN_X64_SPECIFICATION, download_url="https://example.test/pinned-helper.zip", sha256="0" * 64
        )
        monkeypatch.setattr("rawtrace_qc.gui.thermo.THERMO_HELPER_SPECIFICATION", test_specification)
        monkeypatch.setattr("rawtrace_qc.gui.thermo.urlopen", lambda url, timeout: BytesIO(archive_payload))

        with pytest.raises(ConfigurationError, match="SHA-256 verification"):
            ThermoToolManager(ThermoToolSettings(), tmp_path / "tools").ensure_available()

    def test_configured_local_executable_bypasses_download(self, tmp_path: Path) -> None:
        executable_path = tmp_path / "ThermoScanHeaderExtractor.exe"
        executable_path.write_bytes(b"local helper")

        path = ThermoToolManager(
            ThermoToolSettings(executable_path=executable_path), tmp_path / "tools"
        ).ensure_available()

        assert path == executable_path.resolve()


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

    def test_thermo_generation_uses_extractor_and_configured_helper_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source_path = tmp_path / "sample.raw"
        source_path.touch()
        candidate = DiscoveryCandidate(source_path, Vendor.THERMO, FileFormat.RAW)
        helper_path = tmp_path / "central" / "ThermoScanHeaderExtractor.exe"
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
            return CacheResult(ExtractionResult(ms1_path=trace_path), False)

        monkeypatch.setattr(cache, "extract", fake_cache_extract)
        monkeypatch.setattr(
            "rawtrace_qc.gui.reporting.ThermoExtractor",
            lambda *, helper_path=None: helper_paths.append(helper_path) or ThermoExtractor(helper_path=helper_path),
        )
        monkeypatch.setattr("rawtrace_qc.gui.reporting.load_trace", lambda _path: object())
        monkeypatch.setattr("rawtrace_qc.gui.reporting.process_traces", lambda artifacts: tuple(artifacts))
        monkeypatch.setattr(
            "rawtrace_qc.gui.reporting.write_html",
            lambda _tables, path, *, options: path,
        )

        result = generate_report(
            (candidate,),
            cache,
            options=options,
            thermo_settings=ThermoToolSettings(executable_path=helper_path),
        )

        assert helper_paths == [helper_path]
        assert result.output_path == tmp_path / "reports" / "thermo.html"
        assert result.processed_table_count == 1

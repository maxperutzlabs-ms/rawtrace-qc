"""Unit tests for the GUI-independent selection and configuration workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.discovery import DiscoveryCandidate, DiscoveryOptions, FileFormat, Vendor
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.gui.config import (
    GuiSettings,
    default_config_path,
    default_data_directory,
    load_settings,
    save_settings,
)
from rawtrace_qc.gui.patterns import FilenamePattern, PatternMode, filter_candidates
from rawtrace_qc.gui.workflow import RawFileSelection


def _candidate(tmp_path: Path, name: str) -> DiscoveryCandidate:
    path = tmp_path / name
    return DiscoveryCandidate(path, Vendor.THERMO, FileFormat.RAW)


def test_filter_candidates_uses_include_or_and_exclude_wins(tmp_path: Path) -> None:
    candidates = (
        _candidate(tmp_path, "sample-a.raw"),
        _candidate(tmp_path, "sample-b.raw"),
        _candidate(tmp_path, "blank.raw"),
    )
    patterns = (
        FilenamePattern("samples", r"sample-[ab]", PatternMode.INCLUDE),
        FilenamePattern("blank", r"blank", PatternMode.EXCLUDE),
    )

    filtered = filter_candidates(candidates, patterns)

    assert [item.candidate.path.name for item in filtered] == ["sample-a.raw", "sample-b.raw", "blank.raw"]
    assert [item.included for item in filtered] == [True, True, False]
    assert filtered[-1].matched_pattern_names == ("blank",)


def test_filename_pattern_rejects_invalid_regex() -> None:
    with pytest.raises(ConfigurationError, match="invalid regular expression"):
        FilenamePattern("broken", "[")


def test_gui_settings_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    settings = GuiSettings(
        scope="recursive",
        min_size_mb=2,
        min_age_minutes=12.5,
        patterns=(FilenamePattern("run", r"run_\\d+"),),
        cache_directory=tmp_path / "cache",
        report_directory=tmp_path / "reports",
    )

    save_settings(settings, config_path)
    loaded = load_settings(config_path)

    assert loaded == settings
    assert loaded.discovery_options().min_size_bytes == 2 * 1024 * 1024
    assert loaded.discovery_options().min_age_seconds == 12.5 * 60


def test_gui_settings_ignore_and_drop_a_previously_saved_helper_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"thermo": {"executable_path": "C:/tools/helper.exe"}, "theme_mode": "dark"}', encoding="utf-8"
    )

    loaded = load_settings(config_path)
    save_settings(loaded, config_path)

    assert loaded.theme_mode == "dark"
    assert "thermo" not in config_path.read_text(encoding="utf-8")


def test_gui_settings_loads_legacy_discovery_units(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"discovery": {"min_size_bytes": 2097152, "min_age_seconds": 90}}', encoding="utf-8")

    loaded = load_settings(config_path)

    assert loaded.min_size_mb == 2
    assert loaded.min_age_minutes == 1.5


def test_gui_defaults_use_platformdirs_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("rawtrace_qc.environment.user_data_dir", lambda **_kwargs: str(appdata))

    settings = GuiSettings()

    assert default_data_directory() == appdata
    assert default_config_path() == appdata / "config.json"
    assert settings.cache_directory == appdata / "traces"
    assert settings.report_directory == appdata / "reports"


def test_gui_keeps_its_own_discovery_thresholds() -> None:
    options = RawFileSelection().options

    assert options.min_size_bytes == 1024 * 1024
    assert options.min_age_seconds == 120


def test_save_settings_creates_the_default_appdata_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("rawtrace_qc.environment.user_data_dir", lambda **_kwargs: str(appdata))

    saved_path = save_settings(GuiSettings())

    assert saved_path == appdata / "config.json"
    assert saved_path.is_file()


def test_selection_validates_paths_and_keeps_unique_active_entries(tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")
    selection = RawFileSelection(DiscoveryOptions(min_size_bytes=1, min_age_seconds=0))

    first = selection.add_paths((raw, raw))
    second = selection.add_paths((tmp_path / "invalid.txt",))

    assert len(first.accepted) == 2
    assert first.rejected == ()
    assert second.accepted == ()
    assert second.rejected == ((tmp_path / "invalid.txt").resolve(),)
    assert len(selection.selected) == 1
    assert selection.active_selected() == (first.accepted[0],)


def test_selection_accepts_zero_age_files_when_clock_lags_file_mtime(tmp_path: Path) -> None:
    raw = tmp_path / "sample.raw"
    raw.write_bytes(b"raw")
    selection = RawFileSelection(DiscoveryOptions(min_size_bytes=1, min_age_seconds=0, clock=lambda: 0))

    result = selection.add_paths((raw,))

    assert result.accepted[0].path == raw.absolute()
    assert result.rejected == ()


def test_selection_promotes_only_checked_included_candidates(tmp_path: Path) -> None:
    candidates = (_candidate(tmp_path, "sample.raw"), _candidate(tmp_path, "blank.raw"))
    selection = RawFileSelection()
    selection.set_candidates(candidates)
    selection.apply_patterns((FilenamePattern("samples", "sample", PatternMode.INCLUDE),))
    selection.set_candidate_active(tmp_path / "sample.raw", False)

    selection.promote_active_candidates()

    assert selection.selected == ()

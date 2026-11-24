"""Tests for GUI-independent application data paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.environment import default_data_directory, helper_tool_directory


class TestDefaultDataDirectory:
    def test_uses_platformdirs_location_without_creating_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        platform_path = tmp_path / "platform-data"
        calls: list[dict[str, object]] = []

        def platformdirs_path(**kwargs: object) -> str:
            calls.append(kwargs)
            return str(platform_path)

        monkeypatch.setattr("rawtrace_qc.environment.user_data_dir", platformdirs_path)

        assert default_data_directory() == platform_path
        assert calls == [{"appname": "rawtrace-qc", "appauthor": "perutzms", "roaming": False}]
        assert not platform_path.exists()


class TestHelperToolDirectory:
    def test_includes_helper_release_version_and_runtime_without_creating_directories(
        self, isolated_data_directory: Path
    ) -> None:
        path = helper_tool_directory("thermoscanheaderextractor", "0.1.0", "win-x64")

        assert path == isolated_data_directory / "tools" / "thermoscanheaderextractor" / "0.1.0" / "win-x64"
        assert not isolated_data_directory.exists()

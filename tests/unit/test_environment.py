"""Tests for GUI-independent application data paths."""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.environment import default_data_directory, helper_tool_directory


class TestDefaultDataDirectory:
    def test_explicit_override_takes_precedence_over_platformdirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit_path = tmp_path / "explicit-data"
        platform_path = tmp_path / "platform-data"
        monkeypatch.setattr("rawtrace_qc.environment.user_data_dir", lambda **_kwargs: str(platform_path))

        assert default_data_directory() == platform_path
        assert default_data_directory(explicit_path) == explicit_path
        assert not platform_path.exists()
        assert not explicit_path.exists()

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
    def test_includes_helper_release_version_and_runtime_without_creating_directories(self, tmp_path: Path) -> None:
        data_directory = tmp_path / "appdata"

        path = helper_tool_directory("thermoscanheaderextractor", "0.1.0", "win-x64", data_directory=data_directory)

        assert path == data_directory / "tools" / "thermoscanheaderextractor" / "0.1.0" / "win-x64"
        assert not path.exists()
        assert not data_directory.exists()

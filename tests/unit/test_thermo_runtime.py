"""Tests for host runtime detection."""

from __future__ import annotations

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import UnsupportedPlatformError
from rawtrace_qc.thermo import detect_runtime


class TestDetectRuntime:
    @pytest.mark.parametrize(
        ("platform_name", "machine", "expected"),
        [
            ("win32", "AMD64", "win-x64"),
            ("win32", "ARM64", "win-arm64"),
            ("win32", "arm64", "win-arm64"),
            ("linux", "x86_64", "linux-x64"),
            ("linux", "aarch64", "linux-arm64"),
            ("darwin", "x86_64", "osx-x64"),
            ("darwin", "arm64", "osx-arm64"),
            ("win32", "amd64", "win-x64"),
        ],
    )
    def test_maps_platform_and_machine_to_runtime(
        self, monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str, expected: str
    ) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: platform_name)
        monkeypatch.setattr(environment, "get_machine", lambda: machine)

        assert detect_runtime() == expected

    @pytest.mark.parametrize(
        ("platform_name", "machine"),
        [("freebsd13", "amd64"), ("cygwin", "x86_64"), ("win32", "x86"), ("linux", "riscv64"), ("linux", "")],
    )
    def test_raises_unsupported_platform_error_for_unknown_platform_or_machine(
        self, monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str
    ) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: platform_name)
        monkeypatch.setattr(environment, "get_machine", lambda: machine)

        with pytest.raises(UnsupportedPlatformError, match=repr(platform_name)):
            detect_runtime()

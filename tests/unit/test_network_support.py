"""Tests for shared network-test and collection behavior."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Self
from urllib.error import HTTPError
from urllib.request import Request

import pytest
import tests.support.collection as collection_support
import tests.support.network as network_support


class _CollectedItem:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.markers: list[pytest.MarkDecorator] = []

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.markers.append(marker)


class TestUrlopenOrSkip:
    def test_yields_successful_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(network_support, "urlopen", lambda url, timeout: BytesIO(b"asset"))

        with network_support.urlopen_or_skip("https://example.test/asset") as response:
            assert response.read() == b"asset"

    def test_sends_requested_method(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request_methods: list[str] = []

        def open_request(request: Request, timeout: float) -> BytesIO:
            request_methods.append(request.get_method())
            return BytesIO(b"")

        monkeypatch.setattr(network_support, "urlopen", open_request)

        with network_support.urlopen_or_skip("https://example.test/asset", method="HEAD"):
            pass

        assert request_methods == ["HEAD"]

    def test_skips_network_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_to_open(url: str, timeout: float) -> None:
            raise OSError("network unavailable")

        monkeypatch.setattr(network_support, "urlopen", fail_to_open)

        with (
            pytest.raises(pytest.skip.Exception, match="Cannot reach"),
            network_support.urlopen_or_skip("https://example.test/asset"),
        ):
            raise AssertionError("A failed request must not yield a response.")

    def test_skips_proxy_statuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def proxy_denied(url: str, timeout: float) -> None:
            raise HTTPError(url, 407, "Proxy Authentication Required", None, None)

        monkeypatch.setattr(network_support, "urlopen", proxy_denied)

        with (
            pytest.raises(pytest.skip.Exception, match="Network or proxy denied"),
            network_support.urlopen_or_skip("https://example.test/asset"),
        ):
            raise AssertionError("A denied request must not yield a response.")

    def test_does_not_skip_missing_asset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def missing_asset(url: str, timeout: float) -> None:
            raise HTTPError(url, 404, "Not Found", None, None)

        monkeypatch.setattr(network_support, "urlopen", missing_asset)

        with pytest.raises(HTTPError) as error, network_support.urlopen_or_skip("https://example.test/missing"):
            raise AssertionError("A missing asset must not yield a response.")

        assert error.value.code == 404


class TestInternetReachable:
    def test_returns_true_when_socket_connects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _DummySocket:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *args: object) -> None:
                pass

        monkeypatch.setattr("tests.support.collection.socket.create_connection", lambda target, timeout: _DummySocket())

        assert collection_support.internet_reachable() is True

    def test_returns_false_on_socket_os_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail_connection(target: tuple[str, int], timeout: float) -> None:
            raise OSError("connection refused")

        monkeypatch.setattr("tests.support.collection.socket.create_connection", fail_connection)

        assert collection_support.internet_reachable() is False


class TestTagTestItems:
    def test_tags_items_by_folder_and_skips_network_when_offline(self, tmp_path: Path) -> None:
        unit_item = _CollectedItem(tmp_path / "unit" / "test_unit.py")
        network_item = _CollectedItem(tmp_path / "network" / "test_network.py")
        integration_item = _CollectedItem(tmp_path / "integration" / "test_integration.py")

        collection_support.tag_test_items(
            [unit_item, network_item, integration_item], tests_root=tmp_path, reachable=False
        )

        assert [m.mark.name for m in unit_item.markers] == ["unit"]
        assert [m.mark.name for m in network_item.markers] == ["network", "skip"]
        assert network_item.markers[1].mark.kwargs["reason"] == "no internet connection to GitHub"
        assert [m.mark.name for m in integration_item.markers] == ["integration"]

    def test_tags_items_by_folder_without_skipping_network_when_online(self, tmp_path: Path) -> None:
        unit_item = _CollectedItem(tmp_path / "unit" / "test_unit.py")
        network_item = _CollectedItem(tmp_path / "network" / "test_network.py")
        integration_item = _CollectedItem(tmp_path / "integration" / "test_integration.py")

        collection_support.tag_test_items(
            [unit_item, network_item, integration_item], tests_root=tmp_path, reachable=True
        )

        assert [m.mark.name for m in unit_item.markers] == ["unit"]
        assert [m.mark.name for m in network_item.markers] == ["network"]
        assert [m.mark.name for m in integration_item.markers] == ["integration"]

    def test_unmatched_items_do_not_receive_tier_markers(self, tmp_path: Path) -> None:
        other_item = _CollectedItem(tmp_path / "other" / "test_other.py")

        collection_support.tag_test_items([other_item], tests_root=tmp_path, reachable=True)

        assert other_item.markers == []

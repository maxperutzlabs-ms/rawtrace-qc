from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import ThermoHelperChecksumError, ThermoHelperDownloadError
from rawtrace_qc.thermo import ThermoHelperState, ThermoHelperStatus
from tests.support import thermo_helper as resolver


def _status(state: ThermoHelperState, path: Path | None = None) -> ThermoHelperStatus:
    return ThermoHelperStatus(
        state=state,
        path=path,
        version=resolver.THERMO_HELPER_SPECIFICATION.version,
        license_accepted=state is ThermoHelperState.READY,
        message=f"status: {state.value}",
    )


def _archive_specification(payload: bytes) -> resolver.ThermoHelperSpecification:
    return replace(
        resolver.THERMO_HELPER_SPECIFICATION,
        asset_name="test-helper-release.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
    )


class TestGetOrDownloadThermoHelperArchive:
    def test_downloads_missing_archive_once_and_reuses_verified_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = b"valid test helper archive"
        specification = _archive_specification(payload)
        cache_directory = tmp_path / "archives"
        downloads: list[Path] = []

        def download_archive(
            destination: Path, *, specification: resolver.ThermoHelperSpecification, timeout: float
        ) -> Path:
            destination.write_bytes(payload)
            downloads.append(destination)
            return destination

        monkeypatch.setattr(resolver, "download_thermo_helper_archive", download_archive)

        first_path = resolver.get_or_download_thermo_helper_archive(
            specification=specification, cache_directory=cache_directory
        )
        second_path = resolver.get_or_download_thermo_helper_archive(
            specification=specification, cache_directory=cache_directory
        )

        assert first_path == second_path == cache_directory / specification.asset_name
        assert first_path.read_bytes() == payload
        assert len(downloads) == 1

    def test_replaces_checksum_invalid_cache_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = b"valid replacement archive"
        specification = _archive_specification(payload)
        cache_directory = tmp_path / "archives"
        cache_directory.mkdir()
        archive_path = cache_directory / specification.asset_name
        archive_path.write_bytes(b"corrupt cache entry")
        downloads: list[Path] = []

        def download_archive(
            destination: Path, *, specification: resolver.ThermoHelperSpecification, timeout: float
        ) -> Path:
            destination.write_bytes(payload)
            downloads.append(destination)
            return destination

        monkeypatch.setattr(resolver, "download_thermo_helper_archive", download_archive)

        result = resolver.get_or_download_thermo_helper_archive(
            specification=specification, cache_directory=cache_directory
        )

        assert result == archive_path
        assert result.read_bytes() == payload
        assert len(downloads) == 1

    def test_does_not_publish_download_with_checksum_mismatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = b"expected archive"
        specification = _archive_specification(payload)
        cache_directory = tmp_path / "archives"

        def download_archive(
            destination: Path, *, specification: resolver.ThermoHelperSpecification, timeout: float
        ) -> Path:
            destination.write_bytes(b"incorrect archive")
            return destination

        monkeypatch.setattr(resolver, "download_thermo_helper_archive", download_archive)

        with pytest.raises(ThermoHelperChecksumError, match="failed SHA-256 verification"):
            resolver.get_or_download_thermo_helper_archive(specification=specification, cache_directory=cache_directory)

        assert not (cache_directory / specification.asset_name).exists()


class TestExpireStaleTestCache:
    @pytest.mark.parametrize(
        ("stamp_age_hours", "expect_purged"), [(25, True), (23, False), (None, True)], ids=["old", "recent", "no-stamp"]
    )
    def test_purges_cache_only_when_stamp_is_missing_or_older_than_max_age(
        self, tmp_path: Path, stamp_age_hours: float | None, expect_purged: bool
    ) -> None:
        cache_root = tmp_path / "thermo-helper"
        cache_root.mkdir()
        (cache_root / "payload.bin").write_bytes(b"cached")
        if stamp_age_hours is not None:
            stamp_time = time.time() - timedelta(hours=stamp_age_hours).total_seconds()
            (cache_root / ".cache-created-at").write_text(str(stamp_time), encoding="utf-8")

        purged = resolver.expire_stale_test_cache(cache_root=cache_root)

        assert purged is expect_purged
        assert (cache_root / "payload.bin").exists() is not expect_purged
        assert (cache_root / ".cache-created-at").is_file()

    def test_creates_cache_root_with_stamp_when_missing(self, tmp_path: Path) -> None:
        cache_root = tmp_path / "thermo-helper"

        purged = resolver.expire_stale_test_cache(cache_root=cache_root)

        assert purged is False
        assert (cache_root / ".cache-created-at").is_file()


class TestResolveIntegrationThermoHelper:
    @pytest.fixture(autouse=True)
    def force_windows_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")

    def test_uses_ready_per_user_helper_without_touching_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = tmp_path / "user" / "ThermoScanHeaderExtractor.exe"
        status_calls: list[Path | None] = []

        def mock_status(*, data_directory=None, **kwargs):
            status_calls.append(data_directory)
            return _status(ThermoHelperState.READY, executable)

        monkeypatch.setattr(resolver, "get_thermo_helper_status", mock_status)
        monkeypatch.setattr(resolver, "install_thermo_helper", pytest.fail)
        monkeypatch.setattr(resolver, "accept_thermo_license", pytest.fail)
        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", pytest.fail)

        result = resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

        assert result == executable
        assert status_calls == [None]

    def test_unlicensed_user_helper_uses_warm_cache_without_actions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_executable = tmp_path / "user" / "helper.exe"
        executable = tmp_path / "cache" / "helper.exe"
        status_calls = iter(
            [
                _status(ThermoHelperState.UNLICENSED, user_executable),
                _status(ThermoHelperState.READY, executable),
            ]
        )
        monkeypatch.setattr(resolver, "get_thermo_helper_status", lambda **kwargs: next(status_calls))
        monkeypatch.setattr(resolver, "install_thermo_helper", pytest.fail)
        monkeypatch.setattr(resolver, "accept_thermo_license", pytest.fail)
        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", pytest.fail)

        result = resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache-root")

        assert result == executable

    def test_installs_then_accepts_only_when_each_status_requires_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executable = tmp_path / "cache" / "helper.exe"
        statuses = iter(
            [
                _status(ThermoHelperState.NOT_INSTALLED),
                _status(ThermoHelperState.NOT_INSTALLED),
                _status(ThermoHelperState.UNLICENSED, executable),
                _status(ThermoHelperState.READY, executable),
            ]
        )
        archive_path = tmp_path / "cache" / "archives" / "helper.zip"
        install_calls: list[tuple[Path, dict[str, object]]] = []
        accept_calls: list[tuple[Path, dict[str, object]]] = []
        monkeypatch.setattr(resolver, "get_thermo_helper_status", lambda **kwargs: next(statuses))

        def mock_install(archive: Path, **kwargs: object) -> None:
            install_calls.append((archive, kwargs))

        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", lambda **kwargs: archive_path)
        monkeypatch.setattr(resolver, "install_thermo_helper", mock_install)
        monkeypatch.setattr(
            resolver, "accept_thermo_license", lambda path, **kwargs: accept_calls.append((path, kwargs))
        )

        result = resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

        assert result == executable
        assert install_calls == [
            (
                archive_path,
                {
                    "data_directory": (tmp_path / "cache").resolve(),
                    "specification": resolver.THERMO_HELPER_SPECIFICATION,
                    "timeout": 60.0,
                },
            )
        ]
        assert accept_calls == [
            (
                executable,
                {
                    "data_directory": (tmp_path / "cache").resolve(),
                    "specification": resolver.THERMO_HELPER_SPECIFICATION,
                },
            )
        ]

    def test_skips_transient_http_download_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        statuses = iter(
            [
                _status(ThermoHelperState.NOT_INSTALLED),
                _status(ThermoHelperState.NOT_INSTALLED),
            ]
        )
        download_error = ThermoHelperDownloadError("Temporary release outage.")
        download_error.__cause__ = HTTPError("https://example.test/helper.zip", 503, "Unavailable", None, None)
        monkeypatch.setattr(resolver, "get_thermo_helper_status", lambda **kwargs: next(statuses))

        def fail_download(
            _destination: Path, *, specification: resolver.ThermoHelperSpecification, timeout: float
        ) -> Path:
            raise download_error

        monkeypatch.setattr(resolver, "download_thermo_helper_archive", fail_download)

        with pytest.raises(pytest.skip.Exception, match="Network or proxy"):
            resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

    def test_checksum_failure_is_not_skipped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        statuses = iter(
            [
                _status(ThermoHelperState.NOT_INSTALLED),
                _status(ThermoHelperState.NOT_INSTALLED),
            ]
        )
        monkeypatch.setattr(resolver, "get_thermo_helper_status", lambda **kwargs: next(statuses))
        monkeypatch.setattr(
            resolver,
            "get_or_download_thermo_helper_archive",
            lambda **kwargs: (_ for _ in ()).throw(ThermoHelperChecksumError("Pinned digest did not match.")),
        )

        with pytest.raises(ThermoHelperChecksumError, match="digest did not match"):
            resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

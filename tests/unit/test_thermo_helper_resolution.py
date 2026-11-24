from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError
from zipfile import ZipFile

import pytest
from rawtrace_qc import environment
from rawtrace_qc.errors import (
    ThermoHelperChecksumError,
    ThermoHelperDownloadError,
    ThermoHelperLicenseError,
)
from rawtrace_qc.thermo import ThermoHelperState, ThermoHelperStatus
from tests.support import thermo_helper as resolver


def _status(state: ThermoHelperState, path: Path | None = None) -> ThermoHelperStatus:
    return ThermoHelperStatus(
        state=state,
        path=path,
        version=resolver.WIN_X64_SPECIFICATION.version,
        license_accepted=state is ThermoHelperState.READY,
        message=f"status: {state.value}",
    )


def _archive_specification(payload: bytes) -> resolver.ThermoHelperSpecification:
    return replace(
        resolver.WIN_X64_SPECIFICATION,
        asset_name="test-helper-release.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _helper_archive(directory: Path) -> tuple[Path, resolver.ThermoHelperSpecification]:
    archive_path = directory / "helper.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(resolver.WIN_X64_SPECIFICATION.executable_name, b"MZmock-helper")
    return archive_path, _archive_specification(archive_path.read_bytes())


class TestResolveSpecificationOrSkip:
    def test_returns_win_x64_specification_on_supported_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")

        assert resolver.resolve_specification_or_skip() == resolver.WIN_X64_SPECIFICATION

    @pytest.mark.parametrize(("platform_name", "machine"), [("linux", "riscv64"), ("freebsd13", "amd64")])
    def test_skips_on_unsupported_or_unrecognized_host_and_names_the_host(
        self, monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str
    ) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: platform_name)
        monkeypatch.setattr(environment, "get_machine", lambda: machine)

        with pytest.raises(pytest.skip.Exception, match=rf"{platform_name!r} and machine {machine!r}"):
            resolver.resolve_specification_or_skip()


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
        monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")

    def test_uses_ready_per_user_helper_without_touching_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = tmp_path / "user" / "ThermoScanHeaderExtractor.exe"
        monkeypatch.setattr(
            resolver, "get_thermo_helper_status", lambda **kwargs: _status(ThermoHelperState.READY, executable)
        )
        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", pytest.fail)
        monkeypatch.setattr(resolver, "locate_thermo_helper", pytest.fail)

        result = resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

        assert result == executable
        assert not (tmp_path / "cache").exists()

    def test_extracts_the_archive_into_the_cache_once_and_reuses_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_path, specification = _helper_archive(tmp_path)
        downloads: list[dict[str, object]] = []

        def get_archive(**kwargs: object) -> Path:
            downloads.append(kwargs)
            return archive_path

        monkeypatch.setattr(
            resolver, "get_thermo_helper_status", lambda **kwargs: _status(ThermoHelperState.NOT_INSTALLED)
        )
        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", get_archive)
        monkeypatch.setattr(resolver, "locate_thermo_helper", lambda explicit_path, **kwargs: explicit_path)

        first = resolver.resolve_integration_thermo_helper(specification, cache_root=tmp_path / "cache")
        second = resolver.resolve_integration_thermo_helper(specification, cache_root=tmp_path / "cache")

        assert first == second
        assert first.is_relative_to((tmp_path / "cache").resolve())
        assert first.read_bytes() == b"MZmock-helper"
        assert len(downloads) == 1

    def test_checks_the_cached_helper_by_explicit_path_and_skips_without_accepting_when_unlicensed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive_path, specification = _helper_archive(tmp_path)
        located: list[tuple[Path, dict[str, object]]] = []

        def locate_unlicensed(explicit_path: Path, **kwargs: object) -> Path:
            located.append((explicit_path, kwargs))
            raise ThermoHelperLicenseError("The Thermo license agreement has not been accepted.")

        monkeypatch.setattr(
            resolver, "get_thermo_helper_status", lambda **kwargs: _status(ThermoHelperState.UNLICENSED)
        )
        monkeypatch.setattr(resolver, "get_or_download_thermo_helper_archive", lambda **kwargs: archive_path)
        monkeypatch.setattr(resolver, "locate_thermo_helper", locate_unlicensed)

        with pytest.raises(pytest.skip.Exception, match="thermo accept-license"):
            resolver.resolve_integration_thermo_helper(specification, cache_root=tmp_path / "cache")

        [(explicit_path, kwargs)] = located
        assert explicit_path.read_bytes() == b"MZmock-helper"
        assert kwargs == {"specification": specification}

    def test_skips_transient_http_download_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        download_error = ThermoHelperDownloadError("Temporary release outage.")
        download_error.__cause__ = HTTPError("https://example.test/helper.zip", 503, "Unavailable", None, None)
        monkeypatch.setattr(
            resolver, "get_thermo_helper_status", lambda **kwargs: _status(ThermoHelperState.NOT_INSTALLED)
        )

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
        monkeypatch.setattr(
            resolver, "get_thermo_helper_status", lambda **kwargs: _status(ThermoHelperState.NOT_INSTALLED)
        )
        monkeypatch.setattr(
            resolver,
            "get_or_download_thermo_helper_archive",
            lambda **kwargs: (_ for _ in ()).throw(ThermoHelperChecksumError("Pinned digest did not match.")),
        )

        with pytest.raises(ThermoHelperChecksumError, match="digest did not match"):
            resolver.resolve_integration_thermo_helper(cache_root=tmp_path / "cache")

"""Unit tests for ThermoScanHeaderExtractor archive installation."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from rawtrace_qc import environment
from rawtrace_qc.environment import helper_tool_directory
from rawtrace_qc.errors import (
    ThermoHelperArchiveError,
    ThermoHelperChecksumError,
    ThermoHelperDownloadError,
    ThermoHelperInstallationError,
    ThermoHelperInstallConflictError,
    UnsupportedPlatformError,
)
from rawtrace_qc.thermo import (
    THERMO_HELPER_SPECIFICATION,
    download_thermo_helper_archive,
    extract_thermo_helper_archive,
    install_thermo_helper,
    verify_thermo_helper_archive,
)
from rawtrace_qc.thermo import installation as installation_module
from rawtrace_qc.thermo.specification import ThermoHelperSpecification


@pytest.fixture(autouse=True)
def mock_windows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "get_platform", lambda: "win32")


def _create_archive(
    directory: Path, members: dict[str, bytes] | None = None, *, filename: str = "helper.zip"
) -> tuple[Path, ThermoHelperSpecification]:
    archive_path = directory / filename
    archive_members = members or {
        THERMO_HELPER_SPECIFICATION.executable_name: b"MZmock-helper",
        "ThermoScanHeaderExtractor.dll": b"mock-dependency",
    }
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in archive_members.items():
            archive.writestr(name, content)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    return archive_path, replace(THERMO_HELPER_SPECIFICATION, sha256=digest)


def _managed_directory(data_directory: Path, specification: ThermoHelperSpecification) -> Path:
    return helper_tool_directory(specification.tool_name, specification.version, data_directory=data_directory)


def _assert_no_staging_directories(data_directory: Path, specification: ThermoHelperSpecification) -> None:
    staging_parent = _managed_directory(data_directory, specification).parent
    if staging_parent.exists():
        assert tuple(staging_parent.glob(f".{specification.version}-install-*")) == ()


class TestInstallThermoHelper:
    def test_rejects_non_windows_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")

        with pytest.raises(UnsupportedPlatformError, match="requires Windows"):
            install_thermo_helper()

    def test_installs_local_archive_atomically_without_accepting_license(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(tmp_path)
        data_directory = tmp_path / "appdata"

        executable = install_thermo_helper(archive_path, data_directory=data_directory, specification=specification)

        managed_directory = _managed_directory(data_directory, specification)
        assert executable == managed_directory / specification.executable_name
        assert executable.read_bytes() == b"MZmock-helper"
        assert (managed_directory / "ThermoScanHeaderExtractor.dll").read_bytes() == b"mock-dependency"
        assert archive_path.is_file()
        _assert_no_staging_directories(data_directory, specification)

    def test_installs_downloaded_archive_through_the_same_verified_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source_archive, specification = _create_archive(tmp_path)
        data_directory = tmp_path / "appdata"
        downloads: list[Path] = []

        def substitute_download(destination: Path, *, specification: ThermoHelperSpecification, timeout: float) -> Path:
            assert timeout == 60.0
            shutil.copyfile(source_archive, destination)
            downloads.append(destination)
            return destination

        monkeypatch.setattr(installation_module, "download_thermo_helper_archive", substitute_download)

        executable = install_thermo_helper(data_directory=data_directory, specification=specification)

        assert executable.is_file()
        assert len(downloads) == 1

    def test_rejects_checksum_mismatch_and_cleans_staging_state(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(tmp_path)
        wrong_specification = replace(specification, sha256="0" * 64)
        data_directory = tmp_path / "appdata"

        with pytest.raises(ThermoHelperChecksumError, match="failed SHA-256 verification"):
            install_thermo_helper(
                archive_path,
                data_directory=data_directory,
                specification=wrong_specification,
            )

        assert not _managed_directory(data_directory, wrong_specification).exists()
        _assert_no_staging_directories(data_directory, wrong_specification)

    def test_rejects_corrupt_archive_and_leaves_no_managed_directory(self, tmp_path: Path) -> None:
        archive_path = tmp_path / "corrupt.zip"
        archive_path.write_bytes(b"not a zip archive")
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        specification = replace(THERMO_HELPER_SPECIFICATION, sha256=digest)
        data_directory = tmp_path / "appdata"

        with pytest.raises(ThermoHelperArchiveError, match="Could not safely extract"):
            install_thermo_helper(
                archive_path,
                data_directory=data_directory,
                specification=specification,
            )

        assert not _managed_directory(data_directory, specification).exists()
        _assert_no_staging_directories(data_directory, specification)

    def test_rejects_path_traversal_archive_before_writing_outside_target(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(
            tmp_path,
            {
                THERMO_HELPER_SPECIFICATION.executable_name: b"MZmock-helper",
                "../../escape.txt": b"outside",
            },
            filename="traversal.zip",
        )
        data_directory = tmp_path / "appdata"

        with pytest.raises(ThermoHelperArchiveError, match="unsafe member path"):
            install_thermo_helper(
                archive_path,
                data_directory=data_directory,
                specification=specification,
            )

        assert not (tmp_path / "escape.txt").exists()
        assert not _managed_directory(data_directory, specification).exists()
        _assert_no_staging_directories(data_directory, specification)

    def test_interrupted_publish_leaves_no_partial_install_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        archive_path, specification = _create_archive(tmp_path)
        data_directory = tmp_path / "appdata"

        def interrupt_publish(_payload_directory: Path, _install_directory: Path) -> None:
            raise OSError("simulated interrupted install")

        monkeypatch.setattr(installation_module, "_publish_install", interrupt_publish)

        with pytest.raises(ThermoHelperInstallationError, match="Could not atomically install"):
            install_thermo_helper(
                archive_path,
                data_directory=data_directory,
                specification=specification,
            )

        assert not _managed_directory(data_directory, specification).exists()
        _assert_no_staging_directories(data_directory, specification)

    def test_reinstalling_identical_archive_is_idempotent(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(tmp_path)
        data_directory = tmp_path / "appdata"
        first = install_thermo_helper(
            archive_path,
            data_directory=data_directory,
            specification=specification,
        )
        first_contents = first.read_bytes()

        second = install_thermo_helper(
            archive_path,
            data_directory=data_directory,
            specification=specification,
        )

        assert second == first
        assert second.read_bytes() == first_contents
        _assert_no_staging_directories(data_directory, specification)

    def test_refuses_to_overwrite_different_archive_at_same_version(self, tmp_path: Path) -> None:
        first_archive, first_specification = _create_archive(tmp_path, filename="first.zip")
        data_directory = tmp_path / "appdata"
        executable = install_thermo_helper(
            first_archive,
            data_directory=data_directory,
            specification=first_specification,
        )
        second_archive, second_specification = _create_archive(
            tmp_path,
            {THERMO_HELPER_SPECIFICATION.executable_name: b"MZdifferent-helper"},
            filename="second.zip",
        )
        assert second_specification.version == first_specification.version

        with pytest.raises(ThermoHelperInstallConflictError, match="refusing to silently overwrite"):
            install_thermo_helper(
                second_archive,
                data_directory=data_directory,
                specification=second_specification,
            )

        assert executable.read_bytes() == b"MZmock-helper"

    def test_network_failure_from_download_function_cleans_staging_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        specification = THERMO_HELPER_SPECIFICATION
        data_directory = tmp_path / "appdata"

        def fail_download(
            _destination: Path,
            *,
            specification: ThermoHelperSpecification,
            timeout: float,
        ) -> Path:
            raise ThermoHelperDownloadError("Network or proxy failure while downloading.")

        monkeypatch.setattr(installation_module, "download_thermo_helper_archive", fail_download)

        with pytest.raises(ThermoHelperDownloadError, match="Network or proxy failure"):
            install_thermo_helper(
                data_directory=data_directory,
                specification=specification,
            )

        assert not _managed_directory(data_directory, specification).exists()
        _assert_no_staging_directories(data_directory, specification)


class TestDownloadThermoHelperArchive:
    @pytest.mark.parametrize(
        ("download_error", "message"),
        [
            (URLError("offline"), "Network or proxy failure"),
            (HTTPError("https://example.test/helper.zip", 503, "Unavailable", None, None), "HTTP 503"),
        ],
    )
    def test_reports_network_and_http_failures(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        download_error: Exception,
        message: str,
    ) -> None:
        destination = tmp_path / "download" / "helper.zip"

        def fail_request(_url: str, *, timeout: float) -> None:
            raise download_error

        monkeypatch.setattr(installation_module, "urlopen", fail_request)

        with pytest.raises(ThermoHelperDownloadError, match=message):
            download_thermo_helper_archive(destination)

        assert not destination.exists()


class TestVerifyThermoHelperArchive:
    def test_returns_digest_for_valid_archive(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(tmp_path)

        digest = verify_thermo_helper_archive(archive_path, specification=specification)

        assert digest == specification.sha256


class TestExtractThermoHelperArchive:
    def test_rejects_existing_extraction_target(self, tmp_path: Path) -> None:
        archive_path, specification = _create_archive(tmp_path)
        target_directory = tmp_path / "existing"
        target_directory.mkdir()

        with pytest.raises(ThermoHelperArchiveError, match="already exists"):
            extract_thermo_helper_archive(
                archive_path,
                target_directory,
                specification=specification,
            )

        assert tuple(target_directory.iterdir()) == ()

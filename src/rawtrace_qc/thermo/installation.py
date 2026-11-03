"""Download, validate, and install pinned Thermo helper archives."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import BadZipFile, LargeZipFile, ZipFile, ZipInfo

from rawtrace_qc.errors import (
    ThermoHelperArchiveError,
    ThermoHelperChecksumError,
    ThermoHelperDownloadError,
    ThermoHelperInstallationError,
    ThermoHelperInstallConflictError,
)
from rawtrace_qc.thermo.locator import managed_thermo_helper_directory
from rawtrace_qc.thermo.specification import (
    ThermoHelperSpecification,
    resolve_thermo_helper_specification,
)

_INSTALL_MANIFEST_NAME = ".rawtrace-qc-thermo-helper.json"


def install_thermo_helper(
    archive_path: Path | str | None = None,
    *,
    data_directory: Path | str | None = None,
    specification: ThermoHelperSpecification | None = None,
    timeout: float = 60.0,
    overwrite: bool = False,
) -> Path:
    """Install the pinned Thermo helper from a download or local ZIP archive.

    Both sources are copied or downloaded to a temporary file, verified against
    the pinned SHA-256 digest, and safely extracted into a temporary directory
    before the complete helper directory is atomically published. A versioned
    install directory without the helper executable counts as not installed and
    is replaced. Installation never executes the helper or changes its Thermo
    license marker.

    A matching earlier installation is kept as it is, and any other content at
    the install location is refused, unless `overwrite` is set. The existing
    content is only removed after the new archive has been verified.

    Args:
        archive_path: Local ZIP archive to install. If None (default), download
            the archive from the pinned release URL.
        data_directory: Application data directory override. If None (default),
            use the platform-specific user data directory.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.
        timeout: Maximum network timeout in seconds. Defaults to 60.0.
        overwrite: If True, replace whatever exists at the install location,
            including a broken helper that still matches the pinned release.
            Defaults to False.

    Returns:
        The managed ThermoScanHeaderExtractor executable path.

    Raises:
        UnsupportedPlatformError: If the current runtime has no pinned helper
            release.
        ThermoHelperDownloadError: If the pinned archive cannot be downloaded.
        ThermoHelperChecksumError: If the source archive checksum is incorrect.
        ThermoHelperArchiveError: If the source is not a safe ZIP containing
            the expected executable.
        ThermoHelperInstallConflictError: If `overwrite` is False and the
            versioned install directory already contains a helper executable
            from a different or unmanaged installation.
        ThermoHelperInstallationError: If staging or atomic publication fails.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()

    runtime_directory = managed_thermo_helper_directory(
        specification, data_directory=data_directory
    ).expanduser()
    install_parent = runtime_directory.parent.resolve()
    install_directory = install_parent / runtime_directory.name

    if (
        archive_path is None
        and not overwrite
        and _path_exists(install_directory)
        and not _is_missing_executable(install_directory, specification)
    ):
        return _existing_install_executable(install_directory, specification)

    try:
        install_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{install_directory.name}-install-",
            dir=install_parent,
        ) as temporary_name:
            temporary_directory = Path(temporary_name)
            staged_archive = temporary_directory / "helper.zip"
            if archive_path is None:
                download_thermo_helper_archive(
                    staged_archive,
                    specification=specification,
                    timeout=timeout,
                )
            else:
                _copy_local_archive(Path(archive_path).expanduser(), staged_archive)

            staged_executable = extract_thermo_helper_archive(
                staged_archive,
                temporary_directory / "extracted",
                specification=specification,
            )
            payload_directory = staged_executable.parent
            _write_install_manifest(payload_directory, specification)

            replace_existing = _path_exists(install_directory)
            if (
                replace_existing
                and not overwrite
                and not _is_missing_executable(install_directory, specification)
            ):
                return _existing_install_executable(install_directory, specification)

            try:
                if replace_existing:
                    # The staging directory's cleanup removes the moved folder.
                    install_directory.rename(temporary_directory / "replaced")
                _publish_install(payload_directory, install_directory)
            except OSError as error:
                if (
                    not overwrite
                    and _path_exists(install_directory)
                    and not _is_missing_executable(install_directory, specification)
                ):
                    return _existing_install_executable(
                        install_directory, specification
                    )
                raise ThermoHelperInstallationError(
                    f"Could not atomically install ThermoScanHeaderExtractor "
                    f"v{specification.version} at {install_directory}: {error}. "
                    "Check that the managed data directory is writable and that "
                    "the helper is not running."
                ) from error

            return install_directory / specification.executable_name
    except ThermoHelperInstallationError:
        raise
    except OSError as error:
        raise ThermoHelperInstallationError(
            f"Could not stage ThermoScanHeaderExtractor v{specification.version} "
            f"for installation at {install_directory}: {error}. Check that the "
            "managed data directory is writable and has sufficient space."
        ) from error


def download_thermo_helper_archive(
    destination: Path | str,
    *,
    specification: ThermoHelperSpecification | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download the pinned release archive to a caller-selected temporary path.

    This function only handles network transfer. It does not choose the
    managed installation directory, verify the checksum, or extract files.

    Args:
        destination: New path for the downloaded archive. Existing paths are
            not overwritten.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.
        timeout: Maximum network timeout in seconds. Defaults to 60.0.

    Returns:
        The path containing the downloaded archive.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
        ThermoHelperDownloadError: If the server, network, or proxy prevents
            the download from completing.
        ThermoHelperInstallationError: If the temporary destination cannot be
            created or already exists.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()

    if timeout <= 0:
        raise ThermoHelperDownloadError(
            f"Download timeout must be greater than zero, got {timeout!r}."
        )

    archive_path = Path(destination).expanduser()
    if _path_exists(archive_path):
        raise ThermoHelperInstallationError(
            f"Download destination {archive_path} already exists; use a new "
            "temporary path."
        )
    try:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ThermoHelperInstallationError(
            f"Could not create temporary download directory "
            f"{archive_path.parent}: {error}."
        ) from error

    try:
        response = urlopen(specification.download_url, timeout=timeout)
    except HTTPError as error:
        raise ThermoHelperDownloadError(
            f"HTTP {error.code} while downloading the pinned Thermo helper "
            f"archive from {specification.download_url!r}. Check release "
            "availability and proxy settings."
        ) from error
    except URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError):
            raise ThermoHelperDownloadError(
                f"Timed out after {timeout} seconds downloading the pinned "
                "Thermo helper archive. Check network and proxy settings."
            ) from error
        raise ThermoHelperDownloadError(
            f"Network or proxy failure while downloading the pinned Thermo "
            f"helper archive: {reason}. Check connectivity and proxy settings."
        ) from error
    except TimeoutError as error:
        raise ThermoHelperDownloadError(
            f"Timed out after {timeout} seconds downloading the pinned Thermo "
            "helper archive. Check network and proxy settings."
        ) from error
    except OSError as error:
        raise ThermoHelperDownloadError(
            f"Could not connect to the pinned Thermo helper release at "
            f"{specification.download_url!r}: {error}. Check network and "
            "proxy settings."
        ) from error

    created_destination = False
    try:
        with response:
            try:
                output = archive_path.open("xb")
            except OSError as error:
                raise ThermoHelperInstallationError(
                    f"Could not create temporary download file {archive_path}: {error}."
                ) from error
            created_destination = True
            with output:
                shutil.copyfileobj(response, output)
    except BaseException as error:
        if created_destination:
            try:
                archive_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise ThermoHelperDownloadError(
                    f"The download failed and its partial temporary file at "
                    f"{archive_path} could not be removed: {cleanup_error}."
                ) from cleanup_error
        if isinstance(error, ThermoHelperInstallationError):
            raise
        if isinstance(error, HTTPError):
            raise ThermoHelperDownloadError(
                f"HTTP {error.code} while downloading the pinned Thermo helper "
                f"archive from {specification.download_url!r}. Check release "
                "availability and proxy settings."
            ) from error
        if isinstance(error, URLError):
            raise ThermoHelperDownloadError(
                f"Network or proxy failure while receiving the pinned Thermo "
                f"helper archive: {error.reason}. Check connectivity and "
                "proxy settings."
            ) from error
        if isinstance(error, TimeoutError):
            raise ThermoHelperDownloadError(
                f"Timed out after {timeout} seconds while receiving the pinned "
                "Thermo helper archive. Check network and proxy settings."
            ) from error
        if isinstance(error, OSError):
            raise ThermoHelperDownloadError(
                f"The download of the pinned Thermo helper archive failed while "
                f"writing its temporary file: {error}. Check network access and "
                "temporary storage."
            ) from error
        raise

    return archive_path


def verify_thermo_helper_archive(
    archive_path: Path | str,
    *,
    specification: ThermoHelperSpecification | None = None,
) -> str:
    """Verify a helper archive against the pinned SHA-256 checksum.

    Args:
        archive_path: Local path to the downloaded or user-supplied archive.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.

    Returns:
        The verified lowercase SHA-256 digest.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
        ThermoHelperArchiveError: If the archive cannot be read.
        ThermoHelperChecksumError: If its digest differs from the pinned value.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()

    path = Path(archive_path).expanduser()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ThermoHelperArchiveError(
            f"Could not read Thermo helper archive {path} for checksum "
            f"verification: {error}. Check that the file exists and is readable."
        ) from error

    actual = digest.hexdigest()
    expected = specification.sha256.casefold()
    if actual.casefold() != expected:
        raise ThermoHelperChecksumError(
            f"Thermo helper archive {path} failed SHA-256 verification: "
            f"expected {expected!r}, received {actual!r}. Only the archive "
            f"{specification.asset_name!r} of release v{specification.version} "
            "is accepted; obtain it again from a trusted source."
        )
    return actual


def extract_thermo_helper_archive(
    archive_path: Path | str,
    target_directory: Path | str,
    *,
    specification: ThermoHelperSpecification | None = None,
) -> Path:
    """Verify and safely extract the helper into a new staging directory.

    Archive paths are validated before any member is written. Absolute paths,
    traversal components, Windows alternate-stream paths, and symbolic links
    are rejected. On failure, the newly created extraction directory is removed.

    Args:
        archive_path: Local path to the downloaded or user-supplied archive.
        target_directory: New directory used for temporary extraction.
        specification: Pinned helper release metadata. If None (default),
            resolve the specification for the current host runtime.

    Returns:
        The extracted helper executable path within `target_directory`.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
        ThermoHelperChecksumError: If the archive checksum does not match.
        ThermoHelperArchiveError: If the archive is corrupt, unsafe, or does
            not contain exactly one expected executable.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()

    archive_file = Path(archive_path).expanduser()
    requested_root = Path(target_directory).expanduser()
    if _path_exists(requested_root):
        raise ThermoHelperArchiveError(
            f"Extraction target {requested_root} already exists; use a new "
            "temporary directory."
        )
    extraction_root = requested_root.resolve()
    if _path_exists(extraction_root):
        raise ThermoHelperArchiveError(
            f"Resolved extraction target {extraction_root} already exists; "
            "use a new temporary directory."
        )

    verify_thermo_helper_archive(archive_file, specification=specification)
    extraction_created = False
    try:
        with ZipFile(archive_file) as archive:
            members = _validated_archive_members(archive, extraction_root)
            executable_members = [
                (info, relative_path)
                for info, relative_path in members
                if not info.is_dir()
                and relative_path.name == specification.executable_name
            ]
            if len(executable_members) != 1:
                raise ThermoHelperArchiveError(
                    f"Thermo helper archive must contain exactly one "
                    f"{specification.executable_name!r}; found "
                    f"{len(executable_members)}."
                )

            executable_relative = executable_members[0][1]
            payload_relative = executable_relative.parent
            manifest_relative = (
                PurePosixPath(_INSTALL_MANIFEST_NAME)
                if payload_relative == PurePosixPath(".")
                else payload_relative / _INSTALL_MANIFEST_NAME
            )
            member_names = {
                relative_path.as_posix().casefold() for _, relative_path in members
            }
            if manifest_relative.as_posix().casefold() in member_names:
                raise ThermoHelperArchiveError(
                    f"Thermo helper archive contains reserved installation file "
                    f"{manifest_relative.as_posix()!r}."
                )

            extraction_root.mkdir(parents=True, exist_ok=False)
            extraction_created = True
            for info, relative_path in members:
                output_path = _checked_output_path(extraction_root, relative_path)
                if info.is_dir():
                    output_path.mkdir(parents=True, exist_ok=True)
                    continue
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, output_path.open("xb") as output:
                    shutil.copyfileobj(source, output)

            executable_path = extraction_root.joinpath(*executable_relative.parts)
            if not executable_path.is_file():
                raise ThermoHelperArchiveError(
                    f"Thermo helper archive did not extract "
                    f"{specification.executable_name!r} as a regular file."
                )
            return executable_path
    except ThermoHelperInstallationError:
        if extraction_created:
            shutil.rmtree(extraction_root, ignore_errors=True)
        raise
    except (
        BadZipFile,
        LargeZipFile,
        EOFError,
        OSError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as error:
        if extraction_created:
            shutil.rmtree(extraction_root, ignore_errors=True)
        raise ThermoHelperArchiveError(
            f"Could not safely extract Thermo helper archive {archive_file}: "
            f"{error}. Obtain a valid, unencrypted ZIP archive."
        ) from error


def _copy_local_archive(source_path: Path, destination: Path) -> None:
    if not source_path.is_file():
        raise ThermoHelperArchiveError(
            f"Local Thermo helper archive {source_path} does not exist or is "
            "not a regular file. Select a readable ZIP archive."
        )
    try:
        with source_path.open("rb") as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output)
    except OSError as error:
        destination.unlink(missing_ok=True)
        raise ThermoHelperArchiveError(
            f"Could not stage local Thermo helper archive {source_path}: "
            f"{error}. Check that the archive is readable and the data "
            "directory is writable."
        ) from error


def _validated_archive_members(
    archive: ZipFile,
    extraction_root: Path,
) -> list[tuple[ZipInfo, PurePosixPath]]:
    members: list[tuple[ZipInfo, PurePosixPath]] = []
    seen_paths: set[PurePosixPath] = set()
    seen_casefolded: set[str] = set()
    for info in archive.infolist():
        relative_path = _safe_archive_relative_path(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ThermoHelperArchiveError(
                f"Thermo helper archive contains symbolic link "
                f"{info.filename!r}; links are not permitted."
            )
        folded_path = relative_path.as_posix().casefold()
        if relative_path in seen_paths or folded_path in seen_casefolded:
            raise ThermoHelperArchiveError(
                f"Thermo helper archive contains duplicate path {info.filename!r}."
            )
        seen_paths.add(relative_path)
        seen_casefolded.add(folded_path)
        _checked_output_path(extraction_root, relative_path)
        members.append((info, relative_path))
    if not members:
        raise ThermoHelperArchiveError("Thermo helper archive is empty.")
    return members


def _safe_archive_relative_path(member_name: str) -> PurePosixPath:
    normalized_name = member_name.replace("\\", "/")
    relative_path = PurePosixPath(normalized_name)
    windows_path = PureWindowsPath(normalized_name)
    if (
        not normalized_name
        or "\x00" in normalized_name
        or relative_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part == ".." for part in relative_path.parts)
        or any(":" in part for part in relative_path.parts)
        or not relative_path.parts
    ):
        raise ThermoHelperArchiveError(
            f"Thermo helper archive contains unsafe member path "
            f"{member_name!r}; only relative paths inside the extraction "
            "directory are allowed."
        )
    return relative_path


def _checked_output_path(root: Path, relative_path: PurePosixPath) -> Path:
    output_path = root.joinpath(*relative_path.parts).resolve()
    try:
        output_path.relative_to(root)
    except ValueError as error:
        raise ThermoHelperArchiveError(
            f"Thermo helper archive member {relative_path.as_posix()!r} "
            "would write outside the extraction directory."
        ) from error
    return output_path


def _write_install_manifest(
    payload_directory: Path,
    specification: ThermoHelperSpecification,
) -> None:
    manifest_path = payload_directory / _INSTALL_MANIFEST_NAME
    manifest = {
        "version": specification.version,
        "runtime": specification.runtime,
        "sha256": specification.sha256.casefold(),
    }
    try:
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as error:
        raise ThermoHelperInstallationError(
            f"Could not write installation metadata in {payload_directory}: "
            f"{error}. Check that the temporary directory is writable."
        ) from error


def _existing_install_executable(
    install_directory: Path,
    specification: ThermoHelperSpecification,
) -> Path:
    if install_directory.is_symlink() or not install_directory.is_dir():
        raise ThermoHelperInstallConflictError(
            f"Managed Thermo helper location {install_directory} already exists "
            "but is not a regular installation directory; refusing to overwrite it. "
            "Install again with overwrite enabled to replace it."
        )

    manifest_path = install_directory / _INSTALL_MANIFEST_NAME
    executable_path = install_directory / specification.executable_name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ThermoHelperInstallConflictError(
            f"Managed Thermo helper location {install_directory} already exists "
            "without valid rawtrace-qc installation metadata; refusing to "
            "overwrite it. Check the existing directory, then install again with "
            "overwrite enabled."
        ) from error

    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != specification.version
        or manifest.get("runtime") != specification.runtime
        or manifest.get("sha256") != specification.sha256.casefold()
        or executable_path.is_symlink()
        or not executable_path.is_file()
    ):
        raise ThermoHelperInstallConflictError(
            f"Managed Thermo helper location {install_directory} does not match "
            f"the pinned release v{specification.version} for runtime "
            f"{specification.runtime!r}; refusing to silently overwrite a different "
            "or incomplete installation. Install again with overwrite enabled to "
            "replace it."
        )
    return executable_path


def _is_missing_executable(
    install_directory: Path,
    specification: ThermoHelperSpecification,
) -> bool:
    return (
        install_directory.is_dir()
        and not install_directory.is_symlink()
        and not _path_exists(install_directory / specification.executable_name)
    )


def _publish_install(payload_directory: Path, install_directory: Path) -> None:
    payload_directory.rename(install_directory)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()

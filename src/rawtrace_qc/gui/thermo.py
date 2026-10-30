"""Install and locate the optional ThermScanHeaderExtractor executable."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from rawtrace_qc.environment import helper_tool_directory
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.gui.config import ThermoToolSettings
from rawtrace_qc.thermo import THERMO_HELPER_RELEASE

THERMO_HELPER_SPECIFICATION = THERMO_HELPER_RELEASE.specification("win-x64")


class ThermoToolManager:
    """Resolve or download a configured Thermo header-extractor executable."""

    def __init__(
        self,
        settings: ThermoToolSettings,
        install_directory: Path | None = None,
    ) -> None:
        """Create a manager using helper settings and an optional install root.

        Args:
            settings: Thermo helper download and executable settings.
            install_directory: Explicit install directory. Defaults to None.
        """
        self.settings = settings
        self.install_directory = (
            (
                Path(install_directory)
                if install_directory is not None
                else helper_tool_directory(
                    "thermoscanheaderextractor",
                    THERMO_HELPER_SPECIFICATION.version,
                )
            )
            .expanduser()
            .resolve()
        )

    def ensure_available(self) -> Path:
        """Return the helper path, downloading it when configuration permits.

        Returns:
            A usable executable path.

        Raises:
            ConfigurationError: If the pinned archive cannot be downloaded,
                verified, or unpacked.
        """
        existing = self._existing_path()
        if existing is not None:
            return existing
        self.install_directory.mkdir(parents=True, exist_ok=True)
        destination = (
            self.install_directory / THERMO_HELPER_SPECIFICATION.executable_name
        )
        archive_temporary = self.install_directory / (
            THERMO_HELPER_SPECIFICATION.asset_name + ".download"
        )
        executable_temporary = destination.with_suffix(destination.suffix + ".download")
        try:
            with urlopen(
                THERMO_HELPER_SPECIFICATION.download_url, timeout=60
            ) as response:
                with archive_temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
            self._verify_checksum(archive_temporary)
            try:
                with ZipFile(archive_temporary) as archive:
                    member_name = next(
                        (
                            name
                            for name in archive.namelist()
                            if Path(name).name
                            == THERMO_HELPER_SPECIFICATION.executable_name
                        ),
                        None,
                    )
                    if member_name is None:
                        raise ConfigurationError(
                            "Pinned Thermo helper archive does not contain "
                            f"{THERMO_HELPER_SPECIFICATION.executable_name!r}."
                        )
                    with archive.open(member_name) as source:
                        with executable_temporary.open("wb") as output:
                            shutil.copyfileobj(source, output)
            except BadZipFile as error:
                raise ConfigurationError(
                    "Pinned Thermo helper download is not a valid ZIP archive."
                ) from error
            executable_temporary.replace(destination)
        except (OSError, URLError) as error:
            raise ConfigurationError(
                f"Could not install pinned ThermScanHeaderExtractor "
                f"v{THERMO_HELPER_SPECIFICATION.version} from "
                f"{THERMO_HELPER_SPECIFICATION.download_url!r}: {error}."
            ) from error
        finally:
            archive_temporary.unlink(missing_ok=True)
            executable_temporary.unlink(missing_ok=True)
        return destination

    def _existing_path(self) -> Path | None:
        configured = self.settings.executable_path
        if configured is not None:
            resolved = configured.expanduser().resolve()
            if resolved.is_file():
                return resolved
        installed = self.install_directory / THERMO_HELPER_SPECIFICATION.executable_name
        return installed if installed.is_file() else None

    def _verify_checksum(self, path: Path) -> None:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        expected = THERMO_HELPER_SPECIFICATION.sha256
        if digest.hexdigest().casefold() != expected.casefold():
            raise ConfigurationError(
                "Downloaded ThermScanHeaderExtractor archive failed SHA-256 "
                f"verification; expected {expected!r}."
            )

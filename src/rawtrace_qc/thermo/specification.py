"""Pinned ThermoScanHeaderExtractor release metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rawtrace_qc import environment
from rawtrace_qc.errors import UnsupportedPlatformError
from rawtrace_qc.thermo.runtime import find_host_runtime

THERMO_HELPER_NAME = "thermoscanheaderextractor"

_REPOSITORY_URL = "https://github.com/maxperutzlabs-ms/thermo-scan-header-extractor"

ArchiveFormat = Literal["zip", "tar.gz"]


@dataclass(frozen=True, slots=True)
class ThermoHelperAsset:
    """Describe one pinned release archive for a single runtime."""

    asset_name: str
    sha256: str
    archive_format: ArchiveFormat
    executable_name: str


@dataclass(frozen=True, slots=True)
class ThermoHelperSpecification:
    """Describe one immutable ThermoScanHeaderExtractor archive for one runtime."""

    version: str
    runtime: str
    asset_name: str
    download_url: str
    sha256: str
    archive_format: ArchiveFormat
    executable_name: str
    tool_name: str = THERMO_HELPER_NAME


@dataclass(frozen=True, slots=True)
class ThermoHelperRelease:
    """Describe a pinned ThermoScanHeaderExtractor release and its runtime assets."""

    version: str
    assets: Mapping[str, ThermoHelperAsset]

    @property
    def release_page_url(self) -> str:
        """Return the web page listing this release and its archives."""
        return f"{_REPOSITORY_URL}/releases/tag/v{self.version}"

    def specification(self, runtime: str) -> ThermoHelperSpecification:
        """Return the resolved specification for one runtime.

        Args:
            runtime: Runtime identifier such as `win-x64`.

        Returns:
            The specification of the pinned asset for `runtime`.

        Raises:
            UnsupportedPlatformError: If no asset is pinned for `runtime`.
        """
        asset = self.assets.get(runtime)
        if asset is None:
            raise UnsupportedPlatformError(
                f"ThermoScanHeaderExtractor v{self.version} is not available for "
                f"runtime {runtime!r}. "
                f"Supported runtimes are {sorted(self.assets)}."
            )
        return ThermoHelperSpecification(
            version=self.version,
            runtime=runtime,
            asset_name=asset.asset_name,
            download_url=(
                f"{_REPOSITORY_URL}/releases/download/"
                f"v{self.version}/{asset.asset_name}"
            ),
            sha256=asset.sha256,
            archive_format=asset.archive_format,
            executable_name=asset.executable_name,
        )


THERMO_HELPER_RELEASE = ThermoHelperRelease(
    version="0.3.1",
    assets={
        "win-x64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-win-x64.zip",
            sha256="f406bb37ac0eee24b326b20a32eec6838cf33cec75c59eeb50ff59bcddab1b86",
            archive_format="zip",
            executable_name="ThermoScanHeaderExtractor.exe",
        ),
        "win-arm64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-win-arm64.zip",
            sha256="9ad2461ed47ca2e0ea5f426cec321bdbdfa5e8b60678c983d6664b0368f68fc6",
            archive_format="zip",
            executable_name="ThermoScanHeaderExtractor.exe",
        ),
        "linux-x64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-linux-x64.tar.gz",
            sha256="6c41263d12bd39ef9ba25a934061e28f3630afcc9d66af660b7c6b3a0ba3cb93",
            archive_format="tar.gz",
            executable_name="ThermoScanHeaderExtractor",
        ),
        "linux-arm64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-linux-arm64.tar.gz",
            sha256="123a49306a7d73078563b89720f912bf1e35a2a0b85b43952677442149fe7ecd",
            archive_format="tar.gz",
            executable_name="ThermoScanHeaderExtractor",
        ),
        "osx-x64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-osx-x64.tar.gz",
            sha256="c51435938f11cec0df3d07a9be7e1e55c8f3344482d73581de49b403160449db",
            archive_format="tar.gz",
            executable_name="ThermoScanHeaderExtractor",
        ),
        "osx-arm64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.3.1-osx-arm64.tar.gz",
            sha256="e6e0b4cdfafcee41a0a70ccdda427c010b26ce8e3e4919e0bf56d5307f0f0547",
            archive_format="tar.gz",
            executable_name="ThermoScanHeaderExtractor",
        ),
    },
)


def resolve_thermo_helper_specification(
    runtime: str | None = None,
    *,
    release: ThermoHelperRelease = THERMO_HELPER_RELEASE,
) -> ThermoHelperSpecification:
    """Resolve the helper specification for a runtime.

    Args:
        runtime: Runtime identifier such as `win-x64`. If None (default),
            detect the runtime of the current host.
        release: Pinned release to resolve from. Defaults to
            `THERMO_HELPER_RELEASE`.

    Returns:
        The specification of the asset to use for the runtime.

    Raises:
        UnsupportedPlatformError: If the host is not recognized or the
            runtime has no pinned asset.
    """
    selected = find_host_runtime() if runtime is None else runtime
    if selected is None:
        raise UnsupportedPlatformError(
            f"ThermoScanHeaderExtractor v{release.version} is not available for "
            f"platform {environment.get_platform()!r} and machine "
            f"{environment.get_machine()!r}. "
            f"Supported runtimes are {sorted(release.assets)}."
        )
    return release.specification(selected)


def is_thermo_helper_supported(
    runtime: str | None = None,
    *,
    release: ThermoHelperRelease = THERMO_HELPER_RELEASE,
) -> bool:
    """Return whether the helper is available for a runtime.

    A runtime is supported if it has a pinned asset in `release`. This check
    never raises for an unrecognized host, and does not check whether the
    helper is installed.

    Args:
        runtime: Runtime identifier such as `win-x64`. If None (default),
            detect the runtime of the current host.
        release: Pinned release to check. Defaults to `THERMO_HELPER_RELEASE`.

    Returns:
        True if `resolve_thermo_helper_specification` can resolve an asset for
        the runtime, otherwise False.
    """
    selected = find_host_runtime() if runtime is None else runtime
    if selected is None:
        return False
    return selected in release.assets

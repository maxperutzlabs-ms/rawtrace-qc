"""Pinned ThermoScanHeaderExtractor release metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rawtrace_qc.errors import UnsupportedPlatformError
from rawtrace_qc.thermo.runtime import detect_runtime, find_host_runtime

THERMO_HELPER_NAME = "thermoscanheaderextractor"

_RELEASE_BASE_URL = (
    "https://github.com/maxperutzlabs-ms/thermo-scan-header-extractor/releases/download"
)

ArchiveFormat = Literal["zip"]


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
            download_url=f"{_RELEASE_BASE_URL}/v{self.version}/{asset.asset_name}",
            sha256=asset.sha256,
            archive_format=asset.archive_format,
            executable_name=asset.executable_name,
        )


THERMO_HELPER_RELEASE = ThermoHelperRelease(
    version="0.2.0",
    assets={
        "win-x64": ThermoHelperAsset(
            asset_name="ThermoScanHeaderExtractor-v0.2.0-win-x64.zip",
            sha256="4b09265da895b67f810d33dc1a598545c0dc9d7bf3be0e5cccd308a7919a42f4",
            archive_format="zip",
            executable_name="ThermoScanHeaderExtractor.exe",
        ),
    },
)

# Runtimes without a pinned asset that can run another pinned runtime's asset.
# Windows on Arm executes the win-x64 build under x64 emulation.
RUNTIME_FALLBACKS: Mapping[str, str] = {"win-arm64": "win-x64"}


def resolve_thermo_helper_specification(
    runtime: str | None = None,
    *,
    release: ThermoHelperRelease = THERMO_HELPER_RELEASE,
) -> ThermoHelperSpecification:
    """Resolve the helper specification for a runtime.

    If the runtime has no pinned asset in `release`, `RUNTIME_FALLBACKS` is
    consulted once (for example, `win-arm64` runs the `win-x64` asset).

    Args:
        runtime: Runtime identifier such as `win-x64`. If None (default),
            detect the runtime of the current host.
        release: Pinned release to resolve from. Defaults to
            `THERMO_HELPER_RELEASE`.

    Returns:
        The specification of the asset to use for the runtime.

    Raises:
        UnsupportedPlatformError: If the host runtime cannot be detected or
            neither the runtime nor its fallback has a pinned asset.
    """
    selected = detect_runtime() if runtime is None else runtime
    return release.specification(_pinned_runtime(selected, release))


def is_thermo_helper_supported(
    runtime: str | None = None,
    *,
    release: ThermoHelperRelease = THERMO_HELPER_RELEASE,
) -> bool:
    """Return whether the helper is available for a runtime.

    A runtime is supported if it has a pinned asset in `release`, or if its
    entry in `RUNTIME_FALLBACKS` does. This check never raises for an
    unrecognized host, and does not check whether the helper is installed.

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
    return _pinned_runtime(selected, release) in release.assets


def _pinned_runtime(runtime: str, release: ThermoHelperRelease) -> str:
    if runtime in release.assets:
        return runtime
    fallback = RUNTIME_FALLBACKS.get(runtime, runtime)
    return fallback if fallback in release.assets else runtime

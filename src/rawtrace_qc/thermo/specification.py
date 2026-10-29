"""Pinned ThermoScanHeaderExtractor release metadata."""

from __future__ import annotations

from dataclasses import dataclass

THERMO_HELPER_NAME = "thermoscanheaderextractor"
THERMO_LICENSE_MARKER_NAME = ".thermo-license-accepted"


@dataclass(frozen=True, slots=True)
class ThermoHelperSpecification:
    """Describe one immutable ThermoScanHeaderExtractor release."""

    version: str
    asset_name: str
    download_url: str
    sha256: str
    executable_name: str
    tool_name: str = THERMO_HELPER_NAME
    license_marker_name: str = THERMO_LICENSE_MARKER_NAME


THERMO_HELPER_SPECIFICATION = ThermoHelperSpecification(
    version="0.1.0",
    asset_name="ThermoScanHeaderExtractor-v0.1.0-win-x64.zip",
    download_url=(
        "https://github.com/maxperutzlabs-ms/thermo-scan-header-extractor/"
        "releases/download/v0.1.0/ThermoScanHeaderExtractor-v0.1.0-win-x64.zip"
    ),
    sha256="6aeea856ff317d393f0ec7de34f09675b092f26e1671cb298cbf8af34decb882",
    executable_name="ThermoScanHeaderExtractor.exe",
)

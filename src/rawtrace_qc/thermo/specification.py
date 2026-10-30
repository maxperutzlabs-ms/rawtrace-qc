"""Pinned ThermoScanHeaderExtractor release metadata."""

from __future__ import annotations

from dataclasses import dataclass

THERMO_HELPER_NAME = "thermoscanheaderextractor"


@dataclass(frozen=True, slots=True)
class ThermoHelperSpecification:
    """Describe one immutable ThermoScanHeaderExtractor release."""

    version: str
    asset_name: str
    download_url: str
    sha256: str
    executable_name: str
    tool_name: str = THERMO_HELPER_NAME


THERMO_HELPER_SPECIFICATION = ThermoHelperSpecification(
    version="0.2.0",
    asset_name="ThermoScanHeaderExtractor-v0.2.0-win-x64.zip",
    download_url=(
        "https://github.com/maxperutzlabs-ms/thermo-scan-header-extractor/"
        "releases/download/v0.2.0/ThermoScanHeaderExtractor-v0.2.0-win-x64.zip"
    ),
    sha256="4b09265da895b67f810d33dc1a598545c0dc9d7bf3be0e5cccd308a7919a42f4",
    executable_name="ThermoScanHeaderExtractor.exe",
)

"""Detect the .NET-style runtime identifier of the current host."""

from __future__ import annotations

from rawtrace_qc import environment

_OPERATING_SYSTEMS = {"win32": "win", "linux": "linux", "darwin": "osx"}
_ARCHITECTURES = {
    "amd64": "x64",
    "x86_64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def find_host_runtime() -> str | None:
    """Return the runtime identifier of the current host, if it is recognized.

    Returns:
        The runtime identifier such as `win-x64`, or None if the operating
        system or CPU architecture is not recognized.
    """
    operating_system = _OPERATING_SYSTEMS.get(environment.get_platform())
    architecture = _ARCHITECTURES.get(environment.get_machine().casefold())
    if operating_system is None or architecture is None:
        return None
    return f"{operating_system}-{architecture}"

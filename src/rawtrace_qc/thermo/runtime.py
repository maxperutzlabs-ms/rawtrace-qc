"""Detect the .NET-style runtime identifier of the current host."""

from __future__ import annotations

from rawtrace_qc import environment
from rawtrace_qc.errors import UnsupportedPlatformError

_OPERATING_SYSTEMS = {"win32": "win", "linux": "linux", "darwin": "osx"}
_ARCHITECTURES = {
    "amd64": "x64",
    "x86_64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def detect_runtime() -> str:
    """Return the runtime identifier of the current host.

    The identifier combines the operating system (`win`, `linux`, `osx`) and
    the CPU architecture (`x64`, `arm64`), for example `win-x64`.

    Returns:
        The runtime identifier of the current host.

    Raises:
        UnsupportedPlatformError: If the operating system or CPU architecture
            is not recognized.
    """
    platform_name = environment.get_platform()
    machine = environment.get_machine()
    operating_system = _OPERATING_SYSTEMS.get(platform_name)
    architecture = _ARCHITECTURES.get(machine.casefold())
    if operating_system is None or architecture is None:
        raise UnsupportedPlatformError(
            f"Cannot determine the Thermo helper runtime for platform "
            f"{platform_name!r} and machine {machine!r}. Supported operating "
            f"systems are {sorted(_OPERATING_SYSTEMS)} and supported CPU "
            "architectures are "
            f"{sorted(set(_ARCHITECTURES.values()))}."
        )
    return f"{operating_system}-{architecture}"

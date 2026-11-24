"""Environment and application data paths for rawtrace-qc."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

from platformdirs import user_data_dir

_APP_NAME = "rawtrace-qc"
_APP_AUTHOR = "perutzms"


def get_platform() -> str:
    """Return the current Python platform identifier."""
    return sys.platform


def get_machine() -> str:
    """Return the current CPU architecture name reported by Python."""
    return platform.machine()


def default_data_directory() -> Path:
    """Return the per-user application data directory without creating it.

    The location is selected by `platformdirs`.

    Returns:
        The application data directory path.
    """
    return Path(user_data_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR, roaming=False))


def helper_tool_directory(helper_name: str, release_version: str, runtime: str) -> Path:
    """Return a helper install path isolated by helper name, release, and runtime.

    The path is below `default_data_directory()`.

    Args:
        helper_name: Helper tool directory name.
        release_version: Required helper release version.
        runtime: Runtime identifier such as `win-x64`.

    Returns:
        The version- and runtime-specific helper directory path.
    """
    return default_data_directory() / "tools" / helper_name / release_version / runtime

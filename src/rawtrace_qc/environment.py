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


def default_data_directory(override: Path | str | None = None) -> Path:
    """Return the per-user application data directory without creating it.

    If no explicit override is provided, use the location selected by
    `platformdirs`.

    Args:
        override: Explicit data directory. If None (default), use the platform
            default.

    Returns:
        The application data directory path.
    """
    if override is not None:
        return Path(override).expanduser()
    return Path(user_data_dir(appname=_APP_NAME, appauthor=_APP_AUTHOR, roaming=False))


def helper_tool_directory(
    helper_name: str, release_version: str, *, data_directory: Path | str | None = None
) -> Path:
    """Return a helper install path isolated by helper name and release.

    Args:
        helper_name: Helper tool directory name.
        release_version: Required helper release version.
        data_directory: Data directory root. If None (default), use
            `default_data_directory()`.

    Returns:
        The version-specific helper directory path.
    """
    root = default_data_directory(data_directory)
    return root / "tools" / helper_name / release_version

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

"""Collection hooks and item tagging for test folders and markers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parent.parent


def tag_test_items(items: Sequence[pytest.Item], *, tests_root: Path | None = None) -> None:
    """Tag collected test items with folder-derived markers.

    Items located under `unit/` and `integration/` receive the corresponding marker. Tests that
    depend on the network carry an explicit `network` marker and skip themselves when the network
    is unavailable.

    Args:
        items: Pytest test items collected for the session.
        tests_root: Optional root path for test directories. Defaults to the resolved tests folder.
    """
    root = (tests_root or _TESTS_ROOT).resolve()
    tier_dirs = {
        "unit": root / "unit",
        "integration": root / "integration",
    }

    for item in items:
        item_path = getattr(item, "path", None)
        if item_path is None:
            item_path = Path(item.fspath)
        resolved_path = item_path.resolve()

        for tier, tier_dir in tier_dirs.items():
            if _is_relative_to(resolved_path, tier_dir):
                item.add_marker(getattr(pytest.mark, tier))
                break


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        return path.is_relative_to(directory)
    except (ValueError, OSError):
        return False

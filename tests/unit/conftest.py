from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_directory(isolated_data_directory: Path) -> None:
    pass

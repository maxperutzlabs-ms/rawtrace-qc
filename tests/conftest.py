from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.support.collection import tag_test_items
from tests.support.thermo_helper import expire_stale_test_cache, resolve_integration_thermo_helper


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    tag_test_items(items)


@pytest.fixture(scope="session", autouse=True)
def _expire_stale_thermo_cache() -> None:
    expire_stale_test_cache()


@pytest.fixture(scope="session")
def thermo_helper_executable() -> Path:
    return resolve_integration_thermo_helper()


@pytest.fixture
def thermo_raw_fixture() -> Path:
    fixture_path = Path(__file__).resolve().parent / "data" / "thermo" / "exploris480_ms1_dia_3cycles.raw"
    if not fixture_path.is_file():
        pytest.fail(f"Required Thermo test fixture not found: {fixture_path}")
    return fixture_path


@pytest.fixture
def bruker_fixture(tmp_path: Path) -> Path:
    acquisition_path = tmp_path / "sample.d"
    acquisition_path.mkdir()
    _create_tdf(acquisition_path / "analysis.tdf")
    return acquisition_path


def _create_tdf(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE Frames ("
            "Id INTEGER PRIMARY KEY, Time REAL NOT NULL, Polarity TEXT NOT NULL, "
            "ScanMode INTEGER NOT NULL, MsMsType INTEGER NOT NULL, TimsId INTEGER, "
            "MaxIntensity INTEGER NOT NULL, SummedIntensities INTEGER NOT NULL, "
            "NumScans INTEGER NOT NULL, NumPeaks INTEGER NOT NULL, "
            "AccumulationTime REAL NOT NULL, RampTime REAL NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO Frames VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, 1.0, "+", 0, 0, 1, 100, 1000, 10, 100, 5.0, 1.0),
                (2, 2.0, "+", 0, 8, 2, 200, 2000, 20, 200, 6.0, 1.0),
                (3, 3.0, "+", 0, 0, 3, 300, 3000, 30, 300, 7.0, 1.0),
            ],
        )
        connection.execute("CREATE TABLE GlobalMetadata (Key TEXT PRIMARY KEY, Value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO GlobalMetadata VALUES (?, ?)",
            ("AcquisitionDateTime", "2026-08-01T14:30:15.123+02:00"),
        )
        connection.execute(
            "INSERT INTO GlobalMetadata VALUES (?, ?)",
            ("AnalysisId", "78d629b2-0edc-4f60-b942-979a46b94ac8"),
        )
        connection.execute("CREATE TABLE DiaFrameMsMsInfo (Frame INTEGER PRIMARY KEY, WindowGroup INTEGER NOT NULL)")
        connection.execute("INSERT INTO DiaFrameMsMsInfo VALUES (3, 1)")
        connection.commit()

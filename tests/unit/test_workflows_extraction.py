from __future__ import annotations

import os
from pathlib import Path

import pytest
from rawtrace_qc.discovery import DiscoveryIssue, DiscoveryOptions, Vendor
from rawtrace_qc.errors import ThermoHelperNotFoundError
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.thermo import ThermoHelperState, ThermoHelperStatus
from rawtrace_qc.workflows import (
    BatchExtractionResult,
    ExtractionOutcomeStatus,
    extract_batch,
)
from rawtrace_qc.workflows import extraction as workflow_module


def _discovery_options() -> DiscoveryOptions:
    return DiscoveryOptions(min_size_bytes=1, min_age_seconds=0)


def _create_raw(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"raw")
    os.utime(path, (1, 1))
    return path


def _create_bruker(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "analysis.tdf").write_bytes(b"metadata")
    (path / "analysis.tdf_bin").write_bytes(b"binary")
    return path


class RecordingExtractor:
    def __init__(self, failures: dict[Path, Exception] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.failures = failures or {}

    def extract(
        self,
        input_path: Path,
        output_directory: Path | None = None,
        output_name: str | None = None,
        precision_mode: str = "low",
        *,
        select_ms1: bool = True,
        select_msn: bool = True,
    ) -> ExtractionResult:
        self.calls.append(
            {
                "input_path": input_path,
                "output_directory": output_directory,
                "output_name": output_name,
                "precision_mode": precision_mode,
                "select_ms1": select_ms1,
                "select_msn": select_msn,
            }
        )
        if input_path in self.failures:
            raise self.failures[input_path]
        return ExtractionResult()


def _ready_helper_status() -> ThermoHelperStatus:
    return ThermoHelperStatus(
        state=ThermoHelperState.READY,
        path=Path("ThermoScanHeaderExtractor.exe"),
        version="0.1.0",
        license_accepted=True,
        message="Helper is ready.",
    )


def _not_installed_status() -> ThermoHelperStatus:
    return ThermoHelperStatus(
        state=ThermoHelperState.NOT_INSTALLED,
        path=None,
        version=None,
        license_accepted=False,
        message="ThermoScanHeaderExtractor is not installed.",
    )


class TestExtractBatch:
    def test_single_thermo_file_is_extracted_directly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        raw_file = _create_raw(tmp_path / "sample.raw")
        thermo = RecordingExtractor()
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        result = extract_batch([raw_file], discovery_options=_discovery_options())

        assert result.exit_code == 0
        assert len(result.outcomes) == 1
        assert result.outcomes[0].candidate.vendor == Vendor.THERMO
        assert result.outcomes[0].status is ExtractionOutcomeStatus.SUCCEEDED
        assert thermo.calls[0]["input_path"] == raw_file

    def test_glob_input_is_expanded_before_extraction(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        raw_file = _create_raw(tmp_path / "sample.raw")
        thermo = RecordingExtractor()
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        result = extract_batch([tmp_path / "*.raw"], discovery_options=_discovery_options())

        assert result.exit_code == 0
        assert [outcome.candidate.path for outcome in result.outcomes] == [raw_file]
        assert thermo.calls[0]["input_path"] == raw_file

    @pytest.mark.parametrize(("recursive", "expected_candidates"), [(False, 0), (True, 1)])
    def test_directory_scan_obeys_recursive_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recursive: bool, expected_candidates: int
    ) -> None:
        source = tmp_path / "source"
        nested_raw = _create_raw(source / "nested" / "sample.raw")
        thermo = RecordingExtractor()
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        result = extract_batch([source], recursive=recursive, discovery_options=_discovery_options())

        assert len(result.outcomes) == expected_candidates
        if recursive:
            assert result.outcomes[0].candidate.path == nested_raw
        else:
            assert result.discovery_issues[0].path == source

    def test_mixed_inputs_dispatch_using_discovery_vendor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_file = _create_raw(tmp_path / "sample.raw")
        _create_bruker(tmp_path / "run.d")
        thermo = RecordingExtractor()
        bruker = RecordingExtractor()
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "BrukerExtractor", lambda: bruker)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        result = extract_batch([raw_file, tmp_path], discovery_options=_discovery_options())

        assert result.exit_code == 0
        assert [outcome.candidate.vendor for outcome in result.outcomes] == [
            Vendor.THERMO,
            Vendor.BRUKER,
        ]
        assert len(thermo.calls) == 1
        assert len(bruker.calls) == 1

    def test_unready_thermo_helper_skips_thermo_and_still_processes_bruker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_file = _create_raw(tmp_path / "sample.raw")
        bruker_directory = _create_bruker(tmp_path / "run.d")
        thermo = RecordingExtractor()
        bruker = RecordingExtractor()
        status_calls = 0

        def helper_status() -> ThermoHelperStatus:
            nonlocal status_calls
            status_calls += 1
            return _not_installed_status()

        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "BrukerExtractor", lambda: bruker)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", helper_status)

        result = extract_batch([raw_file, bruker_directory], discovery_options=_discovery_options())

        thermo_outcome = result.outcomes[0]
        assert result.exit_code == 1
        assert status_calls == 1
        assert thermo_outcome.status is ExtractionOutcomeStatus.SKIPPED
        assert isinstance(thermo_outcome.error, ThermoHelperNotFoundError)
        assert "not installed" in thermo_outcome.reason
        assert result.outcomes[1].status is ExtractionOutcomeStatus.SUCCEEDED
        assert thermo.calls == []
        assert len(bruker.calls) == 1

    def test_failed_candidate_does_not_abort_later_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first_raw = _create_raw(tmp_path / "first.raw")
        second_raw = _create_raw(tmp_path / "second.raw")
        thermo = RecordingExtractor({first_raw: RuntimeError("mock extraction failure")})
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        result = extract_batch([first_raw, second_raw], discovery_options=_discovery_options())

        assert [outcome.status for outcome in result.outcomes] == [
            ExtractionOutcomeStatus.FAILED,
            ExtractionOutcomeStatus.SUCCEEDED,
        ]
        assert len(thermo.calls) == 2
        assert "mock extraction failure" in result.outcomes[0].reason

    def test_extractor_options_are_forwarded_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        raw_file = _create_raw(tmp_path / "sample.raw")
        output_directory = tmp_path / "traces"
        thermo = RecordingExtractor()
        monkeypatch.setattr(workflow_module, "ThermoExtractor", lambda: thermo)
        monkeypatch.setattr(workflow_module, "get_thermo_helper_status", _ready_helper_status)

        extract_batch(
            [raw_file],
            output_directory=output_directory,
            precision_mode="high",
            select_ms1=False,
            select_msn=True,
            discovery_options=_discovery_options(),
        )

        assert thermo.calls == [
            {
                "input_path": raw_file,
                "output_directory": output_directory,
                "output_name": None,
                "precision_mode": "high",
                "select_ms1": False,
                "select_msn": True,
            }
        ]

    def test_empty_scan_is_reported_as_a_discovery_issue(self, tmp_path: Path) -> None:
        source = tmp_path / "empty"
        source.mkdir()

        result = extract_batch([source], discovery_options=_discovery_options())

        assert result.outcomes == ()
        assert result.exit_code == 1
        assert result.discovery_issues[0].path == source
        assert "No supported" in result.discovery_issues[0].message


class TestBatchExtractionResult:
    def test_exit_code_is_nonzero_for_discovery_issues(self, tmp_path: Path) -> None:
        result = BatchExtractionResult(
            outcomes=(),
            discovery_issues=(DiscoveryIssue(tmp_path, "No acquisitions."),),
        )

        assert result.exit_code == 1

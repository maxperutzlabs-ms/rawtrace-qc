from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.cli import extract as extract_cli_module
from rawtrace_qc.cli import main
from rawtrace_qc.discovery import DiscoveryCandidate, DiscoveryIssue, SkippedAcquisition, SkipReason, Vendor
from rawtrace_qc.errors import ExtractionError, ThermoHelperCommandError, ThermoHelperNotFoundError
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.workflows import (
    BatchExtractionOutcome,
    BatchExtractionResult,
    ExtractionOutcomeStatus,
)


class TestExtractCommand:
    def test_command_passes_options_to_library_and_renders_outcomes(self, tmp_path: Path, monkeypatch, capsys) -> None:
        raw_file = tmp_path / "sample.raw"
        second_raw_file = tmp_path / "second.raw"
        output_directory = tmp_path / "traces"
        candidate = DiscoveryCandidate(raw_file, Vendor.THERMO, "raw")
        batch_result = BatchExtractionResult(
            outcomes=(
                BatchExtractionOutcome(
                    candidate,
                    ExtractionOutcomeStatus.SUCCEEDED,
                    ExtractionResult(msn_path=output_directory / "sample.msn-trace.parquet"),
                ),
            ),
            discovery_issues=(),
        )
        calls: dict[str, object] = {}

        def fake_extract_batch(paths, **kwargs):
            calls["paths"] = paths
            calls.update(kwargs)
            return batch_result

        monkeypatch.setattr(extract_cli_module, "extract_batch", fake_extract_batch)

        result = main(
            [
                "extract",
                str(raw_file),
                str(second_raw_file),
                "--output-dir",
                str(output_directory),
                "--precision",
                "high",
                "--recursive",
                "--msn",
            ]
        )

        output = capsys.readouterr().out
        assert result == 0
        assert calls == {
            "paths": [raw_file, second_raw_file],
            "recursive": True,
            "output_directory": output_directory,
            "precision_mode": "high",
            "select_ms1": False,
            "select_msn": True,
        }
        assert "succeeded" in output
        assert "sample.msn-trace.parquet" in output

    def test_glob_pattern_is_forwarded_to_batch_discovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pattern = tmp_path / "*.raw"
        calls: dict[str, object] = {}

        def fake_extract_batch(paths, **kwargs):
            calls["paths"] = paths
            return BatchExtractionResult(outcomes=(), discovery_issues=())

        monkeypatch.setattr(extract_cli_module, "extract_batch", fake_extract_batch)

        result = main(["extract", str(pattern)])

        assert result == 0
        assert calls["paths"] == [pattern]

    @pytest.mark.parametrize(
        ("flags", "select_ms1", "select_msn"),
        [
            ([], True, True),
            (["--ms1"], True, False),
            (["--msn"], False, True),
            (["--ms1", "--msn"], True, True),
        ],
    )
    def test_ms_level_flags_select_expected_levels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], select_ms1: bool, select_msn: bool
    ) -> None:
        raw_file = tmp_path / "sample.raw"
        calls: dict[str, object] = {}

        def fake_extract_batch(paths, **kwargs):
            calls.update(kwargs)
            return BatchExtractionResult(outcomes=(), discovery_issues=())

        monkeypatch.setattr(extract_cli_module, "extract_batch", fake_extract_batch)

        result = main(["extract", str(raw_file), *flags])

        assert result == 0
        assert calls["select_ms1"] is select_ms1
        assert calls["select_msn"] is select_msn

    def test_report_lists_every_acquisition_by_path_with_its_reason(self, tmp_path: Path, monkeypatch, capsys) -> None:
        corrupt = tmp_path / "a.raw"
        fresh = tmp_path / "b.raw"
        good = tmp_path / "c.raw"
        trace = tmp_path / "c.raw.ms1-trace.parquet"
        batch_result = BatchExtractionResult(
            outcomes=(
                BatchExtractionOutcome(
                    DiscoveryCandidate(good, Vendor.THERMO, "raw"),
                    ExtractionOutcomeStatus.SUCCEEDED,
                    ExtractionResult(ms1_path=trace),
                ),
                BatchExtractionOutcome(
                    DiscoveryCandidate(corrupt, Vendor.THERMO, "raw"),
                    ExtractionOutcomeStatus.FAILED,
                    error=ExtractionError("Could not read acquisition.", path=corrupt),
                ),
            ),
            discovery_issues=(),
            discovery_skips=(SkippedAcquisition(fresh, SkipReason.TOO_RECENT, "Modified 45 s ago (minimum 2 min)."),),
        )
        monkeypatch.setattr(extract_cli_module, "extract_batch", lambda *_args, **_kwargs: batch_result)

        result = main(["extract", str(tmp_path)])

        captured = capsys.readouterr()
        assert result == 1
        assert captured.err == ""
        assert captured.out.splitlines() == [
            f"failed: {corrupt}",
            "  Could not read acquisition.",
            f"skipped: {fresh}",
            "  Modified 45 s ago (minimum 2 min).",
            f"succeeded: {good}",
            f"  MS1: {trace}",
            "Summary: 1 succeeded, 1 skipped, 1 failed, 0 discovery issue(s).",
        ]

    def test_thermo_setup_guidance_is_printed_once_after_the_report(self, tmp_path: Path, monkeypatch, capsys) -> None:
        not_found = ThermoHelperNotFoundError("Thermo helper is not installed.")
        outcomes = tuple(
            BatchExtractionOutcome(
                DiscoveryCandidate(tmp_path / name, Vendor.THERMO, "raw"),
                ExtractionOutcomeStatus.SKIPPED,
                error=not_found,
            )
            for name in ("a.raw", "b.raw")
        )
        command_error = ThermoHelperCommandError("Helper exited with 4.", returncode=4, stdout="", stderr="")
        failed = BatchExtractionOutcome(
            DiscoveryCandidate(tmp_path / "c.raw", Vendor.THERMO, "raw"),
            ExtractionOutcomeStatus.FAILED,
            error=command_error,
        )
        batch_result = BatchExtractionResult(outcomes=(*outcomes, failed), discovery_issues=())
        monkeypatch.setattr(extract_cli_module, "extract_batch", lambda *_args, **_kwargs: batch_result)

        result = main(["extract", str(tmp_path)])

        output = capsys.readouterr().out
        assert result == 1
        assert output.count("Thermo helper is not ready.") == 3
        assert output.count("Thermo helper is not installed.") == 1
        assert output.count("rawtrace-qc thermo install`") == 1
        assert output.count("Helper exited with 4.") == 1
        assert output.count("rawtrace-qc thermo status") == 1
        assert output.index("Thermo setup:") > output.index(str(tmp_path / "c.raw"))

    def test_discovery_issues_are_reported_and_fail_the_command(self, tmp_path: Path, monkeypatch, capsys) -> None:
        candidate = DiscoveryCandidate(tmp_path / "sample.raw", Vendor.THERMO, "raw")
        issue = DiscoveryIssue(tmp_path / "unclassified", "No supported complete acquisitions were found.")
        batch_result = BatchExtractionResult(
            outcomes=(BatchExtractionOutcome(candidate, ExtractionOutcomeStatus.SUCCEEDED),),
            discovery_issues=(issue,),
        )
        monkeypatch.setattr(extract_cli_module, "extract_batch", lambda *_args, **_kwargs: batch_result)

        result = main(["extract", str(issue.path)])

        output = capsys.readouterr().out
        assert result == 1
        assert f"succeeded: {candidate.path}" in output
        assert f"{issue.path}: {issue.message}" in output
        assert "1 discovery issue(s)" in output

    def test_root_help_lists_registered_subcommands(self, capsys) -> None:
        result = main(["--help"])

        output = capsys.readouterr().out
        assert result == 0
        assert "thermo" in output
        assert "extract" in output

    def test_extract_help_omits_unneeded_negative_flags(self, capsys) -> None:
        result = main(["extract", "--help"])

        output = capsys.readouterr().out
        assert result == 0
        assert "PATH" in output
        assert "--recursive" in output
        assert "--empty-PATH" not in output
        assert "--no-recursive" not in output
        assert "--ms1" in output
        assert "--msn" in output
        assert "--no-ms1" not in output
        assert "--no-msn" not in output

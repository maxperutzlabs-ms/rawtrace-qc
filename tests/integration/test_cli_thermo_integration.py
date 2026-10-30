"""Integration tests for the Thermo CLI commands against a real helper binary.

These tests require that the current user has already accepted the Thermo
license terms; otherwise the `thermo_helper_executable` fixture skips them. The
helper records acceptance per user, so the unaccepted state and the first-time
acceptance flow cannot be exercised here without changing the user's real
license state; they are covered by unit tests with a mocked helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rawtrace_qc.cli import main

pytestmark = pytest.mark.network


class TestCliThermoIntegration:
    def test_status_reports_ready_for_real_licensed_helper(
        self,
        thermo_helper_executable: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        result = main(["thermo", "status", "--helper-path", str(thermo_helper_executable)])

        output = capsys.readouterr().out
        assert result == 0
        assert "Thermo helper status: ready" in output
        assert "is ready" in output

    def test_accept_license_is_a_no_op_when_already_accepted(
        self,
        thermo_helper_executable: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        accept_result = main(["thermo", "accept-license", "--helper-path", str(thermo_helper_executable)])

        accept_output = capsys.readouterr().out
        assert accept_result == 0
        assert "The following Thermo license terms will be accepted by this command:" in accept_output
        assert "Thermo license acceptance is recorded for the current user." in accept_output

        status_result = main(["thermo", "status", "--helper-path", str(thermo_helper_executable)])

        status_output = capsys.readouterr().out
        assert status_result == 0
        assert "Thermo helper status: ready" in status_output

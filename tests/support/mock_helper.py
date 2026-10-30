"""Mock ThermoScanHeaderExtractor helper for unit testing."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rawtrace_qc.thermo.specification import THERMO_HELPER_SPECIFICATION


@dataclass
class MockThermoHelper:
    """Mock runner that mimics the ThermoScanHeaderExtractor contract.

    Supports version queries, an in-memory license state that a bare invocation
    reports (exit code 4 when not accepted, usage exit code 1 when accepted) and
    `--agree-to-terms` sets, and configurable failure modes (exit code,
    empty/garbage stdout, timeouts, or execution errors). Nothing is written to
    disk, so tests never touch the real user's license state.
    """

    version: str = THERMO_HELPER_SPECIFICATION.version
    exit_code: int = 0
    stdout: str | None = None
    stderr: str = ""
    hang: bool = False
    os_error: OSError | None = None
    license_text: str = "Mock Thermo license terms.\n"
    license_text_exit_code: int | None = None
    agreement_exit_code: int | None = None
    license_accepted: bool = False
    records_acceptance: bool = True
    commands_run: list[list[str]] = field(default_factory=list)

    def __call__(self, args: Sequence[str | Path], *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        """Execute a simulated helper command."""
        str_args = [str(arg) for arg in args]
        self.commands_run.append(str_args)

        if self.os_error is not None:
            raise self.os_error

        if self.hang:
            raise subprocess.TimeoutExpired(cmd=str_args, timeout=timeout)

        command_exit_code = self.exit_code
        if "--thermo-license" in str_args and self.license_text_exit_code is not None:
            command_exit_code = self.license_text_exit_code
        elif "--agree-to-terms" in str_args and self.agreement_exit_code is not None:
            command_exit_code = self.agreement_exit_code

        if len(str_args) == 1 and command_exit_code == 0 and self.stdout is None:
            if self.license_accepted:
                return subprocess.CompletedProcess(
                    args=str_args, returncode=1, stdout="", stderr="Usage: ThermoScanHeaderExtractor <input.raw>\n"
                )
            return subprocess.CompletedProcess(
                args=str_args, returncode=4, stdout="", stderr="ERROR: Thermo license terms have not been accepted.\n"
            )

        stdout = self.stdout
        if stdout is None and command_exit_code == 0:
            if "--version" in str_args:
                stdout = f"{self.version}\n"
            elif "--thermo-license" in str_args:
                stdout = self.license_text
            elif "--agree-to-terms" in str_args:
                stdout = "Terms accepted.\n"
            else:
                stdout = ""

        if command_exit_code != 0:
            return subprocess.CompletedProcess(
                args=str_args,
                returncode=command_exit_code,
                stdout=stdout or "",
                stderr=self.stderr or f"Process failed with exit code {command_exit_code}.",
            )

        if "--agree-to-terms" in str_args and self.records_acceptance:
            self.license_accepted = True

        return subprocess.CompletedProcess(
            args=str_args,
            returncode=0,
            stdout=stdout or "",
            stderr=self.stderr,
        )


def create_mock_helper_file(directory: Path, name: str = THERMO_HELPER_SPECIFICATION.executable_name) -> Path:
    """Create a mock helper binary file in a directory.

    Args:
        directory: Destination folder.
        name: Executable filename. Defaults to the pinned helper executable name.

    Returns:
        The created executable path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    executable_path = directory / name
    executable_path.write_bytes(b"MZmock_executable_standin")
    return executable_path


if __name__ == "__main__":
    if (
        "--runner-test-success" in sys.argv
        or "--runner-test-failure" in sys.argv
        or "--runner-test-timeout" in sys.argv
    ):
        sys.stdout.write("mock helper stdout\n")
        sys.stderr.write("mock helper stderr\n")
        sys.stdout.flush()
        sys.stderr.flush()
        if "--runner-test-failure" in sys.argv:
            sys.exit(7)
        if "--runner-test-timeout" in sys.argv:
            time.sleep(30)
        sys.exit(0)
    elif "--version" in sys.argv:
        sys.stdout.write(f"{THERMO_HELPER_SPECIFICATION.version}\n")
        sys.exit(0)
    elif "--thermo-license" in sys.argv:
        sys.stdout.write("Mock Thermo license terms.\n")
        sys.exit(0)
    else:
        sys.stderr.write("Unknown command\n")
        sys.exit(1)

"""Build commands and execute ThermoScanHeaderExtractor."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from rawtrace_qc.errors import (
    OperationCancelledError,
    ThermoHelperCommandError,
    ThermoHelperExecutableNotFoundError,
    ThermoHelperExecutionError,
    ThermoHelperOutputError,
    ThermoHelperTimeoutError,
)

if TYPE_CHECKING:
    from rawtrace_qc.extractors.protocol import PrecisionMode

_DEFAULT_TIMEOUT = 600.0
_CANCEL_POLL_SECONDS = 0.1


def build_thermo_helper_command(
    executable_path: Path | str,
    input_path: Path | str,
    output_directory: Path | str | None = None,
    output_name: str | None = None,
    precision_mode: PrecisionMode = "low",
    *,
    select_ms1: bool = True,
    select_msn: bool = True,
) -> list[str]:
    """Build an argument list for the pinned helper's extraction command.

    Paths are returned as individual arguments without shell quoting, so spaces
    and non-ASCII characters are preserved by the operating system process API.

    Args:
        executable_path: ThermoScanHeaderExtractor executable path.
        input_path: Thermo `.raw` input path.
        output_directory: Output directory. Defaults to None.
        output_name: Optional output name. Defaults to None.
        precision_mode: Precision selection, either `low` or `high`. Defaults
            to `low`.
        select_ms1: If True (default), include MS1 scans.
        select_msn: If True (default), include MSn scans.

    Returns:
        The helper command as a list of executable and argument strings.

    Raises:
        ValueError: If the precision mode is invalid or neither scan level is
            selected.
    """
    if precision_mode not in {"low", "high"}:
        raise ValueError("precision_mode must be 'low' or 'high'.")
    if not select_ms1 and not select_msn:
        raise ValueError("At least one of select_ms1 or select_msn must be True.")

    command = [str(executable_path), str(input_path)]
    if precision_mode == "high":
        command.append("--high-precision")
    if select_ms1:
        command.append("--ms1")
    if select_msn:
        command.append("--msn")
    if output_directory is not None:
        command.extend(("-o", str(output_directory)))
    if output_name is not None:
        command.extend(("--name", output_name))
    return command


def run_thermo_helper(
    command: Sequence[str | Path],
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a helper command and return its captured text output.

    The command is passed as an argument sequence with shell execution disabled.
    Standard output and error are captured as bytes and decoded as UTF-8.

    Args:
        command: Argument sequence produced by
            `build_thermo_helper_command`.
        timeout: Maximum process duration in seconds. Defaults to 600.0.
        cancel: Optional event that stops the helper process when set from
            another thread. Defaults to None.

    Returns:
        A completed process containing decoded standard output and error.

    Raises:
        ValueError: If `command` is empty or `timeout` is not positive.
        ThermoHelperCommandError: If the helper exits with a non-zero status.
        ThermoHelperExecutableNotFoundError: If the executable cannot be
            started because it is missing.
        ThermoHelperOutputError: If the output of a successful run is not valid
            UTF-8.
        ThermoHelperTimeoutError: If the process exceeds `timeout`.
        ThermoHelperExecutionError: If another operating-system error prevents
            process execution.
        OperationCancelledError: If `cancel` was set while the helper was running.
    """
    if isinstance(command, str):
        raise TypeError("command must be a sequence of arguments, not a string.")
    command_arguments = [str(argument) for argument in command]
    if not command_arguments:
        raise ValueError("command must contain an executable and its arguments.")
    if timeout <= 0:
        raise ValueError(f"timeout must be greater than zero, got {timeout!r}.")

    try:
        result = (
            _execute_process(command_arguments, timeout=timeout)
            if cancel is None
            else _execute_cancellable_process(
                command_arguments, timeout=timeout, cancel=cancel
            )
        )
    except subprocess.TimeoutExpired as error:
        raise ThermoHelperTimeoutError(
            f"ThermoScanHeaderExtractor command {command_arguments!r} exceeded "
            f"the {timeout}-second timeout.",
            stdout=_decode_output(error.stdout, errors="backslashreplace"),
            stderr=_decode_output(error.stderr, errors="backslashreplace"),
        ) from error
    except FileNotFoundError as error:
        raise ThermoHelperExecutableNotFoundError(
            f"Could not start ThermoScanHeaderExtractor command "
            f"{command_arguments!r}: {error}.",
            stdout="",
            stderr="",
        ) from error
    except OSError as error:
        raise ThermoHelperExecutionError(
            f"Could not execute ThermoScanHeaderExtractor command "
            f"{command_arguments!r}: {error}.",
            stdout="",
            stderr="",
        ) from error

    if result.returncode != 0:
        raise ThermoHelperCommandError(
            f"ThermoScanHeaderExtractor command {command_arguments!r} exited "
            f"with status {result.returncode}.",
            returncode=result.returncode,
            stdout=_decode_output(result.stdout, errors="backslashreplace"),
            stderr=_decode_output(result.stderr, errors="backslashreplace"),
        )

    try:
        stdout = _decode_output(result.stdout)
        stderr = _decode_output(result.stderr)
    except UnicodeDecodeError as error:
        raise ThermoHelperOutputError(
            f"ThermoScanHeaderExtractor command {command_arguments!r} produced "
            f"output that is not valid UTF-8: {error}.",
            stdout=_decode_output(result.stdout, errors="backslashreplace"),
            stderr=_decode_output(result.stderr, errors="backslashreplace"),
        ) from error

    return subprocess.CompletedProcess(
        args=command_arguments,
        returncode=result.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _execute_process(
    command: Sequence[str], *, timeout: float
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _execute_cancellable_process(
    command: Sequence[str], *, timeout: float, cancel: threading.Event
) -> subprocess.CompletedProcess[bytes]:
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=_CANCEL_POLL_SECONDS)
            except subprocess.TimeoutExpired:
                if cancel.is_set():
                    process.kill()
                    process.communicate()
                    raise OperationCancelledError(
                        "The Thermo helper was stopped because the operation "
                        "was cancelled."
                    ) from None
                if time.monotonic() >= deadline:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(
                        command, timeout, output=stdout, stderr=stderr
                    ) from None
            else:
                return subprocess.CompletedProcess(
                    command, process.returncode, stdout, stderr
                )


def _decode_output(output: bytes | str | None, *, errors: str = "strict") -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return output.decode("utf-8", errors=errors)

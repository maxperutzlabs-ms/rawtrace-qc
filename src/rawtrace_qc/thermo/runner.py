"""Build commands and execute ThermoScanHeaderExtractor."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from rawtrace_qc import environment
from rawtrace_qc.errors import (
    OperationCancelledError,
    ThermoHelperCommandError,
    ThermoHelperExecutableNotFoundError,
    ThermoHelperExecutionError,
    ThermoHelperOutputError,
    ThermoHelperTimeoutError,
)
from rawtrace_qc.thermo.specification import (
    THERMO_HELPER_NAME,
    THERMO_HELPER_RELEASE,
    ThermoHelperSpecification,
)

if TYPE_CHECKING:
    from rawtrace_qc.extractors.protocol import PrecisionMode

THERMO_CONFIG_DIRECTORY_VARIABLE = "THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR"

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
    config_directory: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a helper command and return its captured text output.

    The command is passed as an argument sequence with shell execution disabled.
    Standard output and error are captured as bytes and decoded as UTF-8. The
    process runs with the environment of `thermo_helper_environment()`.

    Args:
        command: Argument sequence produced by
            `build_thermo_helper_command`.
        timeout: Maximum process duration in seconds. Defaults to 600.0.
        cancel: Optional event that stops the helper process when set from
            another thread. Defaults to None.
        config_directory: Folder in which the helper records the license
            acceptance. If None (default), uses `thermo_config_directory()`.

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

    process_environment = thermo_helper_environment(config_directory)
    try:
        result = (
            _execute_process(
                command_arguments, timeout=timeout, env=process_environment
            )
            if cancel is None
            else _execute_cancellable_process(
                command_arguments,
                timeout=timeout,
                cancel=cancel,
                env=process_environment,
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
            describe_helper_start_failure(command_arguments[0], error),
            stdout="",
            stderr="",
        ) from error
    except OSError as error:
        raise ThermoHelperExecutionError(
            describe_helper_start_failure(command_arguments[0], error),
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


def thermo_config_directory(
    specification: ThermoHelperSpecification | None = None,
) -> Path:
    """Return the default folder in which the helper records the license acceptance.

    The folder is `tools/<tool>/<version>/config` in the folder of
    `default_data_directory()`, next to the install folders of the helper
    version and not inside one, so that reinstalling the helper keeps the
    acceptance. Each helper version has its own folder, so the license is
    accepted again for every new helper version.
    The folder is not created, because the helper creates it when needed.

    Args:
        specification: Release specification. If None (default), uses the
            pinned release. A helper given by an explicit path also uses the
            folder of the pinned release.

    Returns:
        The absolute path of the folder.
    """
    tool_name = THERMO_HELPER_NAME if specification is None else specification.tool_name
    version = (
        THERMO_HELPER_RELEASE.version
        if specification is None
        else specification.version
    )
    root = environment.default_data_directory().resolve()
    return root / "tools" / tool_name / version / "config"


def thermo_helper_environment(
    config_directory: Path | str | None = None,
) -> dict[str, str]:
    """Return the environment variables for a helper process.

    Returns a copy of `os.environ` in which `THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR`
    names `config_directory`. If the variable is already set and not empty, its
    value is kept unchanged, so a user can choose another folder. `os.environ`
    itself is not changed.

    Args:
        config_directory: Folder in which the helper records the license
            acceptance. If None (default), uses `thermo_config_directory()`.

    Returns:
        The environment variables for the helper process.
    """
    process_environment = dict(os.environ)
    if not process_environment.get(THERMO_CONFIG_DIRECTORY_VARIABLE):
        if config_directory is None:
            config_directory = thermo_config_directory()
        process_environment[THERMO_CONFIG_DIRECTORY_VARIABLE] = str(config_directory)
    return process_environment


def describe_helper_start_failure(executable_path: Path | str, error: OSError) -> str:
    """Explain to the user why the helper executable could not be started.

    On POSIX, a `PermissionError` means that the file has no execute bit or
    that its folder does not allow running programs. On Linux, a
    `FileNotFoundError` for an existing file means that the program loader is
    missing, which is the case on musl-based systems such as Alpine Linux.

    Args:
        executable_path: Path of the helper executable.
        error: The error raised when starting the process.

    Returns:
        A message that names the executable and how to fix the problem.
    """
    if isinstance(error, PermissionError) and environment.get_platform() != "win32":
        return (
            f"ThermoScanHeaderExtractor at {executable_path} cannot be run: the "
            "file is not executable, or its folder does not allow running "
            f"programs. To make the file executable, run `chmod +x {executable_path}`."
        )
    message = (
        f"ThermoScanHeaderExtractor at {executable_path} could not be started: {error}."
    )
    if (
        isinstance(error, FileNotFoundError)
        and environment.get_platform().startswith("linux")
        and Path(executable_path).is_file()
    ):
        message += (
            " On Linux, it needs glibc (for example Ubuntu, Debian, or Fedora) and "
            "does not run on Alpine Linux or other musl-based systems."
        )
    return message


def _execute_process(
    command: Sequence[str], *, timeout: float, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _execute_cancellable_process(
    command: Sequence[str],
    *,
    timeout: float,
    cancel: threading.Event,
    env: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
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

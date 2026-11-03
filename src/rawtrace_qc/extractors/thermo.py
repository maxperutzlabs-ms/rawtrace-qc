"""Extract schema-v1 scan traces from Thermo .raw acquisitions."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from rawtrace_qc.errors import (
    ArtifactValidationError,
    ThermoHelperCommandError,
    ThermoHelperTimeoutError,
)
from rawtrace_qc.extractors.common import (
    missing_level_error,
    read_error,
    validate_extraction_options,
)
from rawtrace_qc.extractors.protocol import PrecisionMode
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.thermo.locator import locate_thermo_helper
from rawtrace_qc.thermo.runner import build_thermo_helper_command, run_thermo_helper
from rawtrace_qc.thermo.specification import ThermoHelperSpecification
from rawtrace_qc.traces import load_trace

_HELPER_SETUP_EXIT_CODES = (4, 5)


class ThermoExtractor:
    """Extract schema-v1 scan-trace Parquet files from a Thermo `.raw` file.

    Thermo `.raw` extraction wraps the external `ThermoScanHeaderExtractor`
    command-line utility. The extractor locates the helper, verifies that its
    license has been accepted, executes extraction to a temporary staging
    location, validates the resulting schema-v1 Parquet trace files, and moves
    them to the requested destination directory. Any failure cleans up partial
    outputs and raises an informative error. Currently supported runtimes:
    `win-x64` (Windows on Arm runs it under x64 emulation).
    """

    def __init__(
        self,
        helper_path: Path | str | None = None,
        *,
        data_directory: Path | str | None = None,
        specification: ThermoHelperSpecification | None = None,
        timeout: float = 600.0,
        cancel: threading.Event | None = None,
    ) -> None:
        """Initialize a ThermoExtractor instance.

        Args:
            helper_path: Optional explicit path to the ThermoScanHeaderExtractor
                executable or directory. Defaults to None.
            data_directory: Application data directory override for locating the
                managed helper. Defaults to None.
            specification: Pinned helper release metadata. If None (default),
                resolve the specification for the current host runtime when
                extracting.
            timeout: Process execution timeout in seconds. Defaults to 600.0.
            cancel: Optional event that stops a running extraction when set from
                another thread, raising `OperationCancelledError`. Defaults to
                None.
        """
        self._helper_path = Path(helper_path) if helper_path is not None else None
        self._data_directory = (
            Path(data_directory) if data_directory is not None else None
        )
        self._specification = specification
        self._timeout = timeout
        self._cancel = cancel

    def extract(
        self,
        input_path: Path,
        output_directory: Path | None = None,
        output_name: str | None = None,
        precision_mode: PrecisionMode = "low",
        *,
        select_ms1: bool = True,
        select_msn: bool = True,
    ) -> ExtractionResult:
        """Extract the selected Thermo scan levels.

        Args:
            input_path: Thermo `.raw` acquisition file.
            output_directory: Directory for output files. Defaults to the input
                file's parent directory.
            output_name: Optional literal filename stem. Defaults to the input
                filename, including `.raw`.
            precision_mode: `low` for float32 trace fields, or `high` for
                float64 trace fields. Defaults to `low`.
            select_ms1: If True (default), extract and write the MS1 artifact.
            select_msn: If True (default), extract and write the MSn artifact
                when MSn scans are present.

        Returns:
            The paths created for the selected, available MS levels. When both
            selection flags are false, no output is created and both paths are
            None after basic input validation.

        Raises:
            ValueError: If an option, filename, or input path format is invalid.
            ValueError: If an argument or input file path is invalid.
            UnsupportedPlatformError: If the current runtime has no pinned helper
                release.
            ThermoHelperNotFoundError: If the helper executable cannot be located.
            ThermoHelperVersionError: If the helper version does not match.
            ThermoHelperLicenseError: If the helper license is not accepted.
            ThermoHelperExecutionError: If the helper cannot be run or reports a
                license failure.
            ExtractionError: If the file cannot be read, reading times out, or a
                single-level selection has no scans of that level.
            ArtifactValidationError: If the produced trace files fail validation.
            OperationCancelledError: If the `cancel` event was set while extracting.
        """
        resolved_input = validate_extraction_options(
            input_path,
            output_name,
            precision_mode,
            expected_extension=".raw",
            vendor_label="Thermo",
            expect_dir=False,
        )

        if not select_ms1 and not select_msn:
            return ExtractionResult()

        executable = locate_thermo_helper(
            self._helper_path,
            data_directory=self._data_directory,
            specification=self._specification,
        )

        destination_directory = (
            resolved_input.parent
            if output_directory is None
            else output_directory.expanduser().resolve()
        )
        file_stem = output_name or resolved_input.name

        destination_existed = destination_directory.exists()
        final_ms1_path: Path | None = None
        final_msn_path: Path | None = None

        try:
            destination_directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                dir=destination_directory,
                prefix=".rawtrace-qc-thermo-",
            ) as temp_dir:
                temp_output_dir = Path(temp_dir)
                command = build_thermo_helper_command(
                    executable,
                    resolved_input,
                    output_directory=temp_output_dir,
                    output_name=file_stem,
                    precision_mode=precision_mode,
                    select_ms1=select_ms1,
                    select_msn=select_msn,
                )
                try:
                    run_thermo_helper(
                        command, timeout=self._timeout, cancel=self._cancel
                    )
                except ThermoHelperCommandError as error:
                    if error.returncode in _HELPER_SETUP_EXIT_CODES:
                        raise
                    level = "MS1" if select_ms1 else "MSn"
                    if select_ms1 != select_msn and _reports_missing_level(
                        error, level
                    ):
                        raise missing_level_error(resolved_input, level) from error
                    raise read_error(resolved_input, _helper_reason(error)) from error
                except ThermoHelperTimeoutError as error:
                    raise read_error(
                        resolved_input,
                        f"Reading timed out after {self._timeout} seconds.",
                    ) from error

                staged_ms1 = temp_output_dir / f"{file_stem}.ms1-trace.parquet"
                staged_msn = temp_output_dir / f"{file_stem}.msn-trace.parquet"

                has_ms1 = select_ms1 and staged_ms1.is_file()
                has_msn = select_msn and staged_msn.is_file()
                if not has_ms1 and not has_msn:
                    raise read_error(resolved_input, "The helper wrote no trace files.")

                if has_ms1:
                    _validate_thermo_trace(
                        staged_ms1,
                        expected_ms_level_file="ms1",
                        precision_mode=precision_mode,
                        source_filename=resolved_input.name,
                    )
                if has_msn:
                    _validate_thermo_trace(
                        staged_msn,
                        expected_ms_level_file="msn",
                        precision_mode=precision_mode,
                        source_filename=resolved_input.name,
                    )

                published_files: list[Path] = []
                try:
                    if has_ms1:
                        final_ms1_path = destination_directory / staged_ms1.name
                        staged_ms1.replace(final_ms1_path)
                        published_files.append(final_ms1_path)

                    if has_msn:
                        final_msn_path = destination_directory / staged_msn.name
                        staged_msn.replace(final_msn_path)
                        published_files.append(final_msn_path)
                except BaseException:
                    for published_file in published_files:
                        try:
                            published_file.unlink(missing_ok=True)
                        except OSError:
                            pass
                    raise
        except BaseException:
            if not destination_existed:
                try:
                    destination_directory.rmdir()
                except OSError:
                    pass
            raise

        return ExtractionResult(ms1_path=final_ms1_path, msn_path=final_msn_path)


def _validate_thermo_trace(
    path: Path,
    *,
    expected_ms_level_file: str,
    precision_mode: PrecisionMode,
    source_filename: str,
) -> None:
    artifact = load_trace(path, strict=True)
    expected_metadata = {
        "vendor": "thermo",
        "ms_level_file": expected_ms_level_file,
        "precision_mode": precision_mode,
        "row_granularity": "spectrum",
        "source_filename": source_filename,
    }
    for key, expected_value in expected_metadata.items():
        actual_value = artifact.metadata.get(key)
        if actual_value != expected_value:
            raise ArtifactValidationError(
                f"Thermo trace {path} has invalid {key}: expected "
                f"{expected_value!r}, got {actual_value!r}."
            )

    levels = artifact.table["ms_level"].to_pylist()
    if expected_ms_level_file == "ms1" and any(level != 1 for level in levels):
        raise ArtifactValidationError(
            f"Thermo MS1 trace {path} contains a non-MS1 scan."
        )
    if expected_ms_level_file == "msn" and any(level <= 1 for level in levels):
        raise ArtifactValidationError(
            f"Thermo MSn trace {path} contains a non-MS2/MSn scan."
        )


def _helper_reason(error: ThermoHelperCommandError) -> str:
    for output in (error.stderr, error.stdout):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if lines:
            return lines[-1].removeprefix("ERROR: ")
    return f"The helper exited with status {error.returncode}."


def _reports_missing_level(error: ThermoHelperCommandError, level: str) -> bool:
    return f"contains no {level} scans" in f"{error.stdout}\n{error.stderr}"

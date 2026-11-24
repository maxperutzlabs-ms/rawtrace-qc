"""Extract schema-v1 scan traces from Thermo .raw acquisitions."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from rawtrace_qc.errors import (
    ArtifactValidationError,
    ExtractionError,
    RawtraceError,
    ThermoHelperCommandError,
    ThermoHelperConfigError,
    ThermoHelperExecutionError,
    ThermoHelperLicenseError,
    ThermoHelperTimeoutError,
)
from rawtrace_qc.extractors.common import (
    access_error,
    missing_level_error,
    no_scans_error,
    read_error,
    validate_extraction_options,
    write_error,
)
from rawtrace_qc.extractors.protocol import PrecisionMode
from rawtrace_qc.models import ExtractionResult
from rawtrace_qc.thermo.locator import locate_thermo_helper
from rawtrace_qc.thermo.paths import thermo_config_directory
from rawtrace_qc.thermo.runner import build_thermo_helper_command, run_thermo_helper
from rawtrace_qc.thermo.specification import ThermoHelperSpecification
from rawtrace_qc.traces import load_trace


class ThermoExtractor:
    """Extract schema-v1 scan-trace Parquet files from a Thermo `.raw` file.

    Thermo `.raw` extraction wraps the external `ThermoScanHeaderExtractor`
    command-line utility. The extractor locates the helper, verifies that its
    license has been accepted, executes extraction to a temporary staging
    location, validates the resulting schema-v1 Parquet trace files, and moves
    them to the requested destination directory. Any failure cleans up partial
    outputs and raises an informative error.
    """

    def __init__(
        self,
        helper_path: Path | str | None = None,
        *,
        specification: ThermoHelperSpecification | None = None,
        timeout: float = 600.0,
        cancel: threading.Event | None = None,
    ) -> None:
        """Initialize a ThermoExtractor instance.

        Args:
            helper_path: Optional explicit path to the ThermoScanHeaderExtractor
                executable or directory. Defaults to None.
            specification: Pinned helper release metadata. If None (default),
                resolve the specification for the current host runtime when
                extracting.
            timeout: Process execution timeout in seconds. Defaults to 600.0.
            cancel: Optional event that stops a running extraction when set from
                another thread, raising `OperationCancelledError`. Defaults to
                None.
        """
        self._helper_path = Path(helper_path) if helper_path is not None else None
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
            UnsupportedPlatformError: If the current runtime has no pinned helper
                release.
            ThermoHelperNotFoundError: If the helper executable cannot be located.
            ThermoHelperVersionError: If the helper version does not match.
            ThermoHelperLicenseError: If the helper license is not accepted.
            ThermoHelperConfigError: If the helper cannot use its license folder.
            ThermoHelperCommandError: If the helper reports invalid usage or an
                internal error, or stops with an unknown exit code.
            ThermoHelperExecutionError: If the helper cannot be run, or reports
                success without writing a trace file.
            AcquisitionAccessError: If the helper cannot open the file.
            AcquisitionReadError: If the file is not a readable Thermo RAW file.
            NoScansError: If none of the selected MS levels has scans.
            TraceWriteError: If the trace files cannot be written to the output
                directory.
            ExtractionError: If reading times out.
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
            self._helper_path, specification=self._specification
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
            try:
                destination_directory.mkdir(parents=True, exist_ok=True)
                staging_directory = tempfile.TemporaryDirectory(
                    dir=destination_directory,
                    prefix=".rawtrace-qc-thermo-",
                )
            except OSError as error:
                raise write_error(
                    resolved_input, destination_directory, str(error)
                ) from error
            with staging_directory as temp_dir:
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
                    completed = run_thermo_helper(
                        command,
                        timeout=self._timeout,
                        cancel=self._cancel,
                        config_directory=thermo_config_directory(self._specification),
                    )
                except ThermoHelperCommandError as error:
                    raise _exit_code_error(
                        error,
                        resolved_input,
                        destination_directory,
                        select_ms1=select_ms1,
                        select_msn=select_msn,
                    ) from error
                except ThermoHelperTimeoutError as error:
                    raise ExtractionError(
                        f"Reading acquisition {resolved_input.name!r} timed out "
                        f"after {self._timeout} seconds.",
                        path=resolved_input,
                    ) from error

                staged_ms1 = temp_output_dir / f"{file_stem}.ms1-trace.parquet"
                staged_msn = temp_output_dir / f"{file_stem}.msn-trace.parquet"

                has_ms1 = select_ms1 and staged_ms1.is_file()
                has_msn = select_msn and staged_msn.is_file()
                if not has_ms1 and not has_msn:
                    raise ThermoHelperExecutionError(
                        "The Thermo tool reported success for "
                        f"{resolved_input.name!r} but wrote no trace files. This "
                        "is a bug in the Thermo tool; please report it.",
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                    )

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
                except BaseException as error:
                    for published_file in published_files:
                        try:
                            published_file.unlink(missing_ok=True)
                        except OSError:
                            pass
                    if isinstance(error, OSError):
                        raise write_error(
                            resolved_input, destination_directory, str(error)
                        ) from error
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


def _exit_code_error(
    error: ThermoHelperCommandError,
    path: Path,
    output_directory: Path,
    *,
    select_ms1: bool,
    select_msn: bool,
) -> RawtraceError:
    code = error.returncode
    detail = _helper_reason(error)
    if code == 2:
        return access_error(path, detail)
    if code == 3:
        return read_error(path, detail)
    if code == 8:
        if select_ms1 and select_msn:
            return no_scans_error(path)
        return missing_level_error(path, "MS1" if select_ms1 else "MSn")
    if code == 6:
        return write_error(path, output_directory, detail)
    if code == 4:
        return ThermoHelperLicenseError(
            "The Thermo license has not been accepted, so the Thermo tool did not "
            f"read {path.name!r}."
        )
    if code == 5:
        return ThermoHelperConfigError(
            "The Thermo tool could not use its license folder. Check that the "
            "folder is writable, or THERMO_SCAN_HEADER_EXTRACTOR_CONFIG_DIR if you "
            f"set it. Details: {detail}"
        )
    if code == 1:
        message = (
            f"rawtrace-qc called the Thermo tool incorrectly for {path.name!r}. "
            "This is a bug in rawtrace-qc; please report it."
        )
    elif code == 7:
        message = (
            f"The Thermo tool had an internal error while reading {path.name!r}. "
            "Please report it."
        )
    else:
        message = (
            f"The Thermo tool stopped unexpectedly while reading {path.name!r} "
            f"(exit code {code})."
        )
    return ThermoHelperCommandError(
        f"{message} Details: {detail}",
        returncode=code,
        stdout=error.stdout,
        stderr=error.stderr,
    )


def _helper_reason(error: ThermoHelperCommandError) -> str:
    for output in (error.stderr, error.stdout):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if lines:
            return lines[-1].removeprefix("ERROR: ")
    return f"The Thermo tool exited with code {error.returncode}."

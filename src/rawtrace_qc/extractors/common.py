"""Shared extraction validation and helper functions."""

from __future__ import annotations

from pathlib import Path

from rawtrace_qc.errors import ExtractionError


def read_error(path: Path, detail: str) -> ExtractionError:
    """Create the shared error for an acquisition that cannot be read.

    Args:
        path: Acquisition file or folder that could not be read.
        detail: Reason reported by the underlying reader.

    Returns:
        An error naming the acquisition and the reader's reason.
    """
    return ExtractionError(
        f"Could not read acquisition {path.name!r}; it may be corrupt, incomplete, "
        f"locked or inaccessible. Details: {detail}",
        path=path,
    )


def missing_level_error(path: Path, level: str) -> ExtractionError:
    """Create the shared error for a selected MS level that does not exist.

    Args:
        path: Acquisition file or folder that was read.
        level: Display name of the missing level, for example `MS1`.

    Returns:
        An error naming the acquisition and the missing level.
    """
    return ExtractionError(
        f"Acquisition {path.name!r} contains no {level} data. Select another MS "
        "level or all levels.",
        path=path,
    )


def is_valid_output_name(output_name: str) -> bool:
    """Check if an output name is a non-empty file stem without path separators.

    Args:
        output_name: Proposed output file name stem.

    Returns:
        True if the name is non-empty and contains no invalid characters.
    """
    return bool(output_name.strip()) and not any(
        character in output_name for character in '\\/:*?"<>|'
    )


def validate_extraction_options(
    input_path: Path,
    output_name: str | None,
    precision_mode: str,
    *,
    expected_extension: str,
    vendor_label: str,
    expect_dir: bool = False,
) -> Path:
    """Validate common extraction options for vendor extractors.

    Args:
        input_path: Raw acquisition input path.
        output_name: Optional literal output filename stem.
        precision_mode: Trace precision identifier, must be `low` or `high`.
        expected_extension: Case-insensitive suffix (e.g. `.raw` or `.d`).
        vendor_label: Human-readable vendor/format name for error messages.
        expect_dir: If True (default is False), expect a directory instead of a
            regular file.

    Returns:
        The resolved absolute Path of the input.

    Raises:
        ValueError: If precision_mode, output_name, or input_path format is invalid.
    """
    if precision_mode not in {"low", "high"}:
        raise ValueError(
            f"Invalid precision_mode {precision_mode!r}. Must be 'low' or 'high'."
        )

    if output_name is not None and not is_valid_output_name(output_name):
        raise ValueError(
            f"Invalid output_name {output_name!r}. Must be a non-empty valid file "
            "name without path separators."
        )

    resolved = input_path.expanduser().resolve()
    if expect_dir:
        if (
            resolved.suffix.casefold() != expected_extension.casefold()
            or not resolved.is_dir()
        ):
            raise ValueError(
                f"Expected a {vendor_label} {expected_extension} directory, "
                f"got: {resolved}"
            )
    else:
        if (
            resolved.suffix.casefold() != expected_extension.casefold()
            or not resolved.is_file()
        ):
            raise ValueError(
                f"Expected a {vendor_label} {expected_extension} file, got: {resolved}"
            )

    return resolved

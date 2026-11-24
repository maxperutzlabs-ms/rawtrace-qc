"""Folders of the ThermoScanHeaderExtractor helper in the application data folder."""

from __future__ import annotations

from pathlib import Path

from rawtrace_qc import environment
from rawtrace_qc.thermo.specification import (
    THERMO_HELPER_NAME,
    THERMO_HELPER_RELEASE,
    ThermoHelperSpecification,
    resolve_thermo_helper_specification,
)


def managed_thermo_helper_directory(
    specification: ThermoHelperSpecification | None = None,
) -> Path:
    """Return the managed install folder of a helper release for one runtime.

    The folder is `tools/<tool>/<version>/<runtime>` in the folder of
    `default_data_directory()`. It is not created by this function.

    Args:
        specification: Release specification. If None (default), resolves the
            specification for the current host runtime.

    Returns:
        The absolute path of the folder.

    Raises:
        UnsupportedPlatformError: If no specification is given and the current
            runtime has no pinned helper release.
    """
    if specification is None:
        specification = resolve_thermo_helper_specification()
    return (
        _version_directory(specification.tool_name, specification.version)
        / specification.runtime
    )


def thermo_config_directory(
    specification: ThermoHelperSpecification | None = None,
) -> Path:
    """Return the default folder in which the helper records the license acceptance.

    The folder is `tools/<tool>/<version>/config` in the folder of
    `default_data_directory()`. It is next to the install folders of the
    helper version and not inside one, so that reinstalling the helper keeps
    the acceptance. Each helper version has its own folder, so the license is
    accepted again for every new helper version. The folder is not created,
    because the helper creates it when needed.

    Args:
        specification: Release specification. If None (default), uses the
            pinned release. A helper given by an explicit path also uses the
            folder of the pinned release.

    Returns:
        The absolute path of the folder.
    """
    if specification is None:
        return (
            _version_directory(THERMO_HELPER_NAME, THERMO_HELPER_RELEASE.version)
            / "config"
        )
    return _version_directory(specification.tool_name, specification.version) / "config"


def _version_directory(tool_name: str, version: str) -> Path:
    return (
        environment.default_data_directory().resolve() / "tools" / tool_name / version
    )

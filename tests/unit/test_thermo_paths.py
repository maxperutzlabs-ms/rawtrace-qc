from __future__ import annotations

from pathlib import Path

from rawtrace_qc.thermo import (
    THERMO_HELPER_NAME,
    THERMO_HELPER_RELEASE,
    managed_thermo_helper_directory,
    thermo_config_directory,
)
from tests.support.thermo_helper import WIN_X64_SPECIFICATION


class TestManagedThermoHelperDirectory:
    def test_returns_the_runtime_folder_of_the_release_without_creating_it(self, isolated_data_directory: Path) -> None:
        directory = managed_thermo_helper_directory(WIN_X64_SPECIFICATION)

        assert directory == (
            isolated_data_directory.resolve()
            / "tools"
            / WIN_X64_SPECIFICATION.tool_name
            / WIN_X64_SPECIFICATION.version
            / "win-x64"
        )
        assert not isolated_data_directory.exists()


class TestThermoConfigDirectory:
    def test_returns_the_folder_of_the_pinned_release_next_to_its_runtime_folders(
        self, isolated_data_directory: Path
    ) -> None:
        config_directory = thermo_config_directory()

        assert config_directory == (
            isolated_data_directory.resolve() / "tools" / THERMO_HELPER_NAME / THERMO_HELPER_RELEASE.version / "config"
        )
        assert config_directory.parent == managed_thermo_helper_directory(WIN_X64_SPECIFICATION).parent

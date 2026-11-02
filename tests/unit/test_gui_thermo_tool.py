"""Tests for the Thermo Tool window and its use from the main window."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rawtrace_qc import environment
from rawtrace_qc.discovery import DiscoveryCandidate, FileFormat, Vendor
from rawtrace_qc.errors import ThermoHelperDownloadError
from rawtrace_qc.gui import thermo_tool
from rawtrace_qc.gui.app import _load_qt, create_window
from rawtrace_qc.gui.reporting import ReportGenerationResult
from rawtrace_qc.gui.theme import get_active_theme
from rawtrace_qc.gui.thermo_tool import (
    create_thermo_tool_dialog,
    describe_thermo_status,
    thermo_asset_label,
    thermo_tool_needs_attention,
    thermo_tool_required_message,
    thermo_tool_tooltip,
)
from rawtrace_qc.thermo import THERMO_HELPER_RELEASE, ThermoHelperState, ThermoHelperStatus

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

ALL_STATES = tuple(ThermoHelperState)
UNREADY_STATES = tuple(state for state in ALL_STATES if state is not ThermoHelperState.READY)


def _status(state: ThermoHelperState, message: str = "helper message") -> ThermoHelperStatus:
    installed = state in {ThermoHelperState.READY, ThermoHelperState.UNLICENSED}
    return ThermoHelperStatus(
        state=state,
        path=Path("helper.exe") if installed else None,
        version="0.2.0" if installed else None,
        license_accepted=state is ThermoHelperState.READY,
        message=message,
    )


def _wait_until(application: Any, condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "Timed out waiting for the GUI."
        application.processEvents()
        time.sleep(0.005)
    application.processEvents()


def _settle(application: Any) -> None:
    QtCore.QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(5):
        application.processEvents()


@pytest.fixture(scope="module")
def qt_application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def host_status(monkeypatch: pytest.MonkeyPatch) -> dict[str, ThermoHelperStatus]:
    current = {"status": _status(ThermoHelperState.NOT_INSTALLED)}

    def get_status() -> ThermoHelperStatus:
        return current["status"]

    monkeypatch.setattr(thermo_tool, "get_thermo_helper_status", get_status)
    monkeypatch.setattr("rawtrace_qc.gui.app.get_thermo_helper_status", get_status)
    monkeypatch.setattr(environment, "get_platform", lambda: "win32")
    monkeypatch.setattr(environment, "get_machine", lambda: "AMD64")
    return current


@pytest.fixture
def dialog(qt_application, host_status) -> Any:
    def build(status: ThermoHelperState, received: list[ThermoHelperStatus] | None = None) -> Any:
        host_status["status"] = _status(status)
        collected = received if received is not None else []
        created = create_thermo_tool_dialog(QtCore, _load_qt()[1], QtWidgets, None, collected.append)
        _settle(qt_application)
        return created

    return build


class TestDescribeThermoStatus:
    def test_ready_offers_only_reviewing_the_license(self) -> None:
        view = describe_thermo_status(_status(ThermoHelperState.READY))

        assert (view.installation_ok, view.license_ok) == (True, True)
        assert (view.can_install, view.can_review_license, view.can_accept_license) == (False, True, False)

    def test_unlicensed_offers_reviewing_and_accepting_the_license(self) -> None:
        view = describe_thermo_status(_status(ThermoHelperState.UNLICENSED))

        assert (view.installation_ok, view.license_ok) == (True, False)
        assert (view.can_install, view.can_review_license, view.can_accept_license) == (False, True, True)

    def test_not_installed_offers_only_installation(self) -> None:
        view = describe_thermo_status(_status(ThermoHelperState.NOT_INSTALLED))

        assert (view.can_install, view.can_review_license, view.can_accept_license) == (True, False, False)

    def test_invalid_version_explains_the_problem_and_offers_the_folder(self) -> None:
        view = describe_thermo_status(_status(ThermoHelperState.INVALID_VERSION, "wrong version"))

        assert view.can_open_folder
        assert not view.can_install
        assert "wrong version" in view.detail

    def test_unsupported_platform_offers_no_actions(self) -> None:
        view = describe_thermo_status(_status(ThermoHelperState.UNSUPPORTED_PLATFORM, "linux-x64 unsupported"))

        assert not (view.can_install or view.can_review_license or view.can_accept_license or view.can_open_folder)
        assert view.detail == "linux-x64 unsupported"


class TestThermoToolNeedsAttention:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (ThermoHelperState.READY, False),
            (ThermoHelperState.UNSUPPORTED_PLATFORM, False),
            (ThermoHelperState.UNLICENSED, True),
            (ThermoHelperState.NOT_INSTALLED, True),
            (ThermoHelperState.INVALID_VERSION, True),
        ],
    )
    def test_flags_only_states_the_user_can_fix(self, state: ThermoHelperState, expected: bool) -> None:
        assert thermo_tool_needs_attention(_status(state)) is expected


class TestThermoToolText:
    @pytest.mark.parametrize("state", ALL_STATES)
    def test_every_state_has_a_tooltip(self, state: ThermoHelperState) -> None:
        assert thermo_tool_tooltip(_status(state)).startswith("Thermo Tool: ")

    @pytest.mark.parametrize("state", UNREADY_STATES)
    def test_every_unready_state_has_a_required_message_without_commands(self, state: ThermoHelperState) -> None:
        message = thermo_tool_required_message(_status(state))

        assert "Thermo Tool" in message
        assert "--agree-to-terms" not in message


class TestThermoAssetLabel:
    def test_shows_asset_name_of_host_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "win32")
        monkeypatch.setattr(environment, "get_machine", lambda: "ARM64")

        assert thermo_asset_label() == "ThermoScanHeaderExtractor-v0.2.0-win-x64.zip"

    def test_names_unsupported_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")
        monkeypatch.setattr(environment, "get_machine", lambda: "x86_64")

        assert thermo_asset_label() == "Not supported on linux-x64"

    def test_handles_undetectable_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "freebsd13")
        monkeypatch.setattr(environment, "get_machine", lambda: "amd64")

        assert thermo_asset_label() == "Not supported on this system"


class TestThermoToolDialog:
    def test_not_installed_shows_install_buttons_and_disables_license_buttons(self, dialog) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)

        assert window.installation_status.text() == "Not installed"
        assert not window.download_button.isHidden()
        assert not window.install_zip_button.isHidden()
        assert not window.show_license_button.isEnabled()
        assert not window.accept_license_button.isEnabled()

    def test_unlicensed_hides_install_buttons_and_enables_license_buttons(self, dialog) -> None:
        window = dialog(ThermoHelperState.UNLICENSED)

        assert window.license_status.text() == "Not accepted"
        assert window.download_button.isHidden()
        assert window.show_license_button.isEnabled()
        assert window.accept_license_button.isEnabled()

    def test_ready_disables_accept_and_keeps_show_license(self, dialog) -> None:
        window = dialog(ThermoHelperState.READY)

        assert window.license_status.text() == "Accepted"
        assert window.show_license_button.isEnabled()
        assert not window.accept_license_button.isEnabled()

    def test_invalid_version_shows_the_helper_message_and_folder_button(self, dialog) -> None:
        window = dialog(ThermoHelperState.INVALID_VERSION)

        assert not window.open_folder_button.isHidden()
        assert "helper message" in window.detail_label.text()

    def test_unsupported_platform_shows_no_install_location(self, dialog, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(environment, "get_platform", lambda: "linux")

        window = dialog(ThermoHelperState.UNSUPPORTED_PLATFORM)

        assert window.location_note.text() == ""
        assert window.asset_label.text() == "Not supported on linux-x64"
        assert window.download_button.isHidden()

    def test_release_link_opens_the_pinned_release_page(self, dialog) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)

        assert window.release_link.openExternalLinks()
        assert THERMO_HELPER_RELEASE.release_page_url in window.release_link.text()

    def test_reports_every_checked_status(self, dialog) -> None:
        received: list[ThermoHelperStatus] = []

        dialog(ThermoHelperState.UNLICENSED, received)

        assert [status.state for status in received] == [ThermoHelperState.UNLICENSED]

    def test_download_installs_while_waiting_then_checks_status_again(
        self, dialog, host_status, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)
        calls: list[object] = []
        wait_visible: list[bool] = []

        def install(archive_path: str | None = None) -> Path:
            calls.append(archive_path)
            host_status["status"] = _status(ThermoHelperState.UNLICENSED)
            return Path("helper.exe")

        monkeypatch.setattr(thermo_tool, "install_thermo_helper", install)

        window.download_button.click()
        wait_visible.append(window._wait_dialog.isVisible() if window._wait_dialog is not None else False)
        _wait_until(qt_application, lambda: window.license_status.text() == "Not accepted")

        assert calls == [None]
        assert wait_visible == [True]
        assert window._wait_dialog is None

    def test_wait_dialog_cannot_be_dismissed(self, dialog, qt_application, monkeypatch: pytest.MonkeyPatch) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)
        release = QtCore.QSemaphore(0)
        monkeypatch.setattr(thermo_tool, "install_thermo_helper", lambda: release.acquire())

        window.download_button.click()
        wait_dialog = window._wait_dialog
        wait_dialog.reject()
        wait_dialog.close()
        visible_after_dismissal = wait_dialog.isVisible()
        release.release()
        _settle(qt_application)

        assert visible_after_dismissal
        assert window._wait_dialog is None

    def test_install_from_zip_passes_the_selected_file(
        self, dialog, host_status, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)
        calls: list[object] = []

        def install(archive_path: str) -> Path:
            calls.append(archive_path)
            host_status["status"] = _status(ThermoHelperState.UNLICENSED)
            return Path("helper.exe")

        monkeypatch.setattr(thermo_tool, "install_thermo_helper", install)
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_args: ("C:/Downloads/helper.zip", ""))

        window.install_zip_button.click()
        _wait_until(qt_application, lambda: window.license_status.text() == "Not accepted")

        assert calls == ["C:/Downloads/helper.zip"]

    def test_cancelling_zip_selection_installs_nothing(self, dialog, monkeypatch: pytest.MonkeyPatch) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)
        calls: list[object] = []
        monkeypatch.setattr(thermo_tool, "install_thermo_helper", calls.append)
        monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *_args: ("", ""))

        window.install_zip_button.click()

        assert calls == []
        assert window._wait_dialog is None

    def test_failed_download_shows_the_error_and_checks_status_again(
        self, dialog, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.NOT_INSTALLED)
        errors: list[str] = []

        def fail_install() -> Path:
            raise ThermoHelperDownloadError("Network or proxy failure.")

        monkeypatch.setattr(thermo_tool, "install_thermo_helper", fail_install)
        monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda _parent, _title, text: errors.append(text))

        window.download_button.click()
        _wait_until(qt_application, lambda: bool(errors))
        _settle(qt_application)

        assert errors == ["Network or proxy failure."]
        assert window.installation_status.text() == "Not installed"
        assert window._wait_dialog is None

    def test_show_license_displays_terms_without_accepting(
        self, dialog, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.UNLICENSED)
        accepted: list[bool] = []
        shown: list[str] = []
        monkeypatch.setattr(thermo_tool, "get_thermo_license_text", lambda: "The terms")
        monkeypatch.setattr(thermo_tool, "accept_thermo_license", lambda: accepted.append(True))

        def inspect_popup() -> None:
            popup = qt_application.activeModalWidget()
            text = popup.findChild(QtWidgets.QPlainTextEdit, "thermoLicenseText")
            if text is None:
                QtCore.QTimer.singleShot(5, inspect_popup)
                return
            shown.append(text.toPlainText())
            popup.accept()

        QtCore.QTimer.singleShot(5, inspect_popup)
        window.show_license_button.click()
        _wait_until(qt_application, lambda: bool(shown))

        assert shown == ["The terms"]
        assert accepted == []
        window._wait_dialog = None

    def test_accept_license_records_acceptance_then_displays_terms(
        self, dialog, host_status, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.UNLICENSED)
        order: list[str] = []
        shown: list[str] = []

        def get_terms() -> str:
            order.append("terms")
            return "The terms"

        def accept() -> None:
            order.append("accept")
            host_status["status"] = _status(ThermoHelperState.READY)

        monkeypatch.setattr(thermo_tool, "get_thermo_license_text", get_terms)
        monkeypatch.setattr(thermo_tool, "accept_thermo_license", accept)

        def inspect_popup() -> None:
            popup = qt_application.activeModalWidget()
            text = popup.findChild(QtWidgets.QPlainTextEdit, "thermoLicenseText")
            if text is None:
                QtCore.QTimer.singleShot(5, inspect_popup)
                return
            shown.append(text.toPlainText())
            popup.accept()

        QtCore.QTimer.singleShot(5, inspect_popup)
        window.accept_license_button.click()
        _wait_until(qt_application, lambda: bool(shown) and window.license_status.text() == "Accepted")

        assert order == ["terms", "accept"]
        assert shown == ["The terms"]

    def test_accept_license_records_nothing_when_terms_cannot_be_loaded(
        self, dialog, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = dialog(ThermoHelperState.UNLICENSED)
        accepted: list[bool] = []
        errors: list[str] = []

        def fail_terms() -> str:
            raise ThermoHelperDownloadError("No terms.")

        monkeypatch.setattr(thermo_tool, "get_thermo_license_text", fail_terms)
        monkeypatch.setattr(thermo_tool, "accept_thermo_license", lambda: accepted.append(True))
        monkeypatch.setattr(QtWidgets.QMessageBox, "critical", lambda _parent, _title, text: errors.append(text))

        window.accept_license_button.click()
        _wait_until(qt_application, lambda: bool(errors))

        assert accepted == []
        assert errors == ["No terms."]


class TestMainWindowThermoStatus:
    def _window(self, tmp_path: Path) -> Any:
        qt_core, qt_gui, qt_widgets = _load_qt()
        return create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")

    def test_shows_attention_dot_and_tooltip_when_setup_is_needed(
        self, tmp_path: Path, qt_application, host_status
    ) -> None:
        window = self._window(tmp_path)

        window.refresh_thermo_status()
        _settle(qt_application)

        assert not window.thermo_tool_attention.isHidden()
        assert window.thermo_tool_button.toolTip() == "Thermo Tool: not installed"
        window.close()

    def test_attention_dot_is_painted_in_the_attention_color(self, tmp_path: Path, qt_application, host_status) -> None:
        window = self._window(tmp_path)

        window.refresh_thermo_status()
        _settle(qt_application)
        center = window.thermo_tool_attention.grab().toImage().pixelColor(5, 5)

        assert center.name().casefold() == get_active_theme().header_attention.casefold()
        window.close()

    def test_hides_attention_dot_when_ready(self, tmp_path: Path, qt_application, host_status) -> None:
        host_status["status"] = _status(ThermoHelperState.READY)
        window = self._window(tmp_path)

        window.refresh_thermo_status()
        _settle(qt_application)

        assert window.thermo_tool_attention.isHidden()
        window.close()

    def test_hides_attention_dot_on_unsupported_platform(self, tmp_path: Path, qt_application, host_status) -> None:
        host_status["status"] = _status(ThermoHelperState.UNSUPPORTED_PLATFORM)
        window = self._window(tmp_path)

        window.refresh_thermo_status()
        _settle(qt_application)

        assert window.thermo_tool_attention.isHidden()
        window.close()

    def test_settings_dialog_has_no_thermo_card(self, tmp_path: Path, qt_application, host_status) -> None:
        window = self._window(tmp_path)
        titles: list[str] = []

        def inspect_dialog() -> None:
            dialog = qt_application.activeModalWidget()
            titles.extend(label.text() for label in dialog.findChildren(QtWidgets.QLabel, "settingsCardTitle"))
            dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        window._open_settings()

        assert titles == ["Appearance", "File filters", "Storage"]
        window.close()


class TestGenerateWithThermoFiles:
    def _window_with_candidates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *vendors: Vendor) -> Any:
        qt_core, qt_gui, qt_widgets = _load_qt()
        window = create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")
        formats = {Vendor.THERMO: FileFormat.RAW, Vendor.BRUKER: FileFormat.D}
        candidates = tuple(
            DiscoveryCandidate(tmp_path / f"sample-{index}", vendor, formats[vendor])
            for index, vendor in enumerate(vendors)
        )
        monkeypatch.setattr(window._selection, "active_selected", lambda: candidates)
        return window

    @pytest.fixture
    def reports(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
        generated: list[tuple[Any, ...]] = []

        def fake_generate(candidates: tuple[Any, ...], *_args: Any, **_kwargs: Any) -> ReportGenerationResult:
            generated.append(candidates)
            return ReportGenerationResult(tmp_path / "report.html", 1, 0)

        monkeypatch.setattr("rawtrace_qc.gui.app.generate_report", fake_generate)
        monkeypatch.setattr("rawtrace_qc.gui.app.webbrowser.open", lambda _uri: True)
        return generated

    @pytest.fixture
    def prompts(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        shown: list[str] = []

        def fake_exec(message: Any) -> int:
            shown.append(message.text())
            return 0

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
        return shown

    @pytest.mark.parametrize("state", UNREADY_STATES)
    def test_blocks_report_and_explains_when_tool_is_not_ready(
        self,
        tmp_path: Path,
        qt_application,
        host_status,
        reports,
        prompts,
        monkeypatch: pytest.MonkeyPatch,
        state: ThermoHelperState,
    ) -> None:
        host_status["status"] = _status(state)
        window = self._window_with_candidates(tmp_path, monkeypatch, Vendor.THERMO)

        window._generate()
        _settle(qt_application)

        assert reports == []
        assert len(prompts) == 1
        assert window.generate_button.isEnabled()
        assert window._worker is None
        window.close()

    def test_blocks_mixed_batch_when_tool_is_not_ready(
        self, tmp_path: Path, qt_application, host_status, reports, prompts, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = self._window_with_candidates(tmp_path, monkeypatch, Vendor.BRUKER, Vendor.THERMO)

        window._generate()
        _settle(qt_application)

        assert reports == []
        assert len(prompts) == 1
        window.close()

    def test_generates_report_when_tool_is_ready(
        self, tmp_path: Path, qt_application, host_status, reports, prompts, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        host_status["status"] = _status(ThermoHelperState.READY)
        window = self._window_with_candidates(tmp_path, monkeypatch, Vendor.THERMO)

        window._generate()
        _wait_until(qt_application, lambda: window._worker is None and bool(reports))

        assert len(reports) == 1
        assert prompts == []
        window.close()

    def test_bruker_files_generate_without_checking_the_tool(
        self, tmp_path: Path, qt_application, host_status, reports, prompts, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checks: list[bool] = []
        monkeypatch.setattr(
            "rawtrace_qc.gui.app.get_thermo_helper_status",
            lambda: checks.append(True) or _status(ThermoHelperState.NOT_INSTALLED),
        )
        window = self._window_with_candidates(tmp_path, monkeypatch, Vendor.BRUKER)

        window._generate()
        _wait_until(qt_application, lambda: window._worker is None and bool(reports))

        assert len(reports) == 1
        assert checks == []
        assert prompts == []
        window.close()

    def test_prompt_opens_the_thermo_tool_when_requested(
        self, tmp_path: Path, qt_application, host_status, reports, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window = self._window_with_candidates(tmp_path, monkeypatch, Vendor.THERMO)
        opened: list[bool] = []
        monkeypatch.setattr(window, "_open_thermo_tool", lambda: opened.append(True))

        def click_open() -> None:
            message = qt_application.activeModalWidget()
            next(button for button in message.buttons() if button.text() == "Open Thermo Tool").click()

        QtCore.QTimer.singleShot(50, click_open)
        window._prompt_thermo_tool_setup(_status(ThermoHelperState.NOT_INSTALLED))

        assert opened == [True]
        window.close()

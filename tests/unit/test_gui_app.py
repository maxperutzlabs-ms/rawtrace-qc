"""Qt-level tests for the rawtrace-qc desktop application."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from rawtrace_qc.discovery import DiscoveryCandidate, FileFormat, Vendor
from rawtrace_qc.errors import OperationCancelledError
from rawtrace_qc.gui.app import _dialog_start_directory, _load_qt, create_window
from rawtrace_qc.gui.config import load_settings
from rawtrace_qc.gui.patterns import FilenamePattern, PatternMode
from rawtrace_qc.gui.reporting import ExcludedFile, ReportGenerationResult, ReportProgress, ReportStage
from rawtrace_qc.gui.theme import DARK_THEME, get_active_theme
from rawtrace_qc.gui.workflow import ExclusionReason, FileExclusion
from rawtrace_qc.thermo import ThermoHelperState, ThermoHelperStatus

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def _wait_until(application, condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "Timed out waiting for the GUI."
        application.processEvents()
        time.sleep(0.005)
    application.processEvents()


@pytest.fixture(scope="module")
def qt_application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class TestCandidatePatterns:
    def test_editing_registered_pattern_updates_candidates_and_custom_pattern_defaults(
        self,
        tmp_path: Path,
        qt_application,
    ) -> None:
        qt_core, qt_gui, qt_widgets = _load_qt()
        window = create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")
        pattern = FilenamePattern("Existing", "first", PatternMode.INCLUDE)
        window._saved_patterns = [pattern]
        window._active_pattern_keys = {(pattern.name, pattern.expression)}
        window._selection.set_candidates(
            (
                DiscoveryCandidate(tmp_path / "first.raw", Vendor.THERMO, FileFormat.RAW),
                DiscoveryCandidate(tmp_path / "second.raw", Vendor.THERMO, FileFormat.RAW),
            )
        )
        result: dict[str, object] = {}

        def inspect_dialog() -> None:
            try:
                dialog = next(
                    widget
                    for widget in qt_application.topLevelWidgets()
                    if isinstance(widget, qt_widgets.QDialog) and widget.isVisible()
                )
                pattern_table = dialog.findChild(qt_widgets.QTableWidget)
                custom_expression = dialog.findChild(qt_widgets.QLineEdit)
                add_button = next(
                    button
                    for button in dialog.findChildren(qt_widgets.QPushButton)
                    if button.text() == "Add custom pattern"
                )
                assert pattern_table is not None
                assert custom_expression is not None
                pattern_table.item(0, 2).setText("second")
                result["after_edit"] = {
                    entry.candidate.path.name: entry.included for entry in window._selection.candidates
                }
                custom_expression.setText("first")
                add_button.click()
                mode_selector = pattern_table.cellWidget(1, 3)
                mode_group = mode_selector.findChild(qt_widgets.QButtonGroup)
                assert mode_group is not None
                result["custom"] = (
                    pattern_table.item(1, 1).text(),
                    pattern_table.item(1, 2).text(),
                    mode_group.checkedId(),
                )
                result["after_custom"] = {
                    entry.candidate.path.name: entry.included for entry in window._selection.candidates
                }
            except (AssertionError, AttributeError, StopIteration) as error:
                result["error"] = error
            finally:
                dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        window._open_candidates()

        assert "error" not in result
        assert result["after_edit"] == {"second.raw": True, "first.raw": False}
        assert result["custom"] == ("Custom 1", "first", 0)
        assert result["after_custom"] == {"first.raw": True, "second.raw": True}
        window.close()


def test_dialog_start_directory_uses_selected_path_or_appdata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appdata = tmp_path / "appdata"
    selected_directory = tmp_path / "selected"
    selected_directory.mkdir()
    selected_file = selected_directory / "helper.exe"
    selected_file.write_bytes(b"helper")
    monkeypatch.setattr(
        "rawtrace_qc.gui.app.default_data_directory",
        lambda: appdata,
    )

    assert _dialog_start_directory(str(selected_directory)) == str(selected_directory)
    assert _dialog_start_directory(str(selected_file)) == str(selected_directory)
    assert _dialog_start_directory(str(tmp_path / "missing")) == str(appdata)


class TestSettingsDialog:
    def test_theme_dropdown_opens_below_when_possible_and_shows_every_option(
        self,
        tmp_path: Path,
        qt_application,
    ) -> None:
        qt_core, qt_gui, qt_widgets = _load_qt()
        window = create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")
        result: dict[str, object] = {}
        dialog = None
        theme_combo = None

        def inspect_dialog() -> None:
            nonlocal dialog, theme_combo
            try:
                dialog = next(
                    widget
                    for widget in qt_application.topLevelWidgets()
                    if isinstance(widget, qt_widgets.QDialog) and widget.isVisible()
                )
                theme_combo = dialog.findChild(qt_widgets.QComboBox, "themeMode")
                assert theme_combo is not None
                theme_combo.showPopup()
                qt_application.processEvents()

                popup = theme_combo.findChild(qt_widgets.QFrame)
                assert popup is not None
                view = theme_combo.view()
                visible_rows = [view.visualRect(view.model().index(index, 0)) for index in range(theme_combo.count())]
                assert all(row.isValid() for row in visible_rows)
                result["all_rows_fit"] = all(view.viewport().rect().contains(row) for row in visible_rows)

                screen = theme_combo.screen()
                assert screen is not None
                available = screen.availableGeometry()
                popup_origin = popup.mapToGlobal(qt_core.QPoint(0, 0))
                popup_bounds = qt_core.QRect(popup_origin, popup.size())
                result["within_work_area"] = available.contains(popup_bounds)
                below_y = theme_combo.mapToGlobal(qt_core.QPoint(0, theme_combo.height())).y() + 2
                below_space = available.bottom() + 1 - below_y
                result["below_fits"] = below_space >= popup.height()
                result["below_selected_when_possible"] = below_space < popup.height() or popup_origin.y() == below_y
            except (AssertionError, AttributeError, StopIteration) as error:
                result["error"] = error
            finally:
                if theme_combo is not None:
                    theme_combo.hidePopup()
                if dialog is not None:
                    dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        window._open_settings()

        assert "error" not in result
        assert result["all_rows_fit"] is True
        assert result["within_work_area"] is True
        assert result["below_fits"] is True
        assert result["below_selected_when_possible"] is True
        window.close()

    def test_apply_closes_without_persisting(
        self,
        tmp_path: Path,
        qt_application,
    ) -> None:
        qt_core, qt_gui, qt_widgets = _load_qt()
        settings_path = tmp_path / "settings.json"
        window = create_window(qt_core, qt_gui, qt_widgets, settings_path)
        result: dict[str, object] = {}
        dialog = None

        def inspect_dialog() -> None:
            nonlocal dialog
            try:
                dialog = next(
                    widget
                    for widget in qt_application.topLevelWidgets()
                    if isinstance(widget, qt_widgets.QDialog) and widget.isVisible()
                )
                buttons = {button.text(): button for button in dialog.findChildren(qt_widgets.QPushButton)}
                assert {"Apply", "Save", "Cancel", "Reset defaults"} <= buttons.keys()
                theme_combo = dialog.findChild(qt_widgets.QComboBox, "themeMode")
                assert theme_combo is not None
                assert [theme_combo.itemText(index) for index in range(theme_combo.count())] == [
                    "System",
                    "Light",
                    "Dark",
                ]
                cache_edit = next(
                    edit
                    for edit in dialog.findChildren(qt_widgets.QLineEdit)
                    if edit.text() == str(window._settings.cache_directory)
                )
                cache_edit.setText(str(tmp_path / "session-cache"))
                buttons["Reset defaults"].click()
                assert cache_edit.text() == str(window._settings.cache_directory)
                assert theme_combo.currentData() == "system"
                assert window._settings.cache_directory != tmp_path / "session-cache"
                cache_edit.setText(str(tmp_path / "session-cache"))
                theme_combo.setCurrentIndex(2)
                buttons["Apply"].click()
                result["applied_path"] = window._settings.cache_directory
                result["theme_mode"] = window._settings.theme_mode
                result["active_theme"] = get_active_theme()
                result["exists_after_apply"] = settings_path.exists()
                result["dialog_closed"] = not dialog.isVisible()
            except (AssertionError, AttributeError, StopIteration) as error:
                result["error"] = error
            finally:
                if dialog is not None and dialog.isVisible():
                    dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        window._open_settings()

        assert "error" not in result
        assert result["applied_path"] == tmp_path / "session-cache"
        assert result["theme_mode"] == "dark"
        assert result["active_theme"] is DARK_THEME
        assert result["exists_after_apply"] is False
        assert result["dialog_closed"] is True
        window.close()

    def test_apply_and_save_closes_and_persists(
        self,
        tmp_path: Path,
        qt_application,
    ) -> None:
        qt_core, qt_gui, qt_widgets = _load_qt()
        settings_path = tmp_path / "settings.json"
        window = create_window(qt_core, qt_gui, qt_widgets, settings_path)
        result: dict[str, object] = {}
        dialog = None

        def inspect_dialog() -> None:
            nonlocal dialog
            try:
                dialog = next(
                    widget
                    for widget in qt_application.topLevelWidgets()
                    if isinstance(widget, qt_widgets.QDialog) and widget.isVisible()
                )
                buttons = {button.text(): button for button in dialog.findChildren(qt_widgets.QPushButton)}
                cache_edit = next(
                    edit
                    for edit in dialog.findChildren(qt_widgets.QLineEdit)
                    if edit.text() == str(window._settings.cache_directory)
                )
                theme_combo = dialog.findChild(qt_widgets.QComboBox, "themeMode")
                assert theme_combo is not None
                cache_edit.setText(str(tmp_path / "saved-cache"))
                theme_combo.setCurrentIndex(2)
                buttons["Save"].click()
                result["saved_path"] = load_settings(settings_path).cache_directory
                result["saved_theme_mode"] = load_settings(settings_path).theme_mode
                result["dialog_closed"] = not dialog.isVisible()
            except (AssertionError, AttributeError, StopIteration) as error:
                result["error"] = error
            finally:
                if dialog is not None and dialog.isVisible():
                    dialog.reject()

        QtCore.QTimer.singleShot(0, inspect_dialog)
        window._open_settings()

        assert "error" not in result
        assert result["saved_path"] == tmp_path / "saved-cache"
        assert result["saved_theme_mode"] == "dark"
        assert result["dialog_closed"] is True
        window.close()


class TestReportStatusAndExclusions:
    @pytest.fixture
    def window(self, tmp_path: Path, qt_application):
        qt_core, qt_gui, qt_widgets = _load_qt()
        window = create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")
        yield window
        _wait_until(qt_application, lambda: window._worker is None and window._scan_task is None)
        window.close()

    @pytest.fixture
    def browser(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        opened: list[str] = []
        monkeypatch.setattr("rawtrace_qc.gui.app.webbrowser.open", opened.append)
        return opened

    def _add_bruker_files(self, window, tmp_path: Path, *names: str) -> tuple[DiscoveryCandidate, ...]:
        candidates = tuple(DiscoveryCandidate(tmp_path / name, Vendor.BRUKER, FileFormat.D) for name in names)
        window._selection._add_candidates(candidates)
        window._refresh_selected()
        return candidates

    def _patch_generate(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *bad: str) -> None:
        def fake_generate(candidates, *_args, on_excluded, **_kwargs) -> ReportGenerationResult:
            excluded = []
            for candidate in candidates:
                if candidate.path.name in bad:
                    file = ExcludedFile(candidate, FileExclusion(ExclusionReason.EXTRACTION_FAILED, "unreadable"))
                    on_excluded(file)
                    excluded.append(file)
            included = tuple(candidate for candidate in candidates if candidate.path.name not in bad)
            return ReportGenerationResult(tmp_path / "report.html", 1, 0, included, tuple(excluded))

        monkeypatch.setattr("rawtrace_qc.gui.app.generate_report", fake_generate)

    def _generate_and_wait(self, window, qt_application) -> None:
        window._generate()
        _wait_until(qt_application, lambda: window._worker is None)
        qt_application.processEvents()

    def test_report_ready_status_appears_and_browser_opens(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "a.d", "b.d")
        self._patch_generate(monkeypatch, tmp_path)

        self._generate_and_wait(window, qt_application)

        assert window.report_status.full_text() == "Report ready: 2 file(s)"
        assert window.report_status.property("state") == "ok"
        assert len(browser) == 1
        assert not window.open_report_button.isHidden()
        assert window.cancel_button.isHidden()
        assert window.generate_button.isEnabled()

    def test_failed_file_is_marked_unchecked_and_cannot_be_ticked_again(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "good.d", "bad.d")
        self._patch_generate(monkeypatch, tmp_path, "bad.d")

        self._generate_and_wait(window, qt_application)
        window._set_all_selected(True)

        item = window.selected_list.item(1)
        assert not item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable
        assert item.data(QtCore.Qt.ItemDataRole.UserRole.value + 1) == "Extraction failed"
        assert "unreadable" in item.toolTip()
        assert "add it again" in item.toolTip()
        assert [entry.path.name for entry in window._selection.active_selected()] == ["good.d"]
        assert window.selected_count.text() == "1 of 2 checked"
        assert window.excluded_count.text() == "1 of 2 excluded"
        assert not window.excluded_count.isHidden()
        assert window.report_status.full_text() == "Report ready: 1 file(s), 1 excluded"
        assert window.report_status.property("state") == "warning"
        assert "Excluded bad.d (Extraction failed): unreadable" in window.log_view.toPlainText()

    def test_long_file_name_does_not_push_rows_wider_than_the_list(
        self, window, tmp_path: Path, qt_application
    ) -> None:
        self._add_bruker_files(window, tmp_path, "long-name-" * 60 + ".d")
        window.show()
        qt_application.processEvents()

        row_width = window.selected_list.visualItemRect(window.selected_list.item(0)).width()

        assert row_width <= window.selected_list.viewport().width()

    def test_changing_the_selection_marks_the_report_stale_and_undoing_it_restores_ready(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "a.d", "b.d")
        self._patch_generate(monkeypatch, tmp_path)
        self._generate_and_wait(window, qt_application)

        window.selected_list.item(1).setCheckState(QtCore.Qt.CheckState.Unchecked)
        stale_text = window.report_status.full_text()
        stale_button = window.open_report_button.text()
        window.selected_list.item(1).setCheckState(QtCore.Qt.CheckState.Checked)

        assert stale_text == "Selection changed since the last report"
        assert stale_button == "Open last report"
        assert window.report_status.full_text() == "Report ready: 2 file(s)"
        assert window.open_report_button.text() == "Open report"

    def test_selection_change_during_a_run_makes_the_finished_report_stale(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "a.d", "b.d")
        release = threading.Event()

        def slow_generate(candidates, *_args, **_kwargs) -> ReportGenerationResult:
            release.wait(5)
            return ReportGenerationResult(tmp_path / "report.html", 1, 0, candidates)

        monkeypatch.setattr("rawtrace_qc.gui.app.generate_report", slow_generate)

        window._generate()
        window.selected_list.item(1).setCheckState(QtCore.Qt.CheckState.Unchecked)
        release.set()
        _wait_until(qt_application, lambda: window._worker is None)

        assert window.report_status.full_text() == "Selection changed since the last report"

    def test_failure_with_a_very_long_message_keeps_the_status_short_and_the_window_narrow(
        self, window, qt_application
    ) -> None:
        width_before = window.minimumSizeHint().width()
        message = "Could not run C:\\tools\\" + "very-long-folder\\" * 100

        window._report_failed(message)

        assert window.report_status.full_text() == "Report failed (see log)"
        assert window.report_status.property("state") == "error"
        assert message in window.log_view.toPlainText()
        assert window.minimumSizeHint().width() == width_before

    def test_failure_message_clears_when_all_failed_files_are_removed(self, window, tmp_path: Path) -> None:
        candidates = self._add_bruker_files(window, tmp_path, "a.d")
        window._selection.exclude(candidates[0].path, FileExclusion(ExclusionReason.EXTRACTION_FAILED, "unreadable"))
        window._report_failed("nothing usable")
        failed_text = window.report_status.full_text()

        window._selection.remove_selected((candidates[0].path,))
        window._refresh_selected()

        assert failed_text == "Report failed (see log)"
        assert window.report_status.full_text() == "No files checked"

    def test_status_says_files_are_unusable_when_every_file_is_excluded(self, window, tmp_path: Path) -> None:
        candidates = self._add_bruker_files(window, tmp_path, "a.d", "b.d")
        for candidate in candidates:
            window._selection.exclude(candidate.path, FileExclusion(ExclusionReason.EXTRACTION_FAILED, "unreadable"))

        window._refresh_selected()
        window._generate()

        assert window.report_status.full_text() == "No usable files: 2 excluded"
        assert "Report not started: No usable files: 2 excluded" in window.log_view.toPlainText()

    def test_status_says_no_files_checked_when_usable_files_are_unticked(self, window, tmp_path: Path) -> None:
        candidates = self._add_bruker_files(window, tmp_path, "a.d", "b.d")
        window._selection.exclude(candidates[0].path, FileExclusion(ExclusionReason.EXTRACTION_FAILED, "unreadable"))
        window._selection.set_selected_active(candidates[1].path, False)

        window._refresh_selected()

        assert window.report_status.full_text() == "No files checked"

    def test_thermo_files_added_while_the_tool_is_not_ready_are_logged_with_the_next_step(
        self, window, tmp_path: Path
    ) -> None:
        raw = tmp_path / "late.raw"
        raw.write_bytes(b"x" * (2 * 1024 * 1024))
        os.utime(raw, (0, 0))
        window._set_thermo_status(ThermoHelperStatus(ThermoHelperState.NOT_INSTALLED, None, None, False, "missing"))

        window._add_paths((raw,))

        log = window.log_view.toPlainText()
        assert "Thermo tool not ready: 1 added file(s) excluded" in log
        assert "Thermo Tool button" in log
        assert "Thermo Tool button" in window.selected_list.item(0).toolTip()

    def test_default_window_height_fits_the_screen(self, window) -> None:
        assert window.height() <= window.screen().availableGeometry().height()

    def test_failure_message_clears_when_the_selection_changes(self, window, tmp_path: Path) -> None:
        window._report_failed("broken")

        self._add_bruker_files(window, tmp_path, "a.d")

        assert window.report_status.full_text() == "1 file(s) ready for a report"

    def test_status_label_shortens_long_text_and_keeps_it_in_the_tooltip(self, window) -> None:
        window.report_status.resize(120, 30)
        text = "Extracting 3 of 12: " + "long-name-" * 30

        window.report_status.set_full_text(text)

        assert len(window.report_status.text()) < len(text)
        assert window.report_status.toolTip() == text

    def test_cancel_stops_the_run_without_excluding_files_or_opening_a_report(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "a.d")
        started = threading.Event()

        def cancellable_generate(*_args, cancel, **_kwargs) -> ReportGenerationResult:
            started.set()
            cancel.wait(5)
            raise OperationCancelledError("stopped")

        monkeypatch.setattr("rawtrace_qc.gui.app.generate_report", cancellable_generate)

        window._generate()
        visible_during_run = not window.cancel_button.isHidden()
        assert started.wait(5)
        window.cancel_button.click()
        cancelling_text = window.report_status.full_text()
        _wait_until(qt_application, lambda: window._worker is None)

        assert visible_during_run
        assert cancelling_text == "Cancelling..."
        assert window.report_status.full_text() == "Report cancelled"
        assert window.cancel_button.isHidden()
        assert window.generate_button.isEnabled()
        assert window._selection.excluded_selected() == ()
        assert browser == []

    def test_generate_without_checked_files_logs_the_reason_and_starts_nothing(self, window) -> None:
        window._generate()

        assert window._worker is None
        assert "Report not started: No files checked" in window.log_view.toPlainText()
        assert window.report_status.full_text() == "No files checked"

    def test_progress_updates_the_status_and_logs_each_extraction_but_only_the_start_of_other_stages(
        self, window, tmp_path: Path, qt_application, browser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._add_bruker_files(window, tmp_path, "a.d")
        window._worker = SimpleNamespace(cancel=threading.Event())

        window._report_progress(ReportProgress(ReportStage.EXTRACTING, 1, 2, "a.d"))
        window._report_progress(ReportProgress(ReportStage.EXTRACTING, 2, 2, "b.d"))
        window._report_progress(ReportProgress(ReportStage.PROCESSING, 1, 2, "a.d"))
        window._report_progress(ReportProgress(ReportStage.PROCESSING, 2, 2, "b.d"))
        status = window.report_status.full_text()
        window._worker = None
        log = window.log_view.toPlainText()

        assert status == "Processing traces 2 of 2"
        assert "Extracting 1 of 2: a.d" in log
        assert "Extracting 2 of 2: b.d" in log
        assert "Processing traces 1 of 2" in log
        assert "Processing traces 2 of 2" not in log

    def test_thermo_status_excludes_and_restores_files_in_the_list_and_log(self, window, tmp_path: Path) -> None:
        window._selection._add_candidates((DiscoveryCandidate(tmp_path / "t.raw", Vendor.THERMO, FileFormat.RAW),))

        window._set_thermo_status(ThermoHelperStatus(ThermoHelperState.NOT_INSTALLED, None, None, False, "missing"))
        excluded_text = window.excluded_count.text()
        reason = window.selected_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole.value + 1)
        window._set_thermo_status(ThermoHelperStatus(ThermoHelperState.READY, Path("helper.exe"), "1", True, "ready"))

        assert excluded_text == "1 of 1 excluded"
        assert reason == "Thermo tool not ready"
        assert window.excluded_count.isHidden()
        assert window.selected_list.item(0).flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable
        log = window.log_view.toPlainText()
        assert "Thermo tool not ready: 1 file(s) excluded" in log
        assert "Thermo tool ready: 1 file(s) restored" in log

    def test_scan_runs_in_the_background_and_logs_skipped_files_and_the_summary(
        self, window, tmp_path: Path, qt_application
    ) -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "small.raw").write_bytes(b"raw")
        window.source_edit.setText(str(source))

        window._scan_source()
        disabled_during_scan = not window.scan_button.isEnabled()
        _wait_until(qt_application, lambda: window._scan_task is None)

        log = window.log_view.toPlainText()
        assert disabled_during_scan
        assert window.scan_button.isEnabled()
        assert "Skipped small.raw:" in log
        assert "Scan finished: 0 valid file(s), 1 skipped, 0 issue(s)" in log

    def test_failed_scan_is_logged_and_the_buttons_return(self, window, tmp_path: Path, qt_application) -> None:
        window.source_edit.setText(str(tmp_path / "missing"))

        window._scan_source()
        _wait_until(qt_application, lambda: window._scan_task is None)

        assert "Scan failed:" in window.log_view.toPlainText()
        assert window.scan_button.isEnabled()
        assert window.choose_source_button.isEnabled()

    def test_adding_paths_logs_why_each_path_was_rejected(self, window, tmp_path: Path) -> None:
        small = tmp_path / "small.raw"
        small.write_bytes(b"raw")
        other = tmp_path / "notes.txt"
        other.write_text("notes")

        window._add_paths((small, other))

        log = window.log_view.toPlainText()
        assert "Rejected small.raw:" in log
        assert f"Rejected {other.resolve()}: not a supported" in log

    def test_log_window_shows_the_history_and_receives_new_lines(self, window) -> None:
        window._log("first line")

        window._open_log()
        window._log("second line")
        text = window._log_view_large.toPlainText()
        window._log_dialog.close()

        assert "first line" in text
        assert "second line" in text


class TestSystemThemeListener:
    def test_system_color_scheme_change_applies_resolved_theme(
        self, tmp_path: Path, qt_application, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        qt_core, qt_gui, qt_widgets = _load_qt()
        window = create_window(qt_core, qt_gui, qt_widgets, tmp_path / "settings.json")
        monkeypatch.setattr("rawtrace_qc.gui.app.resolve_theme", lambda _mode, _qt_gui: DARK_THEME)

        window._on_system_color_scheme_changed()

        assert get_active_theme() is DARK_THEME
        window.close()

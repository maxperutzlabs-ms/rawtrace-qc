"""Thermo Tool window for installing the helper and accepting its license."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from rawtrace_qc.thermo import (
    THERMO_HELPER_RELEASE,
    ThermoHelperState,
    ThermoHelperStatus,
    accept_thermo_license,
    find_host_runtime,
    get_thermo_helper_status,
    get_thermo_license_text,
    install_thermo_helper,
    is_thermo_helper_supported,
    managed_thermo_helper_directory,
    resolve_thermo_helper_specification,
)

_CHECKING_TEXT = "Checking..."
_ROW_HEIGHT = 46


@dataclass(frozen=True, slots=True)
class ThermoToolView:
    """Describe what the Thermo Tool window shows for one helper status."""

    installation: str
    license: str
    installation_ok: bool = False
    license_ok: bool = False
    can_install: bool = False
    can_review_license: bool = False
    can_accept_license: bool = False
    can_open_folder: bool = False
    detail: str = ""


def describe_thermo_status(status: ThermoHelperStatus) -> ThermoToolView:
    """Translate a helper status into the text and actions of the Thermo Tool window.

    Args:
        status: Helper status from `get_thermo_helper_status`.

    Returns:
        The labels and available actions for `status`.
    """
    if status.state is ThermoHelperState.READY:
        return ThermoToolView(
            installation="Installed",
            license="Accepted",
            installation_ok=True,
            license_ok=True,
            can_review_license=True,
        )
    if status.state is ThermoHelperState.UNLICENSED:
        return ThermoToolView(
            installation="Installed",
            license="Not accepted",
            installation_ok=True,
            can_review_license=True,
            can_accept_license=True,
        )
    if status.state is ThermoHelperState.NOT_INSTALLED:
        return ThermoToolView(
            installation="Not installed",
            license="Install the tool first",
            can_install=True,
        )
    if status.state is ThermoHelperState.INVALID_VERSION:
        return ThermoToolView(
            installation="Not usable",
            license="Unknown",
            can_install=True,
            can_open_folder=True,
            detail=(
                f"{status.message} Download or Install from ZIP replaces the "
                "contents of the install folder."
            ),
        )
    return ThermoToolView(
        installation="Not available on this system",
        license="Not available on this system",
        detail=status.message,
    )


def thermo_tool_needs_attention(status: ThermoHelperStatus) -> bool:
    """Return whether the user can act to make an unready helper usable.

    Args:
        status: Helper status from `get_thermo_helper_status`.

    Returns:
        True if the helper is not ready on a system that supports it.
    """
    return not status.is_ready and (
        status.state is not ThermoHelperState.UNSUPPORTED_PLATFORM
    )


def thermo_tool_tooltip(status: ThermoHelperStatus) -> str:
    """Return the header button tooltip for a helper status.

    Args:
        status: Helper status from `get_thermo_helper_status`.

    Returns:
        A short description of the state of the Thermo tool.
    """
    summaries = {
        ThermoHelperState.READY: "ready",
        ThermoHelperState.UNLICENSED: "license not accepted",
        ThermoHelperState.NOT_INSTALLED: "not installed",
        ThermoHelperState.INVALID_VERSION: "not usable",
        ThermoHelperState.UNSUPPORTED_PLATFORM: "not available on this system",
    }
    return f"Thermo Tool: {summaries[status.state]}"


def thermo_tool_required_message(status: ThermoHelperStatus) -> str:
    """Explain why Thermo files are excluded from reports and how to fix it.

    Args:
        status: Helper status from `get_thermo_helper_status`.

    Returns:
        Text for the popup shown when `status` is not ready.
    """
    reasons = {
        ThermoHelperState.UNLICENSED: "Its license has not been accepted yet.",
        ThermoHelperState.NOT_INSTALLED: "It is not installed yet.",
        ThermoHelperState.INVALID_VERSION: "The installed copy cannot be used.",
        ThermoHelperState.UNSUPPORTED_PLATFORM: ("It is not available on this system."),
    }
    return (
        "Reports with Thermo .raw files need the ThermoScanHeaderExtractor tool. "
        f"{reasons[status.state]}\n\n"
        "The Thermo files are excluded until it is set up. Open the Thermo Tool "
        "window to see how. The files then return automatically."
    )


def thermo_asset_label() -> str:
    """Return the release archive required on this system.

    Returns:
        The archive name, or a note naming the unsupported runtime.
    """
    if is_thermo_helper_supported():
        return resolve_thermo_helper_specification().asset_name
    return f"Not supported on {find_host_runtime() or 'this system'}"


def start_background_task(
    qt_core: Any,
    function: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_failure: Callable[[str], None],
) -> Any:
    """Run a function on the Qt thread pool and report back to the GUI thread.

    Pass bound methods of Qt objects as callbacks, so that Qt delivers them on
    the thread of that object. Keep the returned task until a callback has run.

    Args:
        qt_core: The loaded `PySide6.QtCore` module.
        function: Work to run without arguments.
        on_success: Receives the return value of `function`.
        on_failure: Receives the message of an exception raised by `function`.

    Returns:
        The started task.
    """
    task = _background_task_type(qt_core)(function)
    task.signals.succeeded.connect(on_success)
    task.signals.failed.connect(on_failure)
    qt_core.QThreadPool.globalInstance().start(task)
    return task


def create_thermo_tool_dialog(
    qt_core: Any,
    qt_gui: Any,
    qt_widgets: Any,
    parent: Any,
    on_status_changed: Callable[[ThermoHelperStatus], None],
) -> Any:
    """Build the Thermo Tool window and start checking the helper status.

    Args:
        qt_core: The loaded `PySide6.QtCore` module.
        qt_gui: The loaded `PySide6.QtGui` module.
        qt_widgets: The loaded `PySide6.QtWidgets` module.
        parent: Parent window of the dialog.
        on_status_changed: Receives every newly checked helper status.

    Returns:
        The dialog, ready to be shown with `exec()`.
    """

    class WaitDialog(qt_widgets.QDialog):
        """Show a busy message that the user cannot dismiss."""

        def __init__(self, dialog_parent: Any, message: str) -> None:
            super().__init__(dialog_parent)
            self.setObjectName("settingsDialog")
            self.setWindowTitle("Please wait")
            self.setModal(True)
            self.setWindowFlag(qt_core.Qt.WindowType.WindowCloseButtonHint, False)
            self.setMinimumWidth(420)
            layout = qt_widgets.QVBoxLayout(self)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(14)
            label = qt_widgets.QLabel(message)
            label.setObjectName("thermoToolWaitMessage")
            label.setWordWrap(True)
            layout.addWidget(label)
            progress = qt_widgets.QProgressBar()
            progress.setRange(0, 0)
            progress.setTextVisible(False)
            layout.addWidget(progress)

        def reject(self) -> None:
            return

        def closeEvent(self, event: Any) -> None:
            event.ignore()

    class ThermoToolDialog(qt_widgets.QDialog):
        """Show the helper state and offer the steps needed to make it ready."""

        def __init__(self) -> None:
            super().__init__(parent)
            self.setObjectName("settingsDialog")
            self.setWindowTitle("Thermo Tool")
            self.resize(820, 420)
            self._status_task: Any = None
            self._action_task: Any = None
            self._wait_dialog: Any = None
            self._on_action_success: Callable[[Any], None] | None = None
            self._install_directory: Path | None = None
            self._build_ui()
            self.refresh()

        def _build_ui(self) -> None:
            layout = qt_widgets.QVBoxLayout(self)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(14)
            card = qt_widgets.QFrame()
            card.setObjectName("card")
            card_layout = qt_widgets.QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            card_layout.setSpacing(14)
            title = qt_widgets.QLabel("ThermoScanHeaderExtractor")
            title.setObjectName("settingsCardTitle")
            card_layout.addWidget(title)
            purpose = qt_widgets.QLabel(
                "This separate tool reads Thermo .raw files. It is required to "
                "generate reports with them."
            )
            purpose.setObjectName("settingsFieldNote")
            purpose.setWordWrap(True)
            card_layout.addWidget(purpose)
            form = qt_widgets.QFormLayout()
            form.setHorizontalSpacing(16)
            form.setVerticalSpacing(14)
            card_layout.addLayout(form)
            layout.addWidget(card)

            version_pill = qt_widgets.QLabel(f"v{THERMO_HELPER_RELEASE.version}")
            version_pill.setObjectName("pinnedVersion")
            self.asset_label = qt_widgets.QLabel(thermo_asset_label())
            self.asset_label.setObjectName("settingsAssetName")
            self.asset_label.setTextInteractionFlags(
                qt_core.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self.release_link = qt_widgets.QLabel(
                f'<a href="{THERMO_HELPER_RELEASE.release_page_url}">Release page</a>'
            )
            self.release_link.setObjectName("thermoToolReleaseLink")
            self.release_link.setOpenExternalLinks(True)
            self.release_link.setToolTip(THERMO_HELPER_RELEASE.release_page_url)
            self._add_row(
                form,
                "Required version",
                version_pill,
                self.asset_label,
                None,
                self.release_link,
            )

            self.installation_status = self._status_label()
            self.download_button = self._action_button(
                "Download", self._download_helper
            )
            self.install_zip_button = self._action_button(
                "Install from ZIP...", self._install_from_zip
            )
            self.open_folder_button = self._action_button(
                "Open install folder", self._open_install_folder
            )
            self._add_row(
                form,
                "Installation",
                self.installation_status,
                None,
                self.download_button,
                self.install_zip_button,
                self.open_folder_button,
            )
            self.location_note = qt_widgets.QLabel()
            self.location_note.setObjectName("settingsFieldNote")
            self.location_note.setWordWrap(True)
            self.location_note.setTextInteractionFlags(
                qt_core.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            form.addRow(self._form_label(""), self.location_note)

            self.license_status = self._status_label()
            self.show_license_button = self._action_button(
                "Show license", self._show_license
            )
            self.accept_license_button = self._action_button(
                "Accept license", self._accept_license
            )
            self._add_row(
                form,
                "License",
                self.license_status,
                None,
                self.show_license_button,
                self.accept_license_button,
            )
            license_note = qt_widgets.QLabel(
                "Accepting applies to your user account. Use Show license to read "
                "the terms first."
            )
            license_note.setObjectName("settingsFieldNote")
            license_note.setWordWrap(True)
            form.addRow(self._form_label(""), license_note)

            self.detail_label = qt_widgets.QLabel()
            self.detail_label.setObjectName("settingsFieldNote")
            self.detail_label.setWordWrap(True)
            self.detail_label.setTextInteractionFlags(
                qt_core.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            card_layout.addWidget(self.detail_label)

            layout.addStretch()
            button_row = qt_widgets.QHBoxLayout()
            button_row.addStretch()
            close_button = qt_widgets.QPushButton("Close")
            close_button.setObjectName("dialogPrimary")
            close_button.setFixedHeight(40)
            close_button.clicked.connect(self.accept)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

        def _form_label(self, text: str) -> Any:
            label = qt_widgets.QLabel(text)
            label.setObjectName("settingsFormLabel")
            label.setFixedWidth(150)
            return label

        def _status_label(self) -> Any:
            label = qt_widgets.QLabel()
            label.setObjectName("thermoToolStatus")
            return label

        def _action_button(self, text: str, handler: Callable[[], None]) -> Any:
            button = qt_widgets.QPushButton(text)
            button.setObjectName("secondary")
            button.setAutoDefault(False)
            button.clicked.connect(handler)
            return button

        def _add_row(self, form: Any, text: str, *widgets: Any) -> None:
            row = qt_widgets.QWidget()
            row.setFixedHeight(_ROW_HEIGHT)
            row_layout = qt_widgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            for widget in widgets:
                if widget is None:
                    row_layout.addStretch(1)
                else:
                    row_layout.addWidget(
                        widget, 0, qt_core.Qt.AlignmentFlag.AlignVCenter
                    )
            label = self._form_label(text)
            label.setFixedHeight(_ROW_HEIGHT)
            form.addRow(label, row)

        def refresh(self) -> None:
            """Check the helper status again and update the window."""
            self._show_checking()
            self._status_task = start_background_task(
                qt_core,
                get_thermo_helper_status,
                self._status_checked,
                self._status_check_failed,
            )

        def _show_checking(self) -> None:
            self._set_status(self.installation_status, _CHECKING_TEXT, "pending")
            self._set_status(self.license_status, _CHECKING_TEXT, "pending")
            self.download_button.setVisible(False)
            self.install_zip_button.setVisible(False)
            self.open_folder_button.setVisible(False)
            self.show_license_button.setEnabled(False)
            self.accept_license_button.setEnabled(False)
            self.detail_label.setVisible(False)

        def _status_checked(self, status: ThermoHelperStatus) -> None:
            self._status_task = None
            view = describe_thermo_status(status)
            self._set_status(
                self.installation_status,
                view.installation,
                "ok" if view.installation_ok else "problem",
            )
            self._set_status(
                self.license_status,
                view.license,
                "ok" if view.license_ok else "problem",
            )
            self.download_button.setVisible(view.can_install)
            self.install_zip_button.setVisible(view.can_install)
            self.open_folder_button.setVisible(view.can_open_folder)
            self.show_license_button.setEnabled(view.can_review_license)
            self.accept_license_button.setEnabled(view.can_accept_license)
            self.detail_label.setText(view.detail)
            self.detail_label.setVisible(bool(view.detail))
            self._install_directory = (
                managed_thermo_helper_directory()
                if is_thermo_helper_supported()
                else None
            )
            self.location_note.setText(
                f"Install location: {self._install_directory}"
                if self._install_directory is not None
                else ""
            )
            on_status_changed(status)

        def _status_check_failed(self, message: str) -> None:
            self._status_task = None
            self._set_status(self.installation_status, "Unknown", "problem")
            self._set_status(self.license_status, "Unknown", "problem")
            self.detail_label.setText(message)
            self.detail_label.setVisible(True)

        def _set_status(self, label: Any, text: str, state: str) -> None:
            label.setText(text)
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)

        def _download_helper(self) -> None:
            self._run_action(
                f"Downloading ThermoScanHeaderExtractor "
                f"v{THERMO_HELPER_RELEASE.version}, please wait...",
                lambda: install_thermo_helper(overwrite=True),
                self._action_changed_status,
            )

        def _install_from_zip(self) -> None:
            path, _ = qt_widgets.QFileDialog.getOpenFileName(
                self,
                f"Choose {thermo_asset_label()}",
                str(Path.home() / "Downloads"),
                "ZIP archives (*.zip)",
            )
            if not path:
                return
            self._run_action(
                "Installing ThermoScanHeaderExtractor, please wait...",
                lambda: install_thermo_helper(path, overwrite=True),
                self._action_changed_status,
            )

        def _open_install_folder(self) -> None:
            if self._install_directory is not None:
                qt_gui.QDesktopServices.openUrl(
                    qt_core.QUrl.fromLocalFile(str(self._install_directory))
                )

        def _show_license(self) -> None:
            self._run_action(
                "Loading the license, please wait...",
                get_thermo_license_text,
                lambda text: self._show_license_text("Thermo license", "", text),
            )

        def _accept_license(self) -> None:
            def fetch_terms_then_accept() -> str:
                terms = get_thermo_license_text()
                accept_thermo_license()
                return terms

            self._run_action(
                "Accepting the license, please wait...",
                fetch_terms_then_accept,
                self._license_accepted,
            )

        def _license_accepted(self, terms: str) -> None:
            self.refresh()
            self._show_license_text(
                "Thermo license accepted",
                "You accepted these terms for your user account.",
                terms,
            )

        def _show_license_text(self, title: str, note: str, terms: str) -> None:
            popup = qt_widgets.QDialog(self)
            popup.setObjectName("settingsDialog")
            popup.setWindowTitle(title)
            popup.resize(720, 560)
            layout = qt_widgets.QVBoxLayout(popup)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(14)
            if note:
                note_label = qt_widgets.QLabel(note)
                note_label.setObjectName("thermoToolStatus")
                note_label.setProperty("state", "ok")
                layout.addWidget(note_label)
            text = qt_widgets.QPlainTextEdit()
            text.setObjectName("thermoLicenseText")
            text.setReadOnly(True)
            text.setPlainText(terms)
            layout.addWidget(text, 1)
            button_row = qt_widgets.QHBoxLayout()
            button_row.addStretch()
            close_button = qt_widgets.QPushButton("Close")
            close_button.setObjectName("dialogPrimary")
            close_button.setFixedHeight(40)
            close_button.clicked.connect(popup.accept)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)
            popup.exec()

        def _action_changed_status(self, _result: Any) -> None:
            self.refresh()

        def _run_action(
            self,
            message: str,
            function: Callable[[], Any],
            on_success: Callable[[Any], None],
        ) -> None:
            self._wait_dialog = WaitDialog(self, message)
            self._wait_dialog.show()
            self._on_action_success = on_success
            self._action_task = start_background_task(
                qt_core, function, self._action_succeeded, self._action_failed
            )

        def _action_succeeded(self, result: Any) -> None:
            self._finish_action()
            on_success = self._on_action_success
            self._on_action_success = None
            if on_success is not None:
                on_success(result)

        def _action_failed(self, message: str) -> None:
            self._finish_action()
            self._on_action_success = None
            self.refresh()
            qt_widgets.QMessageBox.critical(self, "Thermo Tool", message)

        def _finish_action(self) -> None:
            self._action_task = None
            if self._wait_dialog is not None:
                self._wait_dialog.hide()
                self._wait_dialog.deleteLater()
                self._wait_dialog = None

    return ThermoToolDialog()


@cache
def _background_task_type(qt_core: Any) -> Any:
    class TaskSignals(qt_core.QObject):
        succeeded = qt_core.Signal(object)
        failed = qt_core.Signal(str)

    class BackgroundTask(qt_core.QRunnable):
        def __init__(self, function: Callable[[], Any]) -> None:
            super().__init__()
            self.function = function
            self.signals = TaskSignals()

        def run(self) -> None:
            try:
                result = self.function()
            except Exception as error:
                self.signals.failed.emit(str(error))
            else:
                self.signals.succeeded.emit(result)

    return BackgroundTask

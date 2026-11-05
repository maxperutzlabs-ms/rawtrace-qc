"""PySide6 desktop interface for discovery and one-button report generation."""

from __future__ import annotations

import sys
import textwrap
import threading
import webbrowser
from dataclasses import replace
from datetime import datetime
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rawtrace_qc.discovery import DiscoveryResult, DiscoveryScope, Vendor, discover
from rawtrace_qc.environment import default_data_directory
from rawtrace_qc.errors import ConfigurationError, OperationCancelledError
from rawtrace_qc.gui.cache import TraceCache
from rawtrace_qc.gui.config import (
    GuiSettings,
    load_settings,
    save_settings,
)
from rawtrace_qc.gui.patterns import FilenamePattern, PatternMode
from rawtrace_qc.gui.reporting import (
    ExcludedFile,
    ReportGenerationOptions,
    ReportGenerationResult,
    ReportProgress,
    ReportStage,
    ReportStorageMode,
    ReportWorkspace,
    generate_report,
)
from rawtrace_qc.gui.theme import (
    apply_theme,
    get_active_theme,
    resolve_theme,
)
from rawtrace_qc.gui.thermo_tool import (
    create_thermo_tool_dialog,
    start_background_task,
    thermo_tool_needs_attention,
    thermo_tool_required_message,
    thermo_tool_tooltip,
)
from rawtrace_qc.gui.workflow import (
    RawFileSelection,
    SelectedEntry,
)
from rawtrace_qc.thermo import (
    ThermoHelperState,
    ThermoHelperStatus,
    get_thermo_helper_status,
)

_EXCLUSION_COLUMN_WIDTH = 170
_LOG_MAX_LINES = 5000


def main() -> int:
    """Create the Qt application, show its main window, and run its event loop."""
    qt_core, qt_gui, qt_widgets = _load_qt()
    try:
        settings = load_settings()
    except ConfigurationError:
        settings = GuiSettings()
    application = qt_widgets.QApplication.instance()
    if application is None:
        application = qt_widgets.QApplication(sys.argv)
    application.setStyle("Fusion")
    apply_theme(application, resolve_theme(settings.theme_mode, qt_gui), qt_gui)
    application.setApplicationName("rawtrace-qc")
    application.setOrganizationName("rawtrace-qc")
    window = create_window(qt_core, qt_gui, qt_widgets)
    window.show()
    window.refresh_thermo_status()
    return application.exec()


def create_window(
    qt_core: Any,
    qt_gui: Any,
    qt_widgets: Any,
    settings_path: Path | None = None,
) -> Any:
    """Build and return the main window using already-loaded Qt modules."""
    application = qt_widgets.QApplication.instance()
    try:
        settings = load_settings(settings_path)
        configuration_message = ""
    except ConfigurationError as error:
        settings = GuiSettings()
        configuration_message = f"Configuration reset to defaults: {error}"
    theme = resolve_theme(settings.theme_mode, qt_gui)
    if application is not None:
        apply_theme(application, theme, qt_gui)

    exclusion_role = qt_core.Qt.ItemDataRole.UserRole.value + 1
    svg_pixmap_cache: dict[tuple[str, str, int], Any] = {}

    def themed_svg_pixmap(resource_name: str, color: str, size: int) -> Any:
        """Render a bundled SVG resource in a theme color and requested size."""
        key = (resource_name, color, size)
        if key not in svg_pixmap_cache:
            svg_path = Path(__file__).parent / "resources" / resource_name
            svg_bytes = svg_path.read_bytes().replace(b"currentColor", color.encode())
            pixmap = qt_gui.QPixmap()
            pixmap.loadFromData(qt_core.QByteArray(svg_bytes), "SVG")
            svg_pixmap_cache[key] = pixmap.scaled(
                size,
                size,
                qt_core.Qt.AspectRatioMode.KeepAspectRatio,
                qt_core.Qt.TransformationMode.SmoothTransformation,
            )
        return svg_pixmap_cache[key]

    class DropList(qt_widgets.QListWidget):
        """Accept local files and folders dropped from the operating system."""

        paths_dropped = qt_core.Signal(object)

        def __init__(self) -> None:
            super().__init__()
            self.setAcceptDrops(True)
            self.setDragDropMode(qt_widgets.QAbstractItemView.DragDropMode.DropOnly)

        def dragEnterEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            super().dragEnterEvent(event)

        def dragMoveEvent(self, event: Any) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
            super().dragMoveEvent(event)

        def dropEvent(self, event: Any) -> None:
            paths = tuple(
                Path(url.toLocalFile())
                for url in event.mimeData().urls()
                if url.isLocalFile()
            )
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
            super().dropEvent(event)

        def paintEvent(self, event: Any) -> None:
            super().paintEvent(event)
            theme = get_active_theme()
            painter = qt_gui.QPainter(self.viewport())
            painter.save()
            painter.setRenderHint(qt_gui.QPainter.RenderHint.Antialiasing)

            def draw_panel(rect: Any, *, empty: bool) -> None:
                pen = qt_gui.QPen(
                    qt_gui.QColor(theme.drop_hint_border),
                    1.5,
                    qt_core.Qt.PenStyle.DashLine,
                )
                painter.setPen(pen)
                painter.setBrush(qt_core.Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect, 8, 8)
                center_x = rect.center().x()
                center_y = rect.center().y()
                if empty:
                    icon = themed_svg_pixmap(
                        "upload-icon.svg",
                        theme.drop_hint_icon,
                        36,
                    )
                    painter.drawPixmap(
                        qt_core.QRect(center_x - 18, center_y - 52, 36, 36),
                        icon,
                    )
                    font = painter.font()
                    font.setPixelSize(16)
                    font.setWeight(qt_gui.QFont.Weight.DemiBold)
                    painter.setFont(font)
                    painter.setPen(qt_gui.QColor(theme.text_primary))
                    painter.drawText(
                        qt_core.QRect(
                            rect.left() + 8, center_y - 12, rect.width() - 16, 22
                        ),
                        qt_core.Qt.AlignmentFlag.AlignCenter,
                        "Drop .raw files or .d folders here",
                    )
                    font.setPixelSize(14)
                    font.setWeight(qt_gui.QFont.Weight.Normal)
                    painter.setFont(font)
                    painter.setPen(qt_gui.QColor(theme.drop_hint_text))
                    painter.drawText(
                        qt_core.QRect(
                            rect.left() + 8, center_y + 12, rect.width() - 16, 22
                        ),
                        qt_core.Qt.AlignmentFlag.AlignCenter,
                        "or use Choose folder above to scan a directory",
                    )
                    return

                font = painter.font()
                font.setPixelSize(14)
                font.setWeight(qt_gui.QFont.Weight.Normal)
                painter.setFont(font)
                text = "Drop .raw files or folders here to add more"
                metrics = qt_gui.QFontMetrics(font)
                icon_size = 18
                gap = 8
                total_width = icon_size + gap + metrics.horizontalAdvance(text)
                content_left = center_x - total_width // 2
                icon = themed_svg_pixmap(
                    "upload-icon.svg", theme.drop_hint_text, icon_size
                )
                painter.drawPixmap(
                    qt_core.QRect(
                        content_left, center_y - icon_size // 2, icon_size, icon_size
                    ),
                    icon,
                )
                painter.setPen(qt_gui.QColor(theme.drop_hint_text))
                painter.drawText(
                    qt_core.QRect(
                        content_left + icon_size + gap,
                        rect.top(),
                        metrics.horizontalAdvance(text),
                        rect.height(),
                    ),
                    qt_core.Qt.AlignmentFlag.AlignVCenter,
                    text,
                )

            if self.count() == 0:
                draw_panel(
                    self.viewport().rect().adjusted(12, 12, -12, -12), empty=True
                )
            else:
                last_rect = self.visualItemRect(self.item(self.count() - 1))
                top = last_rect.bottom() + 12
                height = self.viewport().height() - top - 12
                if height >= 48:
                    draw_panel(
                        qt_core.QRect(12, top, self.viewport().width() - 24, height),
                        empty=False,
                    )
            painter.restore()

    class FileItemDelegate(qt_widgets.QStyledItemDelegate):
        """Paint and toggle explicit checkboxes for file list items."""

        @staticmethod
        def _checkbox_rect(option: Any) -> Any:
            """Geometry of the drawn checkbox glyph itself."""
            return qt_core.QRect(
                option.rect.left() + 4,
                option.rect.center().y() - 7,
                14,
                14,
            )

        @staticmethod
        def _checkbox_field_rect(option: Any) -> Any:
            """Clickable area: the whole reserved left column, not just the glyph."""
            return qt_core.QRect(
                option.rect.left(),
                option.rect.top(),
                24,
                option.rect.height(),
            )

        def sizeHint(self, option: Any, index: Any) -> Any:
            hint = super().sizeHint(option, index)
            return qt_core.QSize(hint.width(), 40)

        def initStyleOption(self, option: Any, index: Any) -> None:
            super().initStyleOption(option, index)
            if index.flags() & qt_core.Qt.ItemFlag.ItemIsUserCheckable:
                option.features &= (
                    ~qt_widgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
                )

        def paint(
            self,
            painter: Any,
            option: Any,
            index: Any,
        ) -> None:
            exclusion = index.data(exclusion_role)
            if not exclusion and not (
                index.flags() & qt_core.Qt.ItemFlag.ItemIsUserCheckable
            ):
                super().paint(painter, option, index)
                return
            theme = get_active_theme()
            selected = bool(option.state & qt_widgets.QStyle.StateFlag.State_Selected)
            if selected:
                painter.fillRect(
                    option.rect,
                    qt_gui.QColor(theme.list_selected_background),
                )
            display_option = qt_widgets.QStyleOptionViewItem(option)
            display_option.rect.adjust(
                24, 0, -_EXCLUSION_COLUMN_WIDTH if exclusion else 0, 0
            )
            display_option.palette.setColor(
                qt_gui.QPalette.ColorRole.Highlight,
                qt_gui.QColor(theme.list_selected_background),
            )
            display_option.palette.setColor(
                qt_gui.QPalette.ColorRole.HighlightedText,
                qt_gui.QColor(theme.list_selected_text),
            )
            super().paint(painter, display_option, index)
            rect = self._checkbox_rect(option)
            painter.save()
            painter.setRenderHint(qt_gui.QPainter.RenderHint.Antialiasing)
            painter.setPen(qt_gui.QPen(qt_gui.QColor(theme.checkbox_border), 1.2))
            painter.setBrush(qt_gui.QBrush(qt_gui.QColor(theme.checkbox_background)))
            painter.drawRoundedRect(rect, 3, 3)
            if exclusion:
                exclusion_color = qt_gui.QColor(theme.destructive_button_text)
                painter.setPen(qt_gui.QPen(exclusion_color, 2))
                painter.drawLine(
                    rect.topLeft() + qt_core.QPoint(3, 3),
                    rect.bottomRight() - qt_core.QPoint(3, 3),
                )
                painter.drawLine(
                    rect.topRight() + qt_core.QPoint(-3, 3),
                    rect.bottomLeft() + qt_core.QPoint(3, -3),
                )
                painter.setPen(exclusion_color)
                painter.drawText(
                    option.rect.adjusted(
                        option.rect.width() - _EXCLUSION_COLUMN_WIDTH, 0, -10, 0
                    ),
                    qt_core.Qt.AlignmentFlag.AlignRight
                    | qt_core.Qt.AlignmentFlag.AlignVCenter,
                    str(exclusion),
                )
            elif index.data(qt_core.Qt.ItemDataRole.CheckStateRole) == (
                qt_core.Qt.CheckState.Checked.value
            ):
                painter.setPen(qt_gui.QPen(qt_gui.QColor(theme.checkbox_check), 2))
                painter.drawLine(
                    qt_core.QPoint(rect.left() + 4, rect.center().y()),
                    qt_core.QPoint(rect.center().x() - 1, rect.bottom() - 4),
                )
                painter.drawLine(
                    qt_core.QPoint(rect.center().x() - 1, rect.bottom() - 4),
                    qt_core.QPoint(rect.right() - 3, rect.top() + 4),
                )
            painter.setPen(qt_gui.QPen(qt_gui.QColor(theme.list_divider), 1))
            painter.drawLine(
                option.rect.left(),
                option.rect.bottom(),
                option.rect.right(),
                option.rect.bottom(),
            )
            painter.restore()

        def editorEvent(
            self,
            event: Any,
            model: Any,
            option: Any,
            index: Any,
        ) -> bool:
            if (
                event.type() == qt_core.QEvent.Type.MouseButtonRelease
                and event.button() == qt_core.Qt.MouseButton.LeftButton
                and index.flags() & qt_core.Qt.ItemFlag.ItemIsUserCheckable
                and self._checkbox_field_rect(option).contains(
                    event.position().toPoint()
                )
            ):
                checked = index.data(qt_core.Qt.ItemDataRole.CheckStateRole) == (
                    qt_core.Qt.CheckState.Checked.value
                )
                model.setData(
                    index,
                    (
                        qt_core.Qt.CheckState.Unchecked.value
                        if checked
                        else qt_core.Qt.CheckState.Checked.value
                    ),
                    qt_core.Qt.ItemDataRole.CheckStateRole,
                )
                return True
            return super().editorEvent(event, model, option, index)

    class SelectedFileDelegate(FileItemDelegate):
        """Keep rows as wide as the list, so the exclusion column stays visible.

        Long file names are shortened instead of widening the rows. The tooltip
        shows the full path.
        """

        def sizeHint(self, option: Any, index: Any) -> Any:
            return qt_core.QSize(0, super().sizeHint(option, index).height())

    class WorkerSignals(qt_core.QObject):
        """Carry background report results back to the GUI thread."""

        finished = qt_core.Signal(object)
        failed = qt_core.Signal(str)
        cancelled = qt_core.Signal()
        progress = qt_core.Signal(object)
        excluded = qt_core.Signal(object)

    class ReportWorker(qt_core.QRunnable):
        """Run report generation without blocking the Qt event loop."""

        def __init__(
            self, candidates: tuple[Any, ...], options: Any, trace_cache: TraceCache
        ) -> None:
            super().__init__()
            self.candidates = candidates
            self.options = options
            self.trace_cache = trace_cache
            self.cancel = threading.Event()
            self.signals = WorkerSignals()

        def run(self) -> None:
            try:
                result = generate_report(
                    self.candidates,
                    self.trace_cache,
                    options=self.options,
                    workspace=workspace,
                    on_progress=self.signals.progress.emit,
                    on_excluded=self.signals.excluded.emit,
                    cancel=self.cancel,
                )
            except OperationCancelledError:
                self.signals.cancelled.emit()
            except Exception as error:
                self.signals.failed.emit(str(error))
            else:
                self.signals.finished.emit(result)

    class ElidedLabel(qt_widgets.QLabel):
        """Show one line of any length without widening the window.

        The text is shortened to the available width, and the tooltip holds it in
        full.
        """

        def __init__(self) -> None:
            super().__init__()
            self._full_text = ""
            self.setSizePolicy(
                qt_widgets.QSizePolicy.Policy.Ignored,
                qt_widgets.QSizePolicy.Policy.Preferred,
            )

        def full_text(self) -> str:
            """Return the text before shortening."""
            return self._full_text

        def set_full_text(self, text: str) -> None:
            """Replace the text and shorten it to the current width."""
            self._full_text = text
            self.setToolTip(text)
            self._elide()

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            self._elide()

        def _elide(self) -> None:
            self.setText(
                self.fontMetrics().elidedText(
                    self._full_text,
                    qt_core.Qt.TextElideMode.ElideMiddle,
                    self.width(),
                )
            )

    class ElidedLineEdit(qt_widgets.QLineEdit):
        """Display long paths with a middle ellipsis when the field is inactive."""

        def paintEvent(self, event: Any) -> None:
            if self.hasFocus() and not self.isReadOnly():
                super().paintEvent(event)
                return
            if not self.text():
                super().paintEvent(event)
                return

            option = qt_widgets.QStyleOptionFrame()
            self.initStyleOption(option)
            painter = qt_gui.QPainter(self)
            self.style().drawPrimitive(
                qt_widgets.QStyle.PrimitiveElement.PE_PanelLineEdit,
                option,
                painter,
                self,
            )
            text_rect = self.style().subElementRect(
                qt_widgets.QStyle.SubElement.SE_LineEditContents,
                option,
                self,
            )
            margins = self.textMargins()
            text_rect.adjust(margins.left(), 0, -margins.right(), 0)
            text_color = self.palette().color(
                qt_gui.QPalette.ColorGroup.Active
                if self.isEnabled()
                else qt_gui.QPalette.ColorGroup.Disabled,
                qt_gui.QPalette.ColorRole.Text,
            )
            painter.setPen(text_color)
            metrics = qt_gui.QFontMetrics(self.font())
            display_text = metrics.elidedText(
                self.text(),
                qt_core.Qt.TextElideMode.ElideMiddle,
                text_rect.width(),
            )
            painter.drawText(
                text_rect,
                self.alignment() | qt_core.Qt.AlignmentFlag.AlignVCenter,
                display_text,
            )

    class ThemedComboBox(qt_widgets.QComboBox):
        """Display a rounded popup without clipping its options."""

        def __init__(self, parent: Any | None = None) -> None:
            super().__init__(parent)
            self.setView(qt_widgets.QListView(self))
            container = self.findChild(qt_widgets.QFrame)
            if container is not None:
                container.setFrameShape(qt_widgets.QFrame.Shape.NoFrame)
                container.setLineWidth(0)
            self.setMaxVisibleItems(6)

        def showPopup(self) -> None:
            """Position the popup within the active screen work area."""
            super().showPopup()
            container = self.findChild(qt_widgets.QFrame)
            if container is None:
                return
            container.setFrameShape(qt_widgets.QFrame.Shape.NoFrame)
            container.setLineWidth(0)
            view = self.view()
            visible_count = min(self.count(), 6)
            row_heights = [
                max(view.sizeHintForRow(index), 36) for index in range(visible_count)
            ]
            top_margin = max(0, view.y())
            bottom_margin = max(0, container.height() - view.y() - view.height())
            view_overhead = max(0, view.height() - view.viewport().height())
            total_h = top_margin + sum(row_heights) + view_overhead + bottom_margin

            global_combo = self.mapToGlobal(qt_core.QPoint(0, 0))
            screen = self.screen()
            if screen is None:
                screen = qt_widgets.QApplication.primaryScreen()
            if screen is None:
                return

            available = screen.availableGeometry()
            gap = 2
            below_y = global_combo.y() + self.height() + gap
            above_y = global_combo.y() - total_h - gap
            available_bottom = available.bottom() + 1
            space_below = max(0, available_bottom - below_y)
            space_above = max(0, global_combo.y() - gap - available.top())

            if space_below >= total_h:
                popup_y = below_y
                popup_height = total_h
            elif space_above >= total_h:
                popup_y = above_y
                popup_height = total_h
            elif space_below >= space_above:
                popup_y = below_y
                popup_height = min(total_h, space_below)
            else:
                popup_y = global_combo.y() - gap - min(total_h, space_above)
                popup_height = min(total_h, space_above)

            popup_height = min(popup_height, available.height())
            popup_y = max(
                available.top(),
                min(popup_y, available_bottom - popup_height),
            )
            popup_width = max(self.width(), container.width())
            popup_width = min(popup_width, available.width())
            popup_x = max(
                available.left(),
                min(global_combo.x(), available.right() + 1 - popup_width),
            )

            parent = container.parentWidget()
            if container.isWindow() or parent is None:
                popup_position = qt_core.QPoint(popup_x, popup_y)
            else:
                popup_position = parent.mapFromGlobal(qt_core.QPoint(popup_x, popup_y))
            container.setGeometry(
                popup_position.x(),
                popup_position.y(),
                popup_width,
                popup_height,
            )
            right_margin = max(0, container.width() - view.x() - view.width())
            view.setGeometry(
                view.x(),
                view.y(),
                max(0, popup_width - view.x() - right_margin),
                max(0, popup_height - top_margin - bottom_margin),
            )

    class MainWindow(qt_widgets.QMainWindow):
        """Present discovery, selected inputs, and report controls."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("rawtrace-qc | run review")
            self.resize(1180, min(900, self.screen().availableGeometry().height() - 40))
            self.setMinimumSize(900, 620)
            self._settings = settings
            self._saved_patterns = list(settings.patterns)
            self._custom_patterns: list[FilenamePattern] = []
            self._active_pattern_keys: set[tuple[str, str]] = set()
            self._selection = RawFileSelection(settings.discovery_options())
            self._workspace = workspace
            self._cache = cache
            self._worker: Any = None
            self._scan_task: Any = None
            self._thermo_status_task: Any = None
            self._pending_options: Any = None
            self._last_report: ReportGenerationResult | None = None
            self._run_message: tuple[tuple[SelectedEntry, ...], str, str] | None = None
            self._log_view_large: Any = None
            self._log_dialog: Any = None
            self._closing = False
            self._last_progress_stage: ReportStage | None = None
            self._rendering_candidates = False
            self._rendering_selected = False
            self._configuration_message = configuration_message
            self._candidate_list: Any = None
            self._build_ui()
            self._connect_system_color_scheme_listener()

        def _settings_icon(self, qt_core: Any, qt_gui: Any) -> Any:
            """Load the header settings icon with a light stroke."""
            svg_path = Path(__file__).parent / "resources" / "settings-icon.svg"
            svg_bytes = svg_path.read_bytes().replace(b"currentColor", b"#ffffff")
            pixmap = qt_gui.QPixmap()
            pixmap.loadFromData(qt_core.QByteArray(svg_bytes), "SVG")
            return qt_gui.QIcon(pixmap)

        def _action_icon(self, resource_name: str, color: str, size: int) -> Any:
            """Return a bundled action icon in the requested theme color."""
            return qt_gui.QIcon(themed_svg_pixmap(resource_name, color, size))

        def _connect_system_color_scheme_listener(self) -> None:
            gui_application_type = getattr(qt_gui, "QGuiApplication", None)
            if gui_application_type is None:
                return
            application = gui_application_type.instance()
            if application is None:
                return
            try:
                style_hints = application.styleHints()
                signal = getattr(style_hints, "colorSchemeChanged", None)
                if signal is not None and callable(getattr(signal, "connect", None)):
                    signal.connect(self._on_system_color_scheme_changed)
            except (AttributeError, RuntimeError, TypeError):
                return

        def _apply_current_theme(self) -> None:
            theme = resolve_theme(self._settings.theme_mode, qt_gui)
            application = qt_widgets.QApplication.instance()
            apply_theme(application if application is not None else self, theme, qt_gui)
            self._header_logo.load(theme.header_logo)
            self.remove_highlighted_button.setIcon(
                self._action_icon(
                    "trash-icon.svg",
                    theme.destructive_button_text,
                    14,
                )
            )
            self.selected_list.viewport().update()
            self.selected_list.update()
            if self._candidate_list is not None:
                self._candidate_list.viewport().update()

        def _on_system_color_scheme_changed(self, *_args: Any) -> None:
            if self._settings.theme_mode == "system":
                self._apply_current_theme()

        def _build_ui(self) -> None:
            central = qt_widgets.QWidget()
            self.setCentralWidget(central)
            root = qt_widgets.QVBoxLayout(central)
            root.setContentsMargins(20, 20, 20, 20)
            root.setSpacing(14)

            header = qt_widgets.QFrame()
            header.setObjectName("header")
            header_layout = qt_widgets.QHBoxLayout(header)
            header_layout.setContentsMargins(20, 10, 20, 10)
            header_layout.setSpacing(16)
            theme = resolve_theme(self._settings.theme_mode, qt_gui)
            svg_renderer = import_module("PySide6.QtSvg").QSvgRenderer(
                theme.header_logo
            )
            view_box = svg_renderer.viewBoxF()
            logo_width = (
                int(round(40 * view_box.width() / view_box.height()))
                if view_box.height() > 0
                else 111
            )
            self._header_logo = import_module("PySide6.QtSvgWidgets").QSvgWidget(header)
            self._header_logo.load(theme.header_logo)
            self._header_logo.setFixedSize(logo_width, 40)
            self._header_logo.setToolTip("Perutz Mass Spec Facility")
            self._header_logo.setAccessibleName("Perutz Mass Spec Facility")
            header_layout.addWidget(
                self._header_logo, 0, qt_core.Qt.AlignmentFlag.AlignVCenter
            )
            header_divider = qt_widgets.QFrame(header)
            header_divider.setObjectName("headerDivider")
            header_divider.setFixedSize(1, 32)
            header_layout.addWidget(
                header_divider, 0, qt_core.Qt.AlignmentFlag.AlignVCenter
            )
            header_title_layout = qt_widgets.QHBoxLayout()
            header_title_layout.setContentsMargins(0, 0, 0, 0)
            header_title_layout.setSpacing(10)
            title = qt_widgets.QLabel("rawtrace-qc")
            title.setObjectName("appTitle")
            try:
                app_version = version("rawtrace-qc")
            except PackageNotFoundError:
                app_version = "0.1.0"
            version_label = qt_widgets.QLabel(
                app_version if app_version.startswith("v") else f"v{app_version}"
            )
            version_label.setObjectName("appVersion")
            header_title_layout.addWidget(
                title, 0, qt_core.Qt.AlignmentFlag.AlignBaseline
            )
            header_title_layout.addWidget(
                version_label, 0, qt_core.Qt.AlignmentFlag.AlignBaseline
            )
            header_title_layout.setAlignment(qt_core.Qt.AlignmentFlag.AlignVCenter)
            header_layout.addLayout(header_title_layout)
            header_layout.addStretch()
            self.thermo_tool_button = qt_widgets.QPushButton()
            self.thermo_tool_button.setObjectName("headerSettings")
            self.thermo_tool_button.setIcon(
                self._action_icon("tool-icon.svg", "#ffffff", 24)
            )
            self.thermo_tool_button.setIconSize(qt_core.QSize(20, 20))
            self.thermo_tool_button.setFixedSize(36, 36)
            self.thermo_tool_button.setCursor(qt_core.Qt.CursorShape.PointingHandCursor)
            self.thermo_tool_button.setToolTip("Thermo Tool")
            self.thermo_tool_button.setAccessibleName("Thermo Tool")
            self.thermo_tool_button.clicked.connect(self._open_thermo_tool)
            self.thermo_tool_attention = qt_widgets.QLabel(self.thermo_tool_button)
            self.thermo_tool_attention.setObjectName("headerAttentionDot")
            self.thermo_tool_attention.setFixedSize(10, 10)
            self.thermo_tool_attention.move(24, 2)
            self.thermo_tool_attention.setAttribute(
                qt_core.Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            self.thermo_tool_attention.hide()
            header_layout.addWidget(
                self.thermo_tool_button, 0, qt_core.Qt.AlignmentFlag.AlignVCenter
            )
            self.settings_button = qt_widgets.QPushButton()
            self.settings_button.setObjectName("headerSettings")
            self.settings_button.setIcon(self._settings_icon(qt_core, qt_gui))
            self.settings_button.setIconSize(qt_core.QSize(20, 20))
            self.settings_button.setFixedSize(36, 36)
            self.settings_button.setCursor(qt_core.Qt.CursorShape.PointingHandCursor)
            self.settings_button.setToolTip("Settings (Ctrl+,)")
            self.settings_button.setShortcut(qt_gui.QKeySequence("Ctrl+,"))
            self.settings_button.clicked.connect(self._open_settings)
            header_layout.addWidget(
                self.settings_button, 0, qt_core.Qt.AlignmentFlag.AlignVCenter
            )
            root.addWidget(header)

            source_frame = qt_widgets.QFrame()
            source_frame.setObjectName("card")
            source_layout = qt_widgets.QVBoxLayout(source_frame)
            source_layout.setContentsMargins(18, 16, 18, 16)
            source_layout.setSpacing(12)
            source_heading = qt_widgets.QHBoxLayout()
            source_heading.setSpacing(10)
            source_badge = qt_widgets.QLabel("1")
            source_badge.setObjectName("cardBadge")
            source_badge.setFixedSize(22, 22)
            source_badge.setAlignment(qt_core.Qt.AlignmentFlag.AlignCenter)
            source_heading.addWidget(source_badge)
            source_title = qt_widgets.QLabel("Add raw files")
            source_title.setObjectName("cardTitle")
            source_heading.addWidget(source_title)
            source_heading.addStretch()
            source_layout.addLayout(source_heading)

            source_row = qt_widgets.QHBoxLayout()
            source_row.setSpacing(8)
            self.source_edit = qt_widgets.QLineEdit()
            self.source_edit.setObjectName("folderInput")
            self.source_edit.setFixedHeight(40)
            self.source_edit.setPlaceholderText("Choose a folder to inspect")
            self.source_edit.setReadOnly(True)
            self.choose_source_button = qt_widgets.QPushButton("Choose folder")
            self.choose_source_button.setObjectName("secondary")
            self.choose_source_button.clicked.connect(self._choose_source)
            self.include_subfolders = qt_widgets.QCheckBox("Include subfolders")
            self.include_subfolders.setChecked(
                self._settings.scope is DiscoveryScope.RECURSIVE
            )
            self.include_subfolders.setToolTip(
                "Search folders below the selected folder"
            )
            self.scan_button = qt_widgets.QPushButton("Scan folder")
            self.scan_button.setObjectName("outlineTeal")
            self.scan_button.clicked.connect(self._scan_source)
            source_row.addWidget(self.source_edit, 1)
            source_row.addWidget(self.choose_source_button)
            source_row.addWidget(self.scan_button)
            source_layout.addLayout(source_row)
            source_layout.addWidget(self.include_subfolders)
            root.addWidget(source_frame)

            selected_frame = qt_widgets.QFrame()
            selected_frame.setObjectName("card")
            selected_layout = qt_widgets.QVBoxLayout(selected_frame)
            selected_layout.setContentsMargins(18, 16, 18, 16)
            selected_layout.setSpacing(12)
            selected_heading = qt_widgets.QHBoxLayout()
            selected_heading.setSpacing(10)
            selected_badge = qt_widgets.QLabel("2")
            selected_badge.setObjectName("cardBadge")
            selected_badge.setFixedSize(22, 22)
            selected_badge.setAlignment(qt_core.Qt.AlignmentFlag.AlignCenter)
            selected_heading.addWidget(selected_badge)
            selected_title = qt_widgets.QLabel("Selected files")
            selected_title.setObjectName("cardTitle")
            selected_heading.addWidget(selected_title)
            self.selected_count = qt_widgets.QLabel("0 of 0 checked")
            self.selected_count.setObjectName("countPill")
            selected_heading.addWidget(self.selected_count)
            self.excluded_count = qt_widgets.QLabel()
            self.excluded_count.setObjectName("excludedPill")
            self.excluded_count.setToolTip(
                "Excluded files are not part of the report. Hover over a file to "
                "see why and what to do."
            )
            self.excluded_count.hide()
            selected_heading.addWidget(self.excluded_count)
            selected_heading.addStretch()
            self.check_all_button = qt_widgets.QPushButton("Check all")
            self.check_all_button.setObjectName("secondarySmall")
            self.check_all_button.setFixedHeight(32)
            self.check_all_button.clicked.connect(lambda: self._set_all_selected(True))
            selected_heading.addWidget(self.check_all_button)
            self.uncheck_all_button = qt_widgets.QPushButton("Uncheck all")
            self.uncheck_all_button.setObjectName("secondarySmall")
            self.uncheck_all_button.setFixedHeight(32)
            self.uncheck_all_button.clicked.connect(
                lambda: self._set_all_selected(False)
            )
            selected_heading.addWidget(self.uncheck_all_button)
            header_divider = qt_widgets.QFrame()
            header_divider.setObjectName("headerDivider")
            header_divider.setFixedSize(1, 22)
            selected_heading.addWidget(header_divider)
            self.remove_highlighted_button = qt_widgets.QPushButton(
                "Remove highlighted"
            )
            self.remove_highlighted_button.setObjectName("destructiveOutline")
            self.remove_highlighted_button.setFixedHeight(32)
            self.remove_highlighted_button.setIcon(
                self._action_icon(
                    "trash-icon.svg",
                    theme.destructive_button_text,
                    14,
                )
            )
            self.remove_highlighted_button.setIconSize(qt_core.QSize(14, 14))
            self.remove_highlighted_button.clicked.connect(self._remove_selected)
            selected_heading.addWidget(self.remove_highlighted_button)
            selected_layout.addLayout(selected_heading)
            self.selected_list = DropList()
            self.selected_list.setObjectName("selectedList")
            self.selected_list._file_item_delegate = SelectedFileDelegate(
                self.selected_list
            )
            self.selected_list.setItemDelegate(self.selected_list._file_item_delegate)
            self.selected_list.setSelectionMode(
                qt_widgets.QAbstractItemView.SelectionMode.ExtendedSelection
            )
            self.selected_list.setTextElideMode(qt_core.Qt.TextElideMode.ElideMiddle)
            self.selected_list.setHorizontalScrollBarPolicy(
                qt_core.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.selected_list.setToolTip("Drop valid .raw files or .d folders here")
            self.selected_list.paths_dropped.connect(self._add_paths)
            self.selected_list.itemChanged.connect(self._selected_item_changed)
            selected_layout.addWidget(self.selected_list, 1)
            root.addWidget(selected_frame, 1)

            report_frame = qt_widgets.QFrame()
            report_frame.setObjectName("card")
            report_layout = qt_widgets.QVBoxLayout(report_frame)
            report_layout.setContentsMargins(18, 16, 18, 16)
            report_layout.setSpacing(12)
            report_heading = qt_widgets.QHBoxLayout()
            report_heading.setSpacing(10)
            report_badge = qt_widgets.QLabel("3")
            report_badge.setObjectName("cardBadge")
            report_badge.setFixedSize(22, 22)
            report_badge.setAlignment(qt_core.Qt.AlignmentFlag.AlignCenter)
            report_heading.addWidget(report_badge)
            report_title = qt_widgets.QLabel("Report")
            report_title.setObjectName("cardTitle")
            report_heading.addWidget(report_title)
            report_heading.addStretch()
            report_layout.addLayout(report_heading)
            report_content = qt_widgets.QHBoxLayout()
            storage_selector, _, storage_buttons = _mode_selector(
                qt_core,
                qt_widgets,
                report_frame,
                ("Temporary", "Permanent"),
            )
            self.temporary_storage, self.permanent_storage = storage_buttons
            self.permanent_storage.toggled.connect(self._storage_changed)
            report_content.addWidget(storage_selector)
            report_content.setSpacing(8)
            self.report_directory_edit = ElidedLineEdit(
                str(self._settings.report_directory)
            )
            self.report_directory_edit.setObjectName("reportDirectoryInput")
            self.report_directory_edit.setFixedHeight(40)
            self.report_directory_edit.setPlaceholderText("Permanent report directory")
            self.report_directory_edit.textChanged.connect(
                self.report_directory_edit.setToolTip
            )
            self.report_directory_edit.setToolTip(self.report_directory_edit.text())
            report_content.addWidget(self.report_directory_edit, 1)
            self.browse_report_button = qt_widgets.QPushButton("Browse")
            self.browse_report_button.setObjectName("secondary")
            self.browse_report_button.setFixedHeight(40)
            self.browse_report_button.clicked.connect(self._choose_report_directory)
            report_content.addWidget(self.browse_report_button)
            report_layout.addLayout(report_content)
            self.report_hint = qt_widgets.QLabel()
            self.report_hint.setObjectName("reportHint")
            report_layout.addWidget(self.report_hint)
            self.generate_button = qt_widgets.QPushButton("Generate report")
            self.generate_button.setObjectName("primaryButton")
            self.generate_button.setFixedHeight(44)
            self.generate_button.clicked.connect(self._generate)
            root.addWidget(report_frame)
            self.report_status = ElidedLabel()
            self.report_status.setObjectName("statusLabel")
            self.open_report_button = qt_widgets.QPushButton("Open report")
            self.open_report_button.setObjectName("secondary")
            self.open_report_button.setFixedHeight(44)
            self.open_report_button.clicked.connect(self._open_last_report)
            self.open_report_button.hide()
            self.cancel_button = qt_widgets.QPushButton("Cancel")
            self.cancel_button.setObjectName("destructiveOutline")
            self.cancel_button.setFixedHeight(44)
            self.cancel_button.clicked.connect(self._cancel_report)
            self.cancel_button.hide()
            bottom_bar = qt_widgets.QHBoxLayout()
            bottom_bar.addWidget(self.report_status, 1)
            bottom_bar.addWidget(self.open_report_button)
            bottom_bar.addWidget(self.cancel_button)
            bottom_bar.addWidget(self.generate_button)
            root.addLayout(bottom_bar)
            self.log_view = self._new_log_view()
            self.log_view.setFixedHeight(72)
            self.log_view.setPlaceholderText("Activity log")
            open_log_button = qt_widgets.QPushButton("Open log")
            open_log_button.setObjectName("secondarySmall")
            open_log_button.setFixedHeight(32)
            open_log_button.clicked.connect(self._open_log)
            log_row = qt_widgets.QHBoxLayout()
            log_row.addWidget(self.log_view, 1)
            log_row.addWidget(open_log_button, 0, qt_core.Qt.AlignmentFlag.AlignTop)
            root.addLayout(log_row)
            self._storage_changed()
            self._update_selected_count()
            if self._configuration_message:
                self._log(self._configuration_message)

        def _new_log_view(self) -> Any:
            view = qt_widgets.QPlainTextEdit()
            view.setObjectName("activityLog")
            view.setReadOnly(True)
            view.setMaximumBlockCount(_LOG_MAX_LINES)
            view.setWordWrapMode(
                qt_gui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
            )
            return view

        def _log(self, message: str) -> None:
            """Add one timestamped line to the activity log."""
            line = f"{datetime.now():%H:%M:%S}  {message}"
            self.log_view.appendPlainText(line)
            if self._log_view_large is not None:
                self._log_view_large.appendPlainText(line)

        def _open_log(self) -> None:
            """Show the activity log in a large window that stays up to date."""
            if self._log_dialog is None:
                self._log_dialog = qt_widgets.QDialog(self)
                self._log_dialog.setWindowTitle("rawtrace-qc log")
                self._log_dialog.resize(900, 560)
                layout = qt_widgets.QVBoxLayout(self._log_dialog)
                self._log_view_large = self._new_log_view()
                self._log_view_large.setPlainText(self.log_view.toPlainText())
                layout.addWidget(self._log_view_large, 1)
                buttons = qt_widgets.QHBoxLayout()
                buttons.addStretch()
                copy_button = qt_widgets.QPushButton("Copy all")
                copy_button.setObjectName("secondary")
                copy_button.clicked.connect(
                    lambda: qt_widgets.QApplication.clipboard().setText(
                        self.log_view.toPlainText()
                    )
                )
                buttons.addWidget(copy_button)
                close_button = qt_widgets.QPushButton("Close")
                close_button.setObjectName("secondary")
                close_button.clicked.connect(self._log_dialog.close)
                buttons.addWidget(close_button)
                layout.addLayout(buttons)
            self._log_dialog.show()
            self._log_dialog.raise_()
            self._log_dialog.activateWindow()

        def _set_report_status(self, text: str, state: str = "") -> None:
            self.report_status.set_full_text(text)
            self.report_status.setProperty("state", state)
            self.report_status.style().unpolish(self.report_status)
            self.report_status.style().polish(self.report_status)

        def _refresh_report_status(self) -> None:
            """Show how the current selection relates to the last report run."""
            if self._worker is not None:
                return
            active = self._selection.active_selected()
            report = self._last_report
            matches_report = report is not None and active == report.included
            self.open_report_button.setVisible(report is not None)
            self.open_report_button.setText(
                "Open report" if matches_report else "Open last report"
            )
            if (
                self._run_message is not None
                and self._run_message[0] == self._selection.selected
            ):
                self._set_report_status(self._run_message[1], self._run_message[2])
            elif matches_report:
                excluded = len(self._selection.excluded_selected())
                self._set_report_status(
                    f"Report ready: {len(active)} file(s)"
                    + (f", {excluded} excluded" if excluded else ""),
                    "warning" if excluded else "ok",
                )
            elif report is not None:
                self._set_report_status(
                    "Selection changed since the last report", "warning"
                )
            elif active:
                self._set_report_status(f"{len(active)} file(s) ready for a report")
            else:
                self._set_report_status(self._no_active_files_text())

        def _no_active_files_text(self) -> str:
            excluded = len(self._selection.excluded_selected())
            if excluded and excluded == len(self._selection.selected):
                return f"No usable files: {excluded} excluded"
            return "No files checked"

        def _set_run_message(self, text: str, state: str) -> None:
            """Show a run result until the selection changes."""
            self._run_message = (self._selection.selected, text, state)
            self._refresh_report_status()

        def _choose_source(self) -> None:
            path = qt_widgets.QFileDialog.getExistingDirectory(
                self,
                "Choose discovery folder",
                _dialog_start_directory(self.source_edit.text()),
            )
            if path:
                self.source_edit.setText(path)
                self._clear_candidates()

        def _selected_scope(self) -> DiscoveryScope:
            """Return the discovery scope selected by the subfolder checkbox."""
            return (
                DiscoveryScope.RECURSIVE
                if self.include_subfolders.isChecked()
                else DiscoveryScope.DIRECT
            )

        def _scan_source(self) -> None:
            source_text = self.source_edit.text().strip()
            if not source_text:
                self._log("Choose a folder before scanning.")
                return
            source = Path(source_text)
            scope = self._selected_scope()
            self._selection.options = replace(self._selection.options, scope=scope)
            self._settings = replace(self._settings, scope=scope)
            options = self._selection.options
            self.scan_button.setEnabled(False)
            self.choose_source_button.setEnabled(False)
            self._log(f"Scanning {source}...")
            self._scan_task = start_background_task(
                qt_core,
                lambda: discover(source, options),
                self._scan_finished,
                self._scan_failed,
            )

        def _scan_finished(self, result: DiscoveryResult) -> None:
            self._end_scan()
            if self._closing:
                return
            self._selection.set_candidates(result.candidates)
            for skip in result.skipped:
                self._log(f"Skipped {skip.path.name}: {skip.message}")
            for issue in result.issues:
                self._log(f"Could not scan {issue.path}: {issue.message}")
            self._log(
                f"Scan finished: {len(result.candidates)} valid file(s), "
                f"{len(result.skipped)} skipped, {len(result.issues)} issue(s)"
            )
            if result.candidates:
                self._open_candidates()

        def _scan_failed(self, message: str) -> None:
            self._end_scan()
            if self._closing:
                return
            self._selection.set_candidates(())
            self._log(f"Scan failed: {message}")

        def _end_scan(self) -> None:
            self._scan_task = None
            self.scan_button.setEnabled(True)
            self.choose_source_button.setEnabled(True)

        def _clear_candidates(self) -> None:
            self._selection.set_candidates(())

        def _open_candidates(self) -> None:
            dialog = qt_widgets.QDialog(self)
            dialog.setWindowTitle("Candidate raw files")
            dialog.resize(980, 700)
            layout = qt_widgets.QVBoxLayout(dialog)
            heading = qt_widgets.QHBoxLayout()
            heading.addWidget(qt_widgets.QLabel("Candidate raw files"))
            candidate_count = qt_widgets.QLabel()
            candidate_count.setObjectName("count")
            heading.addWidget(candidate_count)
            heading.addStretch()
            layout.addLayout(heading)

            pattern_title = qt_widgets.QLabel("Filename patterns")
            pattern_title.setObjectName("subheading")
            layout.addWidget(pattern_title)
            pattern_table = qt_widgets.QTableWidget(0, 4)
            pattern_table.setHorizontalHeaderLabels(("Use", "Pattern", "Regex", "Mode"))
            pattern_table.horizontalHeader().setSectionResizeMode(
                0, qt_widgets.QHeaderView.ResizeMode.ResizeToContents
            )
            pattern_table.horizontalHeader().setSectionResizeMode(
                1, qt_widgets.QHeaderView.ResizeMode.ResizeToContents
            )
            pattern_table.horizontalHeader().setSectionResizeMode(
                2, qt_widgets.QHeaderView.ResizeMode.Stretch
            )
            pattern_table.horizontalHeader().setSectionResizeMode(
                3, qt_widgets.QHeaderView.ResizeMode.ResizeToContents
            )
            layout.addWidget(pattern_table)

            custom_row = qt_widgets.QHBoxLayout()
            custom_expression = qt_widgets.QLineEdit()
            custom_expression.setPlaceholderText("Regular expression")
            add_pattern = qt_widgets.QPushButton("Add custom pattern")
            custom_row.addWidget(custom_expression, 1)
            custom_row.addWidget(add_pattern)
            layout.addLayout(custom_row)

            candidate_list = qt_widgets.QListWidget()
            candidate_list._file_item_delegate = FileItemDelegate(candidate_list)
            candidate_list.setItemDelegate(candidate_list._file_item_delegate)
            self._candidate_list = candidate_list
            candidate_list.setSelectionMode(
                qt_widgets.QAbstractItemView.SelectionMode.ExtendedSelection
            )
            layout.addWidget(candidate_list, 1)
            candidate_buttons = qt_widgets.QHBoxLayout()
            select_all = qt_widgets.QPushButton("Select all")
            select_marked = qt_widgets.QPushButton("Select marked")
            select_none = qt_widgets.QPushButton("Select none")
            add_candidates = qt_widgets.QPushButton("Add selected to report")
            add_candidates.setObjectName("primary")
            close = qt_widgets.QPushButton("Close")
            candidate_buttons.addWidget(select_all)
            candidate_buttons.addWidget(select_marked)
            candidate_buttons.addWidget(select_none)
            candidate_buttons.addStretch()
            candidate_buttons.addWidget(add_candidates)
            candidate_buttons.addWidget(close)
            layout.addLayout(candidate_buttons)

            definitions = list(self._saved_patterns) + list(self._custom_patterns)
            saved_count = len(self._saved_patterns)

            def pattern_key(pattern: FilenamePattern) -> tuple[str, str]:
                return pattern.name, pattern.expression

            def read_rows(include_disabled: bool) -> tuple[FilenamePattern, ...] | None:
                patterns: list[FilenamePattern] = []
                try:
                    for row in range(pattern_table.rowCount()):
                        check = pattern_table.cellWidget(row, 0)
                        mode_selector = pattern_table.cellWidget(row, 3)
                        name_item = pattern_table.item(row, 1)
                        expression_item = pattern_table.item(row, 2)
                        mode_group = mode_selector.findChild(qt_widgets.QButtonGroup)
                        if (
                            name_item is None
                            or expression_item is None
                            or mode_group is None
                        ):
                            raise AttributeError("Pattern mode selector is missing.")
                        mode = (
                            PatternMode.EXCLUDE
                            if mode_group.checkedId() == 1
                            else PatternMode.INCLUDE
                        )
                        pattern = FilenamePattern(
                            name_item.text(),
                            expression_item.text(),
                            mode,
                        )
                        definitions[row] = pattern
                        if include_disabled or check.isChecked():
                            patterns.append(pattern)
                except (ConfigurationError, AttributeError) as error:
                    self._log(str(error))
                    return None
                return tuple(patterns)

            def update_candidate_count() -> None:
                included = sum(entry.included for entry in self._selection.candidates)
                candidate_count.setText(
                    f"{included} active / {len(self._selection.candidates)} total"
                )

            def render_candidates() -> None:
                selected_paths = {
                    str(item.data(qt_core.Qt.ItemDataRole.UserRole))
                    for item in candidate_list.selectedItems()
                }
                self._rendering_candidates = True
                candidate_list.clear()
                for entry in self._selection.candidates:
                    item = qt_widgets.QListWidgetItem(entry.candidate.path.name)
                    path_text = str(entry.candidate.path)
                    item.setToolTip(str(entry.candidate.path))
                    item.setSizeHint(qt_core.QSize(0, 40))
                    item.setData(
                        qt_core.Qt.ItemDataRole.UserRole,
                        path_text,
                    )
                    if entry.included:
                        item.setFlags(
                            qt_core.Qt.ItemFlag.ItemIsEnabled
                            | qt_core.Qt.ItemFlag.ItemIsSelectable
                            | qt_core.Qt.ItemFlag.ItemIsUserCheckable
                        )
                        item.setCheckState(
                            qt_core.Qt.CheckState.Checked
                            if entry.active
                            else qt_core.Qt.CheckState.Unchecked
                        )
                    else:
                        item.setFlags(qt_core.Qt.ItemFlag.ItemIsEnabled)
                        item.setForeground(qt_gui.QBrush(qt_gui.QColor("#84909a")))
                    candidate_list.addItem(item)
                    item.setSelected(path_text in selected_paths)
                update_candidate_count()
                self._rendering_candidates = False

            def refresh_patterns() -> None:
                active = read_rows(False)
                if active is None:
                    return
                self._active_pattern_keys = {pattern_key(pattern) for pattern in active}
                self._selection.apply_patterns(active)
                render_candidates()

            def pattern_mode_selector(mode: PatternMode) -> Any:
                selector, mode_group, mode_buttons = _mode_selector(
                    qt_core,
                    qt_widgets,
                    dialog,
                    ("Include", "Exclude"),
                )
                mode_buttons[0].setChecked(mode is PatternMode.INCLUDE)
                mode_buttons[1].setChecked(mode is PatternMode.EXCLUDE)
                mode_group.buttonToggled.connect(lambda *_args: refresh_patterns())
                return selector

            def rebuild_pattern_table() -> None:
                pattern_table.blockSignals(True)
                pattern_table.setRowCount(0)
                for row, pattern in enumerate(definitions):
                    pattern_table.insertRow(row)
                    check = qt_widgets.QCheckBox()
                    check.setChecked(pattern_key(pattern) in self._active_pattern_keys)
                    check.stateChanged.connect(refresh_patterns)
                    pattern_table.setCellWidget(row, 0, check)
                    pattern_table.setItem(
                        row, 1, qt_widgets.QTableWidgetItem(pattern.name)
                    )
                    pattern_table.setItem(
                        row, 2, qt_widgets.QTableWidgetItem(pattern.expression)
                    )
                    pattern_table.setCellWidget(
                        row, 3, pattern_mode_selector(pattern.mode)
                    )
                pattern_table.blockSignals(False)

            def candidate_item_changed(item: Any) -> None:
                if self._rendering_candidates:
                    return
                path = Path(item.data(qt_core.Qt.ItemDataRole.UserRole))
                self._selection.set_candidate_active(
                    path,
                    item.checkState() == qt_core.Qt.CheckState.Checked,
                )
                update_candidate_count()

            def add_custom_pattern() -> None:
                try:
                    pattern = FilenamePattern(
                        f"Custom {len(self._custom_patterns) + 1}",
                        custom_expression.text(),
                        PatternMode.INCLUDE,
                    )
                except ConfigurationError as error:
                    qt_widgets.QMessageBox.warning(
                        dialog, "Invalid pattern", str(error)
                    )
                    return
                definitions.append(pattern)
                self._custom_patterns.append(pattern)
                self._active_pattern_keys.add(pattern_key(pattern))
                custom_expression.clear()
                rebuild_pattern_table()
                refresh_patterns()

            def promote_candidates() -> None:
                if read_rows(False) is None:
                    return
                excluded_before = len(self._selection.excluded_selected())
                self._selection.promote_active_candidates()
                self._refresh_selected()
                self._log_added_exclusions(excluded_before)
                self._log(
                    f"{len(self._selection.active_selected())} selected raw file(s) "
                    "active"
                )
                dialog.accept()

            def persist_pattern_definitions() -> None:
                all_patterns = read_rows(True)
                if all_patterns is None:
                    return
                self._saved_patterns = list(all_patterns[:saved_count])
                self._custom_patterns = list(all_patterns[saved_count:])
                self._settings = replace(
                    self._settings,
                    patterns=tuple(self._saved_patterns),
                )

            candidate_list.itemChanged.connect(candidate_item_changed)
            pattern_table.itemChanged.connect(lambda _item: refresh_patterns())
            select_all.clicked.connect(
                lambda: self._set_candidate_checks(True, render_candidates)
            )
            select_marked.clicked.connect(
                lambda: self._set_marked_candidate_checks(candidate_list, True)
            )
            select_none.clicked.connect(
                lambda: self._set_candidate_checks(False, render_candidates)
            )
            add_pattern.clicked.connect(add_custom_pattern)
            add_candidates.clicked.connect(promote_candidates)
            close.clicked.connect(dialog.reject)
            rebuild_pattern_table()
            refresh_patterns()
            dialog.finished.connect(lambda _: persist_pattern_definitions())
            dialog.exec()
            self._candidate_list = None

        def _set_candidate_checks(self, active: bool, render: Any) -> None:
            for entry in self._selection.candidates:
                if entry.included:
                    self._selection.set_candidate_active(entry.candidate.path, active)
            render()

        def _set_marked_candidate_checks(
            self,
            candidate_list: Any,
            active: bool,
        ) -> None:
            """Set checked state for the currently mouse-marked candidates."""
            for item in candidate_list.selectedItems():
                if item.flags() & qt_core.Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        qt_core.Qt.CheckState.Checked
                        if active
                        else qt_core.Qt.CheckState.Unchecked
                    )

        def _refresh_selected(self) -> None:
            selected_paths = {
                str(item.data(qt_core.Qt.ItemDataRole.UserRole))
                for item in self.selected_list.selectedItems()
            }
            self._rendering_selected = True
            self.selected_list.clear()
            for entry in self._selection.selected:
                item = qt_widgets.QListWidgetItem(entry.candidate.path.name)
                path_text = str(entry.candidate.path)
                item.setToolTip(str(entry.candidate.path))
                item.setData(
                    qt_core.Qt.ItemDataRole.UserRole,
                    path_text,
                )
                if entry.exclusion is None:
                    item.setFlags(
                        qt_core.Qt.ItemFlag.ItemIsEnabled
                        | qt_core.Qt.ItemFlag.ItemIsSelectable
                        | qt_core.Qt.ItemFlag.ItemIsUserCheckable
                    )
                    item.setCheckState(
                        qt_core.Qt.CheckState.Checked
                        if entry.active
                        else qt_core.Qt.CheckState.Unchecked
                    )
                else:
                    item.setFlags(
                        qt_core.Qt.ItemFlag.ItemIsEnabled
                        | qt_core.Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setData(exclusion_role, entry.exclusion.reason.value)
                    item.setToolTip(
                        f"{path_text}\nExcluded: {entry.exclusion.reason.value}\n"
                        f"{textwrap.fill(entry.exclusion.detail, width=100)}\n"
                        f"{entry.exclusion.next_step}"
                    )
                self.selected_list.addItem(item)
                item.setSelected(path_text in selected_paths)
            self._update_selected_count()
            self._rendering_selected = False

        def _selected_item_changed(self, item: Any) -> None:
            if self._rendering_selected:
                return
            path = Path(item.data(qt_core.Qt.ItemDataRole.UserRole))
            self._selection.set_selected_active(
                path,
                item.checkState() == qt_core.Qt.CheckState.Checked,
            )
            self._update_selected_count()

        def _update_selected_count(self) -> None:
            """Refresh the checked count and action-button states."""
            active_count = len(self._selection.active_selected())
            total_count = len(self._selection.selected)
            self.selected_count.setText(f"{active_count} of {total_count} checked")
            has_items = total_count > 0
            self.check_all_button.setEnabled(has_items)
            self.uncheck_all_button.setEnabled(has_items)
            self.remove_highlighted_button.setEnabled(has_items)
            excluded_count = len(self._selection.excluded_selected())
            self.excluded_count.setText(f"{excluded_count} of {total_count} excluded")
            self.excluded_count.setVisible(excluded_count > 0)
            self._refresh_report_status()

        def _add_paths(self, paths: tuple[Path, ...]) -> None:
            excluded_before = len(self._selection.excluded_selected())
            result = self._selection.add_paths(paths)
            self._refresh_selected()
            if result.accepted:
                self._log(f"Added {len(result.accepted)} valid path(s)")
            self._log_added_exclusions(excluded_before)
            explained = {skip.path.resolve() for skip in result.skipped}
            for skip in result.skipped:
                self._log(f"Rejected {skip.path.name}: {skip.message}")
            for path in result.rejected:
                if path not in explained:
                    self._log(
                        f"Rejected {path}: not a supported raw file or acquisition "
                        "folder"
                    )

        def _log_added_exclusions(self, excluded_before: int) -> None:
            """Log Thermo files that were excluded as soon as they were added."""
            added = len(self._selection.excluded_selected()) - excluded_before
            self._log_thermo_exclusions(added, "added file(s)")

        def _log_thermo_exclusions(self, count: int, files: str) -> None:
            exclusion = self._selection.thermo_exclusion
            if count > 0 and exclusion is not None:
                self._log(
                    f"{exclusion.reason.value}: {count} {files} excluded. "
                    f"{exclusion.next_step}"
                )

        def _remove_selected(self) -> None:
            paths = tuple(
                Path(item.data(qt_core.Qt.ItemDataRole.UserRole))
                for item in self.selected_list.selectedItems()
            )
            self._selection.remove_selected(paths)
            self._refresh_selected()

        def _set_all_selected(self, active: bool) -> None:
            self._selection.set_all_selected_active(active)
            self._refresh_selected()

        def _storage_changed(self) -> None:
            permanent = self.permanent_storage.isChecked()
            self.report_directory_edit.setEnabled(permanent)
            self.browse_report_button.setEnabled(permanent)
            if permanent:
                self.report_hint.setText(
                    "Permanent report. Saved to the selected folder with an "
                    "auto-generated timestamp "
                    "(rawtrace-qc-YYYYMMDD-HHMMSS.html). The default folder can "
                    "be changed in Settings."
                )
            else:
                self.report_hint.setText(
                    "Temporary report. Stored in your system's temp folder, "
                    "opened in your browser, and deleted when the application "
                    "closes. Choose Permanent to save it."
                )

        def _choose_report_directory(self) -> None:
            path = qt_widgets.QFileDialog.getExistingDirectory(
                self,
                "Choose permanent report directory",
                _dialog_start_directory(self.report_directory_edit.text()),
            )
            if path:
                self.report_directory_edit.setText(path)

        def _generate(self) -> None:
            try:
                storage_mode = (
                    ReportStorageMode.PERMANENT
                    if self.permanent_storage.isChecked()
                    else ReportStorageMode.TEMPORARY
                )
                output_directory = Path(self.report_directory_edit.text())
                options = ReportGenerationOptions(
                    storage_mode=storage_mode,
                    output_directory=output_directory,
                    precision_mode="low",
                )
            except (ConfigurationError, ValueError) as error:
                self._log(f"Report not started: {error}")
                self._set_report_status("Report not started (see log)", "error")
                return
            self._pending_options = options
            if any(
                entry.candidate.vendor == Vendor.THERMO
                for entry in self._selection.selected
            ):
                self.generate_button.setEnabled(False)
                self._set_report_status("Checking the Thermo tool...")
                self._worker = start_background_task(
                    qt_core,
                    get_thermo_helper_status,
                    self._thermo_tool_checked,
                    self._thermo_tool_check_failed,
                )
                return
            self._start_pending_report(None)

        def _thermo_tool_checked(self, status: ThermoHelperStatus) -> None:
            self._worker = None
            self._set_thermo_status(status)
            self._start_pending_report(status)

        def _thermo_tool_check_failed(self, message: str) -> None:
            self._worker = None
            self._thermo_status_failed(message)
            self._start_pending_report(None)

        def _start_pending_report(self, status: ThermoHelperStatus | None) -> None:
            """Start the requested report with the files that remain active."""
            options = self._pending_options
            self._pending_options = None
            candidates = self._selection.active_selected()
            if candidates:
                self._start_report(candidates, options)
                return
            self.generate_button.setEnabled(True)
            self._refresh_report_status()
            self._log(f"Report not started: {self._no_active_files_text()}")
            if (
                status is not None
                and not status.is_ready
                and any(
                    entry.exclusion is not None
                    and entry.exclusion.caused_by_thermo_tool
                    for entry in self._selection.selected
                )
            ):
                self._prompt_thermo_tool_setup(status)

        def _prompt_thermo_tool_setup(self, status: ThermoHelperStatus) -> None:
            message = qt_widgets.QMessageBox(self)
            message.setIcon(qt_widgets.QMessageBox.Icon.Warning)
            message.setWindowTitle("Thermo tool required")
            message.setText(thermo_tool_required_message(status))
            open_button = message.addButton(
                "Open Thermo Tool", qt_widgets.QMessageBox.ButtonRole.AcceptRole
            )
            message.addButton(qt_widgets.QMessageBox.StandardButton.Close)
            message.exec()
            if message.clickedButton() == open_button:
                self._open_thermo_tool()

        def refresh_thermo_status(self) -> None:
            """Check the Thermo helper in the background and update the header."""
            self._thermo_status_task = start_background_task(
                qt_core,
                get_thermo_helper_status,
                self._set_thermo_status,
                self._thermo_status_failed,
            )

        def _set_thermo_status(self, status: ThermoHelperStatus) -> None:
            self._thermo_status_task = None
            self.thermo_tool_button.setToolTip(thermo_tool_tooltip(status))
            self.thermo_tool_attention.setVisible(thermo_tool_needs_attention(status))
            changed = self._selection.set_thermo_ready(
                status.is_ready,
                status.message,
                supported=status.state is not ThermoHelperState.UNSUPPORTED_PLATFORM,
            )
            if status.is_ready and changed:
                self._log(f"Thermo tool ready: {changed} file(s) restored")
            self._log_thermo_exclusions(changed, "file(s)")
            self._refresh_selected()

        def _thermo_status_failed(self, message: str) -> None:
            self._thermo_status_task = None
            self.thermo_tool_button.setToolTip(f"Thermo Tool: {message}")
            self.thermo_tool_attention.show()
            changed = self._selection.set_thermo_ready(False, message)
            self._log(
                f"Could not check the Thermo tool, {changed} file(s) excluded: "
                f"{message}"
            )
            self._refresh_selected()

        def _open_thermo_tool(self) -> None:
            create_thermo_tool_dialog(
                qt_core, qt_gui, qt_widgets, self, self._set_thermo_status
            ).exec()

        def _start_report(self, candidates: Any, options: Any) -> None:
            self._worker = ReportWorker(candidates, options, self._cache)
            signals = self._worker.signals
            signals.finished.connect(self._report_finished)
            signals.failed.connect(self._report_failed)
            signals.cancelled.connect(self._report_cancelled)
            signals.progress.connect(self._report_progress)
            signals.excluded.connect(self._report_file_excluded)
            self._run_message = None
            self._last_progress_stage = None
            self.generate_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.cancel_button.show()
            self._set_report_status("Starting report...")
            self._log(f"Generating a report from {len(candidates)} file(s)")
            qt_core.QThreadPool.globalInstance().start(self._worker)

        def _report_progress(self, progress: ReportProgress) -> None:
            if self._worker is None or self._worker.cancel.is_set():
                return
            self._set_report_status(progress.message)
            if (
                progress.stage is ReportStage.EXTRACTING
                or progress.stage is not self._last_progress_stage
            ):
                self._log(progress.message)
            self._last_progress_stage = progress.stage

        def _report_file_excluded(self, file: ExcludedFile) -> None:
            self._selection.exclude(file.candidate.path, file.exclusion)
            self._refresh_selected()
            self._log(
                f"Excluded {file.candidate.path.name} "
                f"({file.exclusion.reason.value}): {file.exclusion.detail}"
            )

        def _cancel_report(self) -> None:
            if self._worker is None:
                return
            self._worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self._set_report_status("Cancelling...")
            self._log("Cancelling the report")

        def _open_last_report(self) -> None:
            if self._last_report is not None:
                webbrowser.open(self._last_report.output_path.as_uri())

        def _end_report_run(self) -> None:
            self._worker = None
            self.generate_button.setEnabled(True)
            self.cancel_button.hide()

        def _report_finished(self, result: ReportGenerationResult) -> None:
            self._end_report_run()
            self._last_report = result
            self._log(
                f"Report ready: {result.output_path} ({len(result.included)} file(s), "
                f"{len(result.excluded)} excluded in this run, "
                f"{result.cache_hits} cache hit(s))"
            )
            self._refresh_report_status()
            webbrowser.open(result.output_path.as_uri())

        def _report_failed(self, message: str) -> None:
            self._end_report_run()
            self._log(f"Report failed: {message}")
            self._set_run_message("Report failed (see log)", "error")

        def _report_cancelled(self) -> None:
            self._end_report_run()
            self._log("Report cancelled")
            self._set_run_message("Report cancelled", "")

        def _open_settings(self) -> None:
            dialog = qt_widgets.QDialog(self)
            dialog.setObjectName("settingsDialog")
            dialog.setWindowTitle("rawtrace-qc settings")
            dialog.resize(900, 560)
            layout = qt_widgets.QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(14)

            def make_card(title: str) -> tuple[Any, Any]:
                card = qt_widgets.QFrame()
                card.setObjectName("card")
                card_layout = qt_widgets.QVBoxLayout(card)
                card_layout.setContentsMargins(18, 16, 18, 16)
                card_layout.setSpacing(14)
                title_label = qt_widgets.QLabel(title)
                title_label.setObjectName("settingsCardTitle")
                card_layout.addWidget(title_label)
                form = qt_widgets.QFormLayout()
                form.setHorizontalSpacing(16)
                form.setVerticalSpacing(12)
                form.setFieldGrowthPolicy(
                    qt_widgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
                )
                card_layout.addLayout(form)
                layout.addWidget(card)
                return card, form

            def add_setting_row(
                form: Any, text: str, field: Any, tooltip: str = ""
            ) -> Any:
                label = qt_widgets.QLabel(text)
                label.setObjectName("settingsFormLabel")
                label.setFixedWidth(190)
                if tooltip:
                    label.setToolTip(tooltip)
                    field.setToolTip(tooltip)
                form.addRow(label, field)
                return label

            _, appearance_form = make_card("Appearance")
            _, filters_form = make_card("File filters")
            _, storage_form = make_card("Storage")

            theme_combo = ThemedComboBox()
            theme_combo.setObjectName("themeMode")
            theme_combo.setFixedWidth(220)
            theme_combo.setFixedHeight(40)
            theme_modes = (("System", "system"), ("Light", "light"), ("Dark", "dark"))
            for label, mode in theme_modes:
                theme_combo.addItem(label, mode)
            theme_combo.setCurrentIndex(
                next(
                    index
                    for index, (_, mode) in enumerate(theme_modes)
                    if mode == self._settings.theme_mode
                )
            )
            add_setting_row(appearance_form, "Theme", theme_combo)

            size_edit = qt_widgets.QLineEdit(str(int(self._settings.min_size_mb)))
            size_edit.setObjectName("settingsField")
            size_edit.setFixedWidth(160)
            size_edit.setFixedHeight(40)
            size_edit.setValidator(
                qt_gui.QRegularExpressionValidator(
                    qt_core.QRegularExpression("[0-9]*"),
                    size_edit,
                )
            )
            age_edit = qt_widgets.QLineEdit(str(self._settings.min_age_minutes))
            age_edit.setObjectName("settingsField")
            age_edit.setFixedWidth(160)
            age_edit.setFixedHeight(40)
            age_edit.setValidator(
                qt_gui.QRegularExpressionValidator(
                    qt_core.QRegularExpression("[0-9]*(\\.[0-9]*)?"),
                    age_edit,
                )
            )
            for line_edit, unit_text, tooltip in (
                (
                    size_edit,
                    "MB",
                    "Files smaller than this are skipped when scanning.",
                ),
                (
                    age_edit,
                    "min",
                    "Files modified more recently than this are skipped, for example "
                    "while they are still being acquired.",
                ),
            ):
                unit_label = qt_widgets.QLabel(unit_text, line_edit)
                unit_label.setObjectName("fieldUnit")
                unit_label.setToolTip(tooltip)
                unit_layout = qt_widgets.QHBoxLayout(line_edit)
                unit_layout.setContentsMargins(0, 0, 12, 0)
                unit_layout.addStretch()
                unit_layout.addWidget(unit_label)
                line_edit.setTextMargins(0, 0, 36, 0)

            add_setting_row(
                filters_form,
                "Ignore files smaller than",
                size_edit,
                "Files smaller than this are skipped when scanning.",
            )
            add_setting_row(
                filters_form,
                "Ignore files newer than",
                age_edit,
                "Files modified more recently than this are skipped, for example "
                "while they are still being acquired.",
            )

            cache_edit = ElidedLineEdit(str(self._settings.cache_directory))
            cache_edit.setObjectName("settingsPathField")
            cache_edit.setFixedHeight(40)
            report_edit = ElidedLineEdit(str(self._settings.report_directory))
            report_edit.setObjectName("settingsPathField")
            report_edit.setFixedHeight(40)
            for path_edit in (cache_edit, report_edit):
                path_edit.setToolTip(path_edit.text())
                path_edit.textChanged.connect(path_edit.setToolTip)
            cache_editor = _path_editor(cache_edit, dialog)
            report_editor = _path_editor(report_edit, dialog)
            add_setting_row(
                storage_form,
                "Trace cache",
                cache_editor,
                "Where extracted trace data is cached.",
            )
            add_setting_row(
                storage_form,
                "Permanent reports",
                report_editor,
                "Default folder for permanent reports.",
            )

            button_row = qt_widgets.QHBoxLayout()
            button_row.setSpacing(8)
            reset_button = qt_widgets.QPushButton("Reset defaults")
            reset_button.setObjectName("textButton")
            apply_button = qt_widgets.QPushButton("Apply")
            cancel_button = qt_widgets.QPushButton("Cancel")
            apply_button.setObjectName("secondary")
            cancel_button.setObjectName("secondary")
            save_button = qt_widgets.QPushButton("Save")
            save_button.setObjectName("dialogPrimary")
            save_button.setDefault(True)
            save_button.setFixedHeight(40)

            def apply_settings(persist: bool) -> None:
                self._apply_settings_dialog(
                    dialog,
                    cache_edit,
                    report_edit,
                    size_edit,
                    age_edit,
                    theme_combo,
                    persist=persist,
                )

            reset_button.clicked.connect(
                lambda: self._reset_settings_dialog(
                    cache_edit,
                    report_edit,
                    size_edit,
                    age_edit,
                    theme_combo,
                )
            )
            apply_button.clicked.connect(lambda: apply_settings(False))
            save_button.clicked.connect(lambda: apply_settings(True))
            cancel_button.clicked.connect(dialog.reject)
            button_row.addWidget(reset_button)
            button_row.addStretch()
            button_row.addWidget(cancel_button)
            button_row.addWidget(apply_button)
            button_row.addWidget(save_button)
            layout.addLayout(button_row)
            tab_order = (
                theme_combo,
                size_edit,
                age_edit,
                cache_edit,
                cache_editor.findChild(qt_widgets.QPushButton),
                report_edit,
                report_editor.findChild(qt_widgets.QPushButton),
                reset_button,
                cancel_button,
                apply_button,
                save_button,
            )
            for first, second in zip(tab_order, tab_order[1:], strict=False):
                qt_widgets.QWidget.setTabOrder(first, second)
            dialog.exec()

        def _apply_settings_dialog(
            self,
            dialog: Any,
            cache_edit: Any,
            report_edit: Any,
            size_edit: Any,
            age_edit: Any,
            theme_combo: Any,
            persist: bool,
        ) -> None:
            nonlocal cache
            try:
                size_text = size_edit.text().strip()
                if not size_text:
                    raise ConfigurationError(
                        "Minimum file size must be a non-negative integer."
                    )
                age_text = age_edit.text().strip()
                if not age_text:
                    raise ConfigurationError(
                        "Minimum file age must be a non-negative integer."
                    )

                updated = GuiSettings(
                    scope=self._selected_scope(),
                    min_size_mb=int(size_text),
                    min_age_minutes=float(age_text),
                    patterns=tuple(self._saved_patterns),
                    cache_directory=Path(cache_edit.text()),
                    report_directory=Path(report_edit.text()),
                    theme_mode=str(theme_combo.currentData()),
                )
                if persist:
                    save_settings(updated, settings_path)
            except (ConfigurationError, OSError, ValueError) as error:
                qt_widgets.QMessageBox.critical(dialog, "Invalid settings", str(error))
                return
            self._settings = updated
            self._selection.options = updated.discovery_options()
            cache = TraceCache(updated.cache_directory)
            self._cache = cache
            self.report_directory_edit.setText(str(updated.report_directory))
            self._apply_current_theme()
            dialog.accept()

        def _reset_settings_dialog(
            self,
            cache_edit: Any,
            report_edit: Any,
            size_edit: Any,
            age_edit: Any,
            theme_combo: Any,
        ) -> None:
            defaults = GuiSettings()
            cache_edit.setText(str(defaults.cache_directory))
            report_edit.setText(str(defaults.report_directory))
            size_edit.setText(str(defaults.min_size_mb))
            age_edit.setText(str(defaults.min_age_minutes))
            theme_combo.setCurrentIndex(0)

        def closeEvent(self, event: Any) -> None:
            if self._worker is not None:
                qt_widgets.QMessageBox.information(
                    self,
                    "Report in progress",
                    "Cancel the current report or wait for it to finish before "
                    "closing the application.",
                )
                event.ignore()
                return
            self._closing = True
            self._workspace.cleanup()
            event.accept()

    workspace = ReportWorkspace()
    cache = TraceCache(settings.cache_directory)
    window = MainWindow()
    return window


def _load_qt() -> tuple[Any, Any, Any]:
    """Load PySide6 lazily so the core package keeps Qt optional."""
    try:
        return (
            import_module("PySide6.QtCore"),
            import_module("PySide6.QtGui"),
            import_module("PySide6.QtWidgets"),
        )
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "The rawtrace-qc desktop application requires the optional 'gui' "
            'extra. Install it with `pip install "rawtrace-qc[gui]"` or '
            '`uv tool install "rawtrace-qc[gui]"`.'
        ) from error


def _mode_selector(
    qt_core: Any,
    qt_widgets: Any,
    parent: Any,
    labels: tuple[str, str],
) -> tuple[Any, Any, tuple[Any, Any]]:
    """Build a compact two-option selector from checkable tool buttons."""
    container = qt_widgets.QWidget(parent)
    container.setObjectName("modeSelector")
    layout = qt_widgets.QHBoxLayout(container)
    layout.setContentsMargins(3, 3, 3, 3)
    layout.setSpacing(2)
    group = qt_widgets.QButtonGroup(container)
    group.setExclusive(True)
    first = qt_widgets.QToolButton(container)
    second = qt_widgets.QToolButton(container)
    first.setText(labels[0])
    second.setText(labels[1])
    for button in (first, second):
        button.setObjectName("modeOption")
        button.setCheckable(True)
        button.setFixedHeight(34)
        button.setToolButtonStyle(qt_core.Qt.ToolButtonStyle.ToolButtonTextOnly)
        layout.addWidget(button)
    group.addButton(first, 0)
    group.addButton(second, 1)
    first.setChecked(True)
    return container, group, (first, second)


def _path_editor(line_edit: Any, dialog: Any) -> Any:
    """Add a directory browse button beside one settings path field."""
    qt_widgets = import_module("PySide6.QtWidgets")
    container = qt_widgets.QWidget(dialog)
    layout = qt_widgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    button = qt_widgets.QPushButton("Browse")
    button.setObjectName("secondary")
    button.setFixedHeight(40)

    def browse() -> None:
        path = qt_widgets.QFileDialog.getExistingDirectory(
            dialog, "Choose directory", _dialog_start_directory(line_edit.text())
        )
        if path:
            line_edit.setText(path)

    button.clicked.connect(browse)
    layout.addWidget(line_edit, 1)
    layout.addWidget(button)
    return container


def _dialog_start_directory(path_text: str) -> str:
    """Return an existing selected path or the application data directory."""
    selected_text = path_text.strip()
    if selected_text:
        selected_path = Path(selected_text).expanduser()
        if selected_path.exists():
            return str(
                selected_path if selected_path.is_dir() else selected_path.parent
            )
    return str(default_data_directory())

"""PySide6 desktop interface for discovery and one-button report generation."""

from __future__ import annotations

import sys
import webbrowser
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Any

from rawtrace_qc.discovery import DiscoveryScope
from rawtrace_qc.environment import default_data_directory
from rawtrace_qc.errors import ConfigurationError, DiscoveryError
from rawtrace_qc.gui.cache import TraceCache
from rawtrace_qc.gui.config import (
    GuiSettings,
    load_settings,
    save_settings,
)
from rawtrace_qc.gui.patterns import FilenamePattern, PatternMode
from rawtrace_qc.gui.reporting import (
    ReportGenerationOptions,
    ReportGenerationResult,
    ReportStorageMode,
    ReportWorkspace,
    generate_report,
)
from rawtrace_qc.gui.theme import (
    apply_theme,
    get_active_theme,
    resolve_theme,
)
from rawtrace_qc.gui.workflow import RawFileSelection
from rawtrace_qc.thermo import THERMO_HELPER_SPECIFICATION


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
            if not index.flags() & qt_core.Qt.ItemFlag.ItemIsUserCheckable:
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
            display_option.rect.adjust(24, 0, 0, 0)
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
            if index.data(qt_core.Qt.ItemDataRole.CheckStateRole) == (
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

    class WorkerSignals(qt_core.QObject):
        """Carry background report results back to the GUI thread."""

        finished = qt_core.Signal(object)
        failed = qt_core.Signal(str)

    class ReportWorker(qt_core.QRunnable):
        """Run report generation without blocking the Qt event loop."""

        def __init__(self, candidates: tuple[Any, ...], options: Any) -> None:
            super().__init__()
            self.candidates = candidates
            self.options = options
            self.signals = WorkerSignals()

        def run(self) -> None:
            try:
                result = generate_report(
                    self.candidates,
                    cache,
                    options=self.options,
                    workspace=workspace,
                    thermo_settings=current_settings.thermo,
                )
            except Exception as error:
                self.signals.failed.emit(str(error))
            else:
                self.signals.finished.emit(result)

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

    class ElidedLabel(qt_widgets.QLabel):
        """Display long labels with a trailing ellipsis and preserve the full text."""

        def __init__(self, text: str, parent: Any | None = None) -> None:
            super().__init__(text, parent)
            self._full_text = text

        def resizeEvent(self, event: Any) -> None:
            super().resizeEvent(event)
            metrics = qt_gui.QFontMetrics(self.font())
            self.setText(
                metrics.elidedText(
                    self._full_text,
                    qt_core.Qt.TextElideMode.ElideRight,
                    self.contentsRect().width(),
                )
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
            self.resize(1180, 820)
            self.setMinimumSize(900, 620)
            self._settings = settings
            self._saved_patterns = list(settings.patterns)
            self._custom_patterns: list[FilenamePattern] = []
            self._active_pattern_keys: set[tuple[str, str]] = set()
            self._selection = RawFileSelection(settings.discovery_options())
            self._workspace = workspace
            self._cache = cache
            self._worker: Any = None
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
            header_text_layout = qt_widgets.QVBoxLayout()
            header_text_layout.setSpacing(2)
            title = qt_widgets.QLabel("rawtrace-qc")
            title.setObjectName("appTitle")
            subtitle = qt_widgets.QLabel("Raw-file review  /  report desk")
            subtitle.setObjectName("appSubtitle")
            header_text_layout.addWidget(title)
            header_text_layout.addWidget(subtitle)
            header_layout.addLayout(header_text_layout)
            header_layout.addStretch()
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
            choose_source = qt_widgets.QPushButton("Choose folder")
            choose_source.setObjectName("secondary")
            choose_source.clicked.connect(self._choose_source)
            self.include_subfolders = qt_widgets.QCheckBox("Include subfolders")
            self.include_subfolders.setChecked(
                self._settings.scope is DiscoveryScope.RECURSIVE
            )
            self.include_subfolders.setToolTip(
                "Search folders below the selected folder"
            )
            scan_button = qt_widgets.QPushButton("Scan folder")
            scan_button.setObjectName("outlineTeal")
            scan_button.clicked.connect(self._scan_source)
            source_row.addWidget(self.source_edit, 1)
            source_row.addWidget(choose_source)
            source_row.addWidget(scan_button)
            source_layout.addLayout(source_row)
            source_layout.addWidget(self.include_subfolders)
            root.addWidget(source_frame)
            self.discovery_status = qt_widgets.QLabel("No folder scanned yet")
            self.discovery_status.setObjectName("statusLabel")

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
            self.selected_list._file_item_delegate = FileItemDelegate(
                self.selected_list
            )
            self.selected_list.setItemDelegate(self.selected_list._file_item_delegate)
            self.selected_list.setSelectionMode(
                qt_widgets.QAbstractItemView.SelectionMode.ExtendedSelection
            )
            self.selected_list.setTextElideMode(qt_core.Qt.TextElideMode.ElideMiddle)
            self.selected_list.setToolTip("Drop valid .raw files or .d folders here")
            self.selected_list.paths_dropped.connect(self._add_paths)
            self.selected_list.itemChanged.connect(self._selected_item_changed)
            selected_layout.addWidget(self.selected_list, 1)
            self._update_selected_count()
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
            bottom_bar = qt_widgets.QHBoxLayout()
            bottom_bar.addWidget(self.discovery_status, 1)
            bottom_bar.addWidget(self.generate_button)
            root.addLayout(bottom_bar)
            self._storage_changed()
            if self._configuration_message:
                self.discovery_status.setText(self._configuration_message)

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
            nonlocal current_settings
            source_text = self.source_edit.text().strip()
            if not source_text:
                self.discovery_status.setText("Choose a folder before scanning.")
                return
            try:
                scope = self._selected_scope()
                self._selection.options = replace(self._selection.options, scope=scope)
                self._settings = replace(self._settings, scope=scope)
                current_settings = self._settings
                result = self._selection.discover_folder(Path(source_text))
            except (DiscoveryError, OSError, ValueError) as error:
                self._clear_candidates()
                self.discovery_status.setText(str(error))
                return
            if not result.candidates:
                self.discovery_status.setText("No valid rawfiles were found in folder")
                return
            self.discovery_status.setText(
                f"{len(result.candidates)} valid candidate(s) found"
                + (
                    f"  /  {len(result.issues)} traversal issue(s)"
                    if result.issues
                    else ""
                )
            )
            self._open_candidates()

        def _clear_candidates(self) -> None:
            self._selection.set_candidates(())
            self.discovery_status.setText("Candidate list cleared")

        def _open_candidates(self) -> None:
            if not self._selection.candidates:
                self.discovery_status.setText("No valid rawfiles were found in folder")
                return
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
                    self.discovery_status.setText(str(error))
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
                self._selection.promote_active_candidates()
                self._refresh_selected()
                self.discovery_status.setText(
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

        def _add_paths(self, paths: tuple[Path, ...]) -> None:
            result = self._selection.add_paths(paths)
            self._refresh_selected()
            messages = []
            if result.accepted:
                messages.append(f"Added {len(result.accepted)} valid path(s)")
            if result.rejected:
                messages.append(f"Rejected {len(result.rejected)} invalid path(s)")
            self.discovery_status.setText("  /  ".join(messages) or "No paths added")

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
            candidates = self._selection.active_selected()
            if not candidates:
                self.discovery_status.setText(
                    "Select at least one active raw file first."
                )
                return
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
                self.discovery_status.setText(str(error))
                return
            self._worker = ReportWorker(candidates, options)
            self._worker.signals.finished.connect(self._report_finished)
            self._worker.signals.failed.connect(self._report_failed)
            self.generate_button.setEnabled(False)
            self.discovery_status.setText("Generating report in the background...")
            qt_core.QThreadPool.globalInstance().start(self._worker)

        def _report_finished(self, result: ReportGenerationResult) -> None:
            self._worker = None
            self.generate_button.setEnabled(True)
            self.discovery_status.setText(
                f"Report ready: {result.output_path}  /  "
                f"{result.cache_hits} cache hit(s)"
            )
            webbrowser.open(result.output_path.as_uri())

        def _report_failed(self, message: str) -> None:
            self._worker = None
            self.generate_button.setEnabled(True)
            self.discovery_status.setText(f"Report failed: {message}")

        def _open_settings(self) -> None:
            dialog = qt_widgets.QDialog(self)
            dialog.setObjectName("settingsDialog")
            dialog.setWindowTitle("rawtrace-qc settings")
            dialog.resize(900, 740)
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
            _, thermo_form = make_card("Thermo helper")

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
            cache_editor = _path_editor(cache_edit, dialog, False)
            report_editor = _path_editor(report_edit, dialog, False)
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

            pinned_version = qt_widgets.QWidget()
            pinned_layout = qt_widgets.QHBoxLayout(pinned_version)
            pinned_layout.setContentsMargins(0, 0, 0, 0)
            pinned_layout.setSpacing(8)
            version_pill = qt_widgets.QLabel(f"v{THERMO_HELPER_SPECIFICATION.version}")
            version_pill.setObjectName("pinnedVersion")
            asset_name = ElidedLabel(THERMO_HELPER_SPECIFICATION.asset_name)
            asset_name.setObjectName("settingsAssetName")
            asset_name.setToolTip(THERMO_HELPER_SPECIFICATION.asset_name)
            pinned_layout.addWidget(version_pill)
            pinned_layout.addWidget(asset_name, 1)
            add_setting_row(thermo_form, "Pinned version", pinned_version)

            helper_path = ElidedLineEdit(
                str(self._settings.thermo.executable_path or "")
            )
            helper_path.setObjectName("settingsPathField")
            helper_path.setFixedHeight(40)
            helper_path.setPlaceholderText(
                "Optional. Leave empty to download the pinned version"
            )
            helper_path.setToolTip(helper_path.text())
            helper_path.textChanged.connect(helper_path.setToolTip)
            helper_editor = _path_editor(helper_path, dialog, True)
            helper_field = qt_widgets.QWidget()
            helper_field_layout = qt_widgets.QVBoxLayout(helper_field)
            helper_field_layout.setContentsMargins(0, 0, 0, 0)
            helper_field_layout.setSpacing(8)
            helper_field_layout.addWidget(helper_editor)
            helper_note = qt_widgets.QLabel(
                "Without a local executable, the pinned version is downloaded and "
                "its SHA-256 is verified before installation."
            )
            helper_note.setObjectName("settingsFieldNote")
            helper_note.setWordWrap(True)
            helper_field_layout.addWidget(helper_note)
            add_setting_row(thermo_form, "Local executable", helper_field)

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
                    helper_path,
                    size_edit,
                    age_edit,
                    theme_combo,
                    persist=persist,
                )

            reset_button.clicked.connect(
                lambda: self._reset_settings_dialog(
                    cache_edit,
                    report_edit,
                    helper_path,
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
                helper_path,
                helper_editor.findChild(qt_widgets.QPushButton),
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
            helper_path: Any,
            size_edit: Any,
            age_edit: Any,
            theme_combo: Any,
            persist: bool,
        ) -> None:
            nonlocal cache, current_settings
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
                    thermo=_thermo_settings(helper_path.text()),
                    theme_mode=str(theme_combo.currentData()),
                )
                if persist:
                    save_settings(updated, settings_path)
            except (ConfigurationError, OSError, ValueError) as error:
                qt_widgets.QMessageBox.critical(dialog, "Invalid settings", str(error))
                return
            self._settings = updated
            current_settings = updated
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
            helper_path: Any,
            size_edit: Any,
            age_edit: Any,
            theme_combo: Any,
        ) -> None:
            defaults = GuiSettings()
            cache_edit.setText(str(defaults.cache_directory))
            report_edit.setText(str(defaults.report_directory))
            helper_path.clear()
            size_edit.setText(str(defaults.min_size_mb))
            age_edit.setText(str(defaults.min_age_minutes))
            theme_combo.setCurrentIndex(0)

        def closeEvent(self, event: Any) -> None:
            if self._worker is not None:
                qt_widgets.QMessageBox.information(
                    self,
                    "Report in progress",
                    "Wait for the current report to finish before closing the "
                    "application.",
                )
                event.ignore()
                return
            self._workspace.cleanup()
            event.accept()

    workspace = ReportWorkspace()
    cache = TraceCache(settings.cache_directory)
    current_settings = settings
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
            "The GUI requires PySide6. Install it with `uv sync --extra gui`."
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


def _path_editor(line_edit: Any, dialog: Any, file_mode: bool) -> Any:
    """Add a browse button beside one settings path field."""
    qt_widgets = import_module("PySide6.QtWidgets")
    container = qt_widgets.QWidget(dialog)
    layout = qt_widgets.QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    button = qt_widgets.QPushButton("Browse")
    button.setObjectName("secondary")
    button.setFixedHeight(40)

    def browse() -> None:
        start_directory = _dialog_start_directory(line_edit.text())
        if file_mode:
            path, _ = qt_widgets.QFileDialog.getOpenFileName(
                dialog, "Choose executable", start_directory
            )
        else:
            path = qt_widgets.QFileDialog.getExistingDirectory(
                dialog, "Choose directory", start_directory
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


def _thermo_settings(executable: str) -> Any:
    """Build helper settings from the optional local executable field."""
    from rawtrace_qc.gui.config import ThermoToolSettings

    return ThermoToolSettings(
        executable_path=Path(executable.strip()) if executable.strip() else None
    )

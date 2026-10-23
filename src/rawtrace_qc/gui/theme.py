"""Semantic colors and Qt styling for the rawtrace-qc desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from string import Template
from typing import Any

_RESOURCES_DIRECTORY = Path(__file__).parent / "resources"


@dataclass(frozen=True)
class Theme:
    """Store semantic colors used to style the desktop interface."""

    name: str = "light"
    is_dark: bool = False
    chevron_down_icon: str = (
        _RESOURCES_DIRECTORY / "chevron-down-light.svg"
    ).as_posix()

    # Window and section surfaces
    window_background: str = "#f3f7f8"
    settings_dialog_background: str = "#EEF4F6"
    surface_background: str = "#ffffff"
    section_background: str = "#ffffff"
    card_background: str = "#ffffff"
    card_border: str = "#D5E1E6"
    badge_background: str = "#0F7C7A"
    badge_text: str = "#ffffff"
    title_text: str = "#063853"
    muted_text: str = "#4F6B79"
    mode_selector_background: str = "#E8F1F4"
    mode_option_inactive_text: str = "#063853"
    mode_option_hover: str = "#d8e7eb"
    mode_option_active_background: str = "#0F7C7A"
    mode_option_active_text: str = "#ffffff"
    dialog_primary_hover: str = "#0c6563"
    report_hint_text: str = "#4F6B79"

    # Input and standard button surfaces
    input_background: str = "#fbfdfd"
    button_background: str = "#E8F1F4"
    button_hover: str = "#d7ecec"
    button_disabled: str = "#E8F1F4"

    # Text colors
    text_primary: str = "#063853"
    text_muted: str = "#78909b"
    text_disabled: str = "#9eb1bb"
    placeholder_text: str = "#78909b"
    folder_input_border: str = "#AFC3CC"
    folder_input_placeholder: str = "#5E7886"

    # Secondary and outlined action button colors
    secondary_button_background: str = "#E8F1F4"
    secondary_button_border: str = "#AFC3CC"
    secondary_button_text: str = "#063853"
    secondary_button_hover: str = "#d8e7eb"
    count_pill_background: str = "#E3F4F3"
    count_pill_text: str = "#0B6563"
    destructive_button_background: str = "#ffffff"
    destructive_button_border: str = "#E3B3B0"
    destructive_button_text: str = "#B3261E"
    destructive_button_hover: str = "#FDF2F2"
    button_disabled_background: str = "#F3F8FA"
    button_disabled_border: str = "#D5E1E6"
    button_disabled_text: str = "#5A7483"
    outline_teal_button_background: str = "#ffffff"
    outline_teal_button_border: str = "#0F7C7A"
    outline_teal_button_text: str = "#0B6563"
    outline_teal_button_hover: str = "#E3F4F3"

    # Header and brand colors
    header_logo: str = (
        _RESOURCES_DIRECTORY / "perutz-ms-facility_logo-inverted.svg"
    ).as_posix()
    header_divider: str = "rgba(255, 255, 255, 0.25)"
    header_background: str = "#063853"
    header_title: str = "#ffffff"
    header_version: str = "#B7D2DE"
    accent: str = "#40B7B5"
    accent_hover: str = "#369c9a"
    accent_text: str = "#063853"

    # Primary action button colors
    primary_button: str = "#C62B2F"
    primary_button_hover: str = "#a92427"
    primary_button_text: str = "#ffffff"
    scan_button_background: str = "#E73C40"
    scan_button_hover: str = "#c92f34"

    # Borders and selection colors
    border: str = "#D5E1E6"
    border_input: str = "#bfd1d5"
    border_strong: str = "#b7cdd0"
    selection_background: str = "#40B7B5"
    selection_text: str = "#063853"
    list_divider: str = "#E3ECF0"
    list_selected_background: str = "#E6F1F6"
    list_selected_text: str = "#063853"
    drop_hint_border: str = "#AFC3CC"
    drop_hint_text: str = "#4F6B79"
    drop_hint_icon: str = "#0F7C7A"

    # Checkbox colors
    checkbox_border: str = "#063853"
    checkbox_background: str = "#ffffff"
    checkbox_check: str = "#0F7C7A"
    checkbox_mark: str = "#ffffff"

    # Scrollbar and splitter colors
    scrollbar_background: str = "#f3f7f8"
    scrollbar_handle: str = "#b7d9d9"
    splitter_handle: str = "#b7d9d9"

    # Section heading colors
    header_section_background: str = "#E8F1F4"
    header_section_text: str = "#063853"

    # Tooltip colors
    tooltip_background: str = "#063853"
    tooltip_text: str = "#ffffff"


LIGHT_THEME = Theme(name="light")
DARK_THEME = Theme(
    name="dark",
    chevron_down_icon=(_RESOURCES_DIRECTORY / "chevron-down-dark.svg").as_posix(),
    window_background="#12161a",
    surface_background="#1c2128",
    section_background="#1c2128",
    card_background="#1c2128",
    card_border="#30363d",
    settings_dialog_background="#12161a",
    badge_background="#0F7C7A",
    badge_text="#ffffff",
    title_text="#e6edf3",
    muted_text="#919ea8",
    mode_selector_background="#262c36",
    mode_option_inactive_text="#e6edf3",
    mode_option_hover="#323a46",
    mode_option_active_background="#0F7C7A",
    mode_option_active_text="#ffffff",
    dialog_primary_hover="#0c6563",
    report_hint_text="#919ea8",
    input_background="#171b21",
    button_background="#262c36",
    button_hover="#323a46",
    button_disabled="#1c2128",
    text_primary="#e6edf3",
    text_muted="#919ea8",
    text_disabled="#656f7d",
    placeholder_text="#76828f",
    folder_input_border="#444c56",
    folder_input_placeholder="#76828f",
    secondary_button_background="#262c36",
    secondary_button_border="#444c56",
    secondary_button_text="#e6edf3",
    secondary_button_hover="#323a46",
    count_pill_background="#1a3438",
    count_pill_text="#40B7B5",
    destructive_button_background="#1c2128",
    destructive_button_border="#7d3532",
    destructive_button_text="#f87171",
    destructive_button_hover="#3b1d1d",
    button_disabled_background="#1e242c",
    button_disabled_border="#30363d",
    button_disabled_text="#656f7d",
    outline_teal_button_background="#1c2128",
    outline_teal_button_border="#0F7C7A",
    outline_teal_button_text="#40B7B5",
    outline_teal_button_hover="#1b3a3c",
    header_logo=(
        _RESOURCES_DIRECTORY / "perutz-ms-facility_logo-inverted.svg"
    ).as_posix(),
    header_divider="rgba(255, 255, 255, 0.25)",
    header_background="#0b283b",
    header_title="#ffffff",
    header_version="#B7D2DE",
    accent="#40B7B5",
    accent_hover="#4ed1cf",
    accent_text="#063853",
    primary_button="#C62B2F",
    primary_button_hover="#d83438",
    primary_button_text="#ffffff",
    scan_button_background="#E73C40",
    scan_button_hover="#f04d51",
    border="#30363d",
    border_input="#444c56",
    border_strong="#485260",
    selection_background="#255d6e",
    selection_text="#ffffff",
    list_divider="#262c36",
    list_selected_background="#243542",
    list_selected_text="#e6edf3",
    drop_hint_border="#444c56",
    drop_hint_text="#919ea8",
    drop_hint_icon="#40B7B5",
    checkbox_border="#8b949e",
    checkbox_background="#171b21",
    checkbox_check="#0F7C7A",
    checkbox_mark="#ffffff",
    scrollbar_background="#12161a",
    scrollbar_handle="#363d47",
    splitter_handle="#363d47",
    header_section_background="#252b34",
    header_section_text="#e6edf3",
    tooltip_background="#2d333b",
    tooltip_text="#e6edf3",
    is_dark=True,
)

__all__ = [
    "DARK_THEME",
    "LIGHT_THEME",
    "Theme",
    "apply_theme",
    "generate_stylesheet",
    "get_active_theme",
    "resolve_theme",
]


_STYLESHEET = Template(
    """
QWidget {
    color: $text_primary;
}
QMainWindow, QDialog, QMessageBox {
    background: $window_background;
    color: $text_primary;
}
QDialog#settingsDialog {
    background: $settings_dialog_background;
}
QFrame#card, QFrame#section {
    background: $card_background;
    color: $text_primary;
    border: 1px solid $card_border;
    border-radius: 12px;
}
QLabel#cardBadge {
    background: $badge_background;
    color: $badge_text;
    border-radius: 11px;
    font-size: 12.5px;
    font-weight: 700;
}
QLabel#cardTitle {
    background: transparent;
    color: $title_text;
    font-size: 15px;
    font-weight: 600;
}
QLabel#settingsCardTitle {
    background: transparent;
    color: $title_text;
    font-size: 15px;
    font-weight: 600;
}
QLabel#settingsFormLabel {
    background: transparent;
    color: $title_text;
    font-size: 14px;
}
QLabel#fieldUnit {
    background: transparent;
    color: $muted_text;
    font-size: 13px;
}
QLabel#settingsAssetName, QLabel#settingsFieldNote {
    background: transparent;
    color: $muted_text;
    font-size: 12.5px;
}
QLabel#settingsAssetName {
    font-size: 13px;
}
QLabel#pinnedVersion {
    background: $count_pill_background;
    color: $count_pill_text;
    border: 0;
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 12.5px;
    font-weight: 600;
}
QLineEdit#settingsField, QLineEdit#settingsPathField, QComboBox#themeMode {
    background: $input_background;
    color: $text_primary;
    border: 1px solid $folder_input_border;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 14px;
    min-height: 40px;
    max-height: 40px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url($chevron_down_icon);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background: $surface_background;
    color: $text_primary;
    border: 1px solid $folder_input_border;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $list_selected_background;
    selection-color: $list_selected_text;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 32px;
    padding: 4px 10px;
    border-radius: 6px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: $list_selected_background;
    color: $list_selected_text;
}
QLineEdit#settingsPathField {
    font-size: 13.5px;
}
QLineEdit#settingsField:focus, QLineEdit#settingsPathField:focus,
QComboBox#themeMode:focus {
    border: 2px solid $mode_option_active_background;
}
QPushButton#secondary:focus {
    border: 2px solid $mode_option_active_background;
}
QDialog#settingsDialog QPushButton#secondary {
    padding: 0 18px;
}
QPushButton#textButton {
    background: transparent;
    color: $title_text;
    border: 0;
    border-radius: 0;
    padding: 0;
    font-size: 14px;
    font-weight: 600;
    text-decoration: underline;
}
QPushButton#textButton:hover {
    background: transparent;
    color: $title_text;
}
QPushButton#textButton:focus {
    border: 2px solid $mode_option_active_background;
    border-radius: 4px;
}
QPushButton#dialogPrimary {
    background: $mode_option_active_background;
    color: $primary_button_text;
    border: 0;
    border-radius: 8px;
    padding: 0 24px;
    font-size: 14px;
    font-weight: 700;
    min-height: 40px;
    max-height: 40px;
}
QPushButton#dialogPrimary:hover {
    background: $dialog_primary_hover;
    color: $primary_button_text;
}
QPushButton#dialogPrimary:focus {
    border: 2px solid $mode_option_active_background;
}
QLabel#statusLabel {
    background: transparent;
    color: $muted_text;
    font-size: 13.5px;
    border: 0;
}
QFrame#header {
    background: $header_background;
    color: $header_title;
    border: 0;
    border-radius: 12px;
}
QFrame#headerDivider {
    background-color: $header_divider;
    border: none;
    min-width: 1px;
    max-width: 1px;
    min-height: 32px;
    max-height: 32px;
}
QFrame#header QLabel {
    background: transparent;
    color: $header_title;
}
QLabel#appTitle {
    color: $header_title;
    font-size: 22px;
    font-weight: 700;
}
QLabel#muted {
    color: $text_muted;
}
QLabel#appVersion {
    color: $header_version;
    font-size: 12.5px;
}
QLabel#count, QLabel#subheading {
    color: $accent;
    font-weight: 700;
}
QLabel#countPill {
    background: $count_pill_background;
    color: $count_pill_text;
    border: 0;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 12.5px;
    font-weight: 600;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QListWidget, QTableWidget,
QPlainTextEdit, QTextEdit, QComboBox {
    background: $input_background;
    color: $text_primary;
    border: 1px solid $border_input;
    border-radius: 6px;
    padding: 6px;
    selection-background-color: $selection_background;
    selection-color: $selection_text;
}
QLineEdit {
    placeholder-text-color: $placeholder_text;
}
QLineEdit#folderInput {
    background: $input_background;
    color: $text_primary;
    border: 1px solid $folder_input_border;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 14px;
    placeholder-text-color: $folder_input_placeholder;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QListWidget:disabled, QTableWidget:disabled, QPlainTextEdit:disabled,
QTextEdit:disabled, QComboBox:disabled {
    background: $window_background;
    color: $text_disabled;
    border-color: $border;
}
QLineEdit#reportDirectoryInput {
    background: $input_background;
    color: $text_primary;
    border: 1px solid $folder_input_border;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 13.5px;
}
QLineEdit#reportDirectoryInput:disabled {
    background: $button_disabled_background;
    color: $button_disabled_text;
    border: 1px solid $button_disabled_border;
}
QLabel#reportHint {
    color: $report_hint_text;
    font-size: 12.5px;
}
QWidget#modeSelector {
    background: $mode_selector_background;
    border: 0;
    border-radius: 9px;
}
QToolButton#modeOption {
    background: transparent;
    color: $mode_option_inactive_text;
    border: 0;
    border-radius: 7px;
    padding: 0 16px;
    font-size: 14px;
    font-weight: 600;
    min-height: 34px;
    max-height: 34px;
}
QToolButton#modeOption:hover:!checked {
    background: $mode_option_hover;
    color: $mode_option_inactive_text;
}
QToolButton#modeOption:checked {
    background: $mode_option_active_background;
    color: $mode_option_active_text;
}
QToolButton:disabled {
    background: $button_background;
    color: $text_disabled;
}
QListWidget, QTableWidget {
    padding: 2px;
}
QListWidget#selectedList {
    background: $input_background;
    color: $text_primary;
    border: 1px solid $card_border;
    border-radius: 8px;
    padding: 0;
    font-size: 13.5px;
    selection-background-color: $list_selected_background;
    selection-color: $list_selected_text;
}
QPushButton, QToolButton {
    background: $button_background;
    color: $text_primary;
    border: 1px solid $border_strong;
    border-radius: 6px;
    padding: 8px 13px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: $button_hover;
    color: $text_primary;
    border-color: $accent;
}
QPushButton#secondary {
    background: $secondary_button_background;
    color: $secondary_button_text;
    border: 1px solid $secondary_button_border;
    border-radius: 8px;
    padding: 0 16px;
    font-size: 14px;
    font-weight: 600;
    min-height: 40px;
    max-height: 40px;
}
QPushButton#secondary:hover {
    background: $secondary_button_hover;
    color: $secondary_button_text;
    border-color: $secondary_button_border;
}
QPushButton#secondarySmall {
    background: $secondary_button_background;
    color: $secondary_button_text;
    border: 1px solid $secondary_button_border;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 600;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#secondarySmall:hover {
    background: $secondary_button_hover;
    color: $secondary_button_text;
    border-color: $secondary_button_border;
}
QPushButton#secondarySmall:disabled {
    background: $button_disabled_background;
    color: $button_disabled_text;
    border-color: $button_disabled_border;
}
QPushButton#destructiveOutline {
    background: $destructive_button_background;
    color: $destructive_button_text;
    border: 1px solid $destructive_button_border;
    border-radius: 8px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 600;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#destructiveOutline:hover {
    background: $destructive_button_hover;
    color: $destructive_button_text;
    border-color: $destructive_button_border;
}
QPushButton#destructiveOutline:disabled {
    background: $button_disabled_background;
    color: $button_disabled_text;
    border-color: $button_disabled_border;
}
QFrame#headerDivider {
    background: $card_border;
    border: 0;
    margin: 0 6px;
}
QPushButton#outlineTeal {
    background: $outline_teal_button_background;
    color: $outline_teal_button_text;
    border: 1.5px solid $outline_teal_button_border;
    border-radius: 8px;
    padding: 0 18px;
    font-size: 14px;
    font-weight: 600;
    min-height: 40px;
    max-height: 40px;
}
QPushButton#outlineTeal:hover {
    background: $outline_teal_button_hover;
    color: $outline_teal_button_text;
    border-color: $outline_teal_button_border;
}
QPushButton#secondary:disabled, QPushButton#outlineTeal:disabled {
    background: $button_disabled;
    color: $text_disabled;
    border-color: $border;
}
QPushButton#headerSettings {
    background: transparent;
    color: $header_title;
    border: 1px solid rgba(255, 255, 255, 0.35);
    border-radius: 8px;
    padding: 0;
}
QPushButton#headerSettings:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: $header_title;
}
QPushButton#headerSettings:pressed {
    background: rgba(255, 255, 255, 0.2);
    border-color: $header_title;
}
QPushButton:disabled, QToolButton:disabled {
    background: $button_disabled;
    color: $text_disabled;
    border-color: $border;
}
QPushButton#primary {
    background: $scan_button_background;
    color: $primary_button_text;
    border-color: $scan_button_background;
}
QPushButton#primary:hover {
    background: $scan_button_hover;
    color: $primary_button_text;
    border-color: $scan_button_hover;
}
QPushButton#primary:disabled {
    background: $button_disabled;
    color: $text_disabled;
    border-color: $border;
}
QPushButton#primaryButton {
    background: $primary_button;
    color: $primary_button_text;
    border: 0;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 700;
    padding: 0 26px;
    min-height: 44px;
    max-height: 44px;
}
QPushButton#primaryButton:hover {
    background: $primary_button_hover;
    color: $primary_button_text;
}
QPushButton#primaryButton:disabled {
    background: $button_disabled;
    color: $text_disabled;
}
QCheckBox {
    background: transparent;
    color: $text_primary;
    spacing: 7px;
    font-size: 13.5px;
}
QCheckBox:disabled {
    background: transparent;
    color: $text_disabled;
}
QCheckBox::indicator {
    background: $checkbox_background;
    color: $checkbox_check;
    border: 1px solid $checkbox_border;
    border-radius: 3px;
    width: 16px;
    height: 16px;
}
QCheckBox::indicator:checked {
    background: $checkbox_check;
    color: $checkbox_mark;
    border-color: $checkbox_check;
}
QCheckBox::indicator:disabled {
    background: $window_background;
    color: $text_disabled;
    border-color: $border;
}
QHeaderView::section {
    background: $header_section_background;
    color: $header_section_text;
    border: 0;
    font-weight: 700;
    padding: 7px;
}
QTableWidget QTableCornerButton::section {
    background: $header_section_background;
    color: $header_section_text;
    border: 0;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: $scrollbar_background;
    color: $text_primary;
    border: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: $scrollbar_handle;
    color: $text_primary;
    border: 0;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: $scrollbar_background;
    color: $text_primary;
    border: 0;
}
QSplitter::handle {
    background: $splitter_handle;
    color: $text_primary;
    height: 5px;
}
QToolTip {
    background: $tooltip_background;
    color: $tooltip_text;
    border: 1px solid $border_strong;
}
"""
)

_active_theme = LIGHT_THEME


def resolve_theme(mode: str, qt_gui: Any | None = None) -> Theme:
    """Resolve a configured theme mode to its semantic colors.

    Args:
        mode: Theme selection. Must be `system`, `light`, or `dark`.
        qt_gui: Optional loaded `PySide6.QtGui` module. If None (default), QtGui
            is imported when available.

    Returns:
        The light or dark theme matching the selection. System mode falls back
        to the light theme when Qt cannot provide a color scheme.

    Raises:
        ValueError: If `mode` is not a supported theme selection.
    """
    if mode not in ["light", "dark", "system"]:
        raise ValueError(
            f"Invalid theme mode {mode!r}. Must be one of 'system', 'light', or 'dark'."
        )

    if mode == "light":
        return LIGHT_THEME
    if mode == "dark":
        return DARK_THEME

    if qt_gui is None:
        try:
            qt_gui = import_module("PySide6.QtGui")
        except ImportError:
            return LIGHT_THEME
    application_type = getattr(qt_gui, "QGuiApplication", None)
    if application_type is None:
        return LIGHT_THEME
    try:
        application = application_type.instance()
        style_hints = (
            application.styleHints()
            if application is not None
            else application_type.styleHints()
        )
        color_scheme = style_hints.colorScheme()
        qt_core = import_module("PySide6.QtCore")
        scheme_type = getattr(qt_core.Qt, "ColorScheme", None)
        dark_scheme = getattr(scheme_type, "Dark", None)
    except (AttributeError, ImportError, RuntimeError, TypeError):
        return LIGHT_THEME
    return (
        DARK_THEME
        if dark_scheme is not None and color_scheme == dark_scheme
        else LIGHT_THEME
    )


def generate_stylesheet(theme: Theme) -> str:
    """Generate a Qt stylesheet from semantic theme colors.

    Args:
        theme: Theme whose color tokens should replace stylesheet placeholders.

    Returns:
        A complete Qt stylesheet with all theme placeholders resolved.
    """
    return _STYLESHEET.substitute(
        {field: getattr(theme, field) for field in Theme.__dataclass_fields__}
    )


def apply_theme(app_or_window: Any, theme: Theme, qt_gui: Any | None = None) -> None:
    """Apply a stylesheet and matching palette to a Qt application or widget.

    Args:
        app_or_window: Qt application or widget receiving the theme.
        theme: Semantic colors to apply.
        qt_gui: Optional loaded `PySide6.QtGui` module. If None (default), QtGui
            is imported when available.
    """
    global _active_theme
    _active_theme = theme
    app_or_window.setStyleSheet(generate_stylesheet(theme))
    if qt_gui is None:
        try:
            qt_gui = import_module("PySide6.QtGui")
        except ImportError:
            return

    palette_type = getattr(qt_gui, "QPalette", None)
    color_type = getattr(qt_gui, "QColor", None)
    if palette_type is not None and color_type is not None:
        palette = palette_type()
        roles = getattr(palette_type, "ColorRole", palette_type)
        active_role_colors = {
            "Window": theme.window_background,
            "WindowText": theme.text_primary,
            "Base": theme.input_background,
            "AlternateBase": theme.surface_background,
            "Text": theme.text_primary,
            "Button": theme.button_background,
            "ButtonText": theme.text_primary,
            "Highlight": theme.selection_background,
            "HighlightedText": theme.selection_text,
            "PlaceholderText": theme.placeholder_text,
            "ToolTipBase": theme.tooltip_background,
            "ToolTipText": theme.tooltip_text,
            "Light": theme.surface_background,
            "Mid": theme.border_strong,
            "Dark": theme.border,
        }
        disabled_role_colors = {
            **active_role_colors,
            "WindowText": theme.text_muted,
            "Base": theme.window_background,
            "Text": theme.text_disabled,
            "ButtonText": theme.text_disabled,
            "PlaceholderText": theme.text_disabled,
        }
        groups = getattr(palette_type, "ColorGroup", None)
        active = getattr(groups, "Active", None)
        inactive = getattr(groups, "Inactive", None)
        disabled = getattr(groups, "Disabled", None)
        for group in (active, inactive, disabled):
            colors = disabled_role_colors if group == disabled else active_role_colors
            for role_name, color in colors.items():
                role = getattr(roles, role_name, None)
                if role is not None:
                    if group is None:
                        palette.setColor(role, color_type(color))
                    else:
                        palette.setColor(group, role, color_type(color))
        app_or_window.setPalette(palette)


def get_active_theme() -> Theme:
    """Return the theme most recently applied to a Qt target."""
    return _active_theme

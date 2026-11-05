"""Render processed trace tables as a multi-tab interactive HTML report."""

from __future__ import annotations

import json
from collections.abc import Sequence
from html import escape
from pathlib import Path

from plotly.offline import get_plotlyjs, get_plotlyjs_version

from rawtrace_qc.processing.models import ProcessedTable
from rawtrace_qc.report.models import ReportDocument, ReportOptions
from rawtrace_qc.report.prepare import build_report


def write_html(
    processed_tables: Sequence[ProcessedTable],
    output_path: Path,
    *,
    options: ReportOptions | None = None,
) -> Path:
    """Create a multi-tab HTML report from processed tables.

    Args:
        processed_tables: Report-ready tables to include in the report.
        output_path: Destination HTML path. Parent directories are created when
            necessary.
        options: Report configuration. If None (default), uses all available
            channels and the default metadata fields.

    Returns:
        The resolved output path.

    Raises:
        ConfigurationError: If report options or requested channels are invalid.
        ReportError: If a processed table cannot be serialized for reporting.
    """
    report = build_report(processed_tables, options=options)
    resolved_path = output_path.expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(_render_document(report), encoding="utf-8")
    return resolved_path


def render_html(
    processed_tables: Sequence[ProcessedTable],
    *,
    options: ReportOptions | None = None,
) -> str:
    """Render processed tables to an HTML string without writing a file.

    Args:
        processed_tables: Report-ready tables to include in the report.
        options: Report configuration. If None (default), uses all available
            channels and the default metadata fields.

    Returns:
        A complete HTML document.
    """
    return _render_document(build_report(processed_tables, options=options))


def _render_document(report: ReportDocument) -> str:
    tabs = _render_tabs(report)
    plot_panel = _render_plot_panel(report)
    metadata_panel = _render_metadata_panel(report)
    plotly_asset = _plotly_asset(report)
    payload = _safe_json(_report_payload(report))
    active_panel = "plot-panel" if report.channels else "metadata-panel"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(report.title)}</title>
  {_css()}
</head>
<body>
  <div class="report-shell">
    <header class="report-header">
      <h1>{escape(report.title)}</h1>
      <p>{_file_count_label(report)}</p>
    </header>
    <nav class="report-tabs" role="tablist" aria-label="Report views">
      {tabs}
    </nav>
    <main>
      {plot_panel}
      {metadata_panel}
    </main>
  </div>
  <script id="rawtrace-report-data" type="application/json">{payload}</script>
  {plotly_asset}
  <script>
    {_javascript(active_panel)}
  </script>
</body>
</html>
"""


def _file_count_label(report: ReportDocument) -> str:
    file_count = len({trace.source_key for trace in report.traces})
    return f"{file_count} file" if file_count == 1 else f"{file_count} files"


def _render_tabs(report: ReportDocument) -> str:
    buttons: list[str] = []
    for index, channel in enumerate(report.channels):
        active = index == 0
        buttons.append(
            _tab_button(
                label=channel.label,
                panel="plot-panel",
                channel=channel.key,
                active=active,
            )
        )
    buttons.append(
        _tab_button(
            label="Metadata",
            panel="metadata-panel",
            channel=None,
            active=not report.channels,
        )
    )
    return "\n      ".join(buttons)


def _tab_button(
    *,
    label: str,
    panel: str,
    channel: str | None,
    active: bool,
) -> str:
    channel_attribute = (
        "" if channel is None else f' data-channel="{escape(channel, quote=True)}"'
    )
    selected = "true" if active else "false"
    classes = "report-tab is-active" if active else "report-tab"
    return (
        f'<button class="{classes}" type="button" role="tab" '
        f'aria-selected="{selected}" data-panel="{panel}"{channel_attribute}>'
        f"{escape(label)}</button>"
    )


def _render_plot_panel(report: ReportDocument) -> str:
    if not report.channels:
        return ""
    ms_options = "".join(
        f'<option value="{level}">MS{level}</option>'
        for level in report.available_ms_levels
    )
    controls = f"""
      <div class="report-toolbar">
        <label class="report-control-ms">
          MS level <select id="report-ms-level">{ms_options}</select>
        </label>
        {_render_faims_control(report)}
        <label class="report-control-view">View <select id="report-view">
          <option value="overlay">Overlay</option>
          <option value="stacked">Stacked</option>
          <option value="pairwise">Pairwise</option>
        </select></label>
        <label>Reference trace <select id="report-reference">
          <option value="">None</option>
        </select></label>
        <div id="report-selected-traces-control" class="report-picker">
          <button
            id="report-selected-traces-toggle"
            class="report-picker-toggle"
            type="button"
            aria-haspopup="dialog"
            aria-expanded="false"
            aria-controls="report-selected-traces-menu"
          >Selected traces <span id="report-selected-traces-count">All</span></button>
          <div
            id="report-selected-traces-menu"
            class="report-picker-menu"
            role="dialog"
            aria-label="Select traces to display"
            hidden
          >
            <div class="report-picker-actions">
              <button id="report-select-all" type="button">Select all</button>
              <button id="report-select-none" type="button">Select none</button>
            </div>
            <div
              id="report-selected-traces-options"
              class="report-picker-options"
              role="group"
              aria-label="Available traces"
            ></div>
          </div>
        </div>
        <div id="report-pairwise-control" class="report-pairwise-control" hidden>
          <label>Comparison trace <select id="report-comparison-trace">
            <option value="">Select a reference first</option>
          </select></label>
          <div class="report-pairwise-buttons">
            <button
              id="report-previous-trace"
              class="report-pairwise-button"
              type="button"
              title="Previous trace"
              aria-label="Previous trace"
            >&larr;</button>
            <button
              id="report-next-trace"
              class="report-pairwise-button"
              type="button"
              title="Next trace"
              aria-label="Next trace"
            >&rarr;</button>
          </div>
        </div>
      </div>
      <div id="report-plot-shell" class="report-plot-shell">
        <div class="report-plot-actions">
          <button
            id="report-fullscreen-toggle"
            class="report-fullscreen-toggle"
            type="button"
            aria-controls="report-plot-shell"
            aria-label="Enter fullscreen plot"
            aria-pressed="false"
            title="Enter fullscreen plot"
          ><span aria-hidden="true">&#x26F6;</span></button>
        </div>
        <div id="report-plot" role="img" aria-label="Chromatogram plot"></div>
      </div>
"""
    return (
        '<section id="plot-panel" class="report-panel" role="tabpanel">'
        f"{controls}</section>"
    )


def _render_faims_control(report: ReportDocument) -> str:
    if not report.available_faims_values:
        return ""
    options = '<option value="all">All CVs</option>' + "".join(
        f'<option value="{escape(str(value), quote=True)}">'
        f"CV {escape(_display_faims_value(value))}</option>"
        for value in report.available_faims_values
    )
    return f'<label>FAIMS CV <select id="report-faims">{options}</select></label>'


def _render_metadata_panel(report: ReportDocument) -> str:
    if not report.metadata_rows:
        content = '<p class="empty-state">No processed tables were supplied.</p>'
    else:
        headers = "".join(
            f'<th scope="col" aria-sort="none">'
            f'<button type="button" class="metadata-sort-button" '
            f'data-sort-field="{escape(field, quote=True)}" '
            f'aria-label="Sort by {escape(_field_label(field), quote=True)}">'
            f"<span>{escape(_field_label(field))}</span>"
            '<span class="metadata-sort-indicator" aria-hidden="true"></span>'
            "</button></th>"
            for field in report.metadata_fields
        )
        rows = [
            (
                f'<tr data-table-index="{row_index}">'
                + "".join(
                    "<td>" + escape(_display_metadata_value(value)) + "</td>"
                    for _, value in row.values
                )
                + "</tr>"
            )
            for row_index, row in enumerate(report.metadata_rows)
        ]
        content = (
            '<div class="metadata-table-wrap"><table class="metadata-table">'
            f"<thead><tr>{headers}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return (
        '<section id="metadata-panel" class="report-panel" role="tabpanel">'
        f"{content}</section>"
    )


def _plotly_asset(report: ReportDocument) -> str:
    if not report.channels:
        return ""
    if report.asset_mode.value == "cdn":
        return (
            f'<script src="https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js">'
            "</script>"
        )
    return f"<script>{get_plotlyjs()}</script>"


def _report_payload(report: ReportDocument) -> dict[str, object]:
    return {
        "initial_channel": report.initial_channel,
        "initial_view": report.initial_view.value,
        "available_ms_levels": list(report.available_ms_levels),
        "channels": {
            channel.key: {
                "label": channel.label,
                "y_axis_title": channel.y_axis_title,
            }
            for channel in report.channels
        },
        "available_faims_values": list(report.available_faims_values),
        "metadata_rows": [
            {
                "table_index": row_index,
                "values": {field: value for field, value in row.values},
            }
            for row_index, row in enumerate(report.metadata_rows)
        ],
        "traces": [
            {
                "table_index": trace.table_index,
                "name": trace.name,
                "source_key": trace.source_key,
                "ms_level": trace.ms_level,
                "faims_cv": trace.faims_cv,
                "color_index": trace.color_index,
                "retention_time_min": list(trace.retention_time_min),
                "channels": {
                    channel: list(values) for channel, values in trace.channels
                },
            }
            for trace in report.traces
        ],
    }


def _safe_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    return (
        serialized.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _display_metadata_value(value: object) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, tuple):
        return ", ".join(value) or "None"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _display_faims_value(value: float | str) -> str:
    if isinstance(value, float):
        return f"{value:+g} V"
    return value


def _field_label(field_name: str) -> str:
    labels = {
        "ms_level": "MS level",
        "ms_level_file": "MS file",
        "faims_cv": "FAIMS CV",
        "rawfile_name": "Raw file",
        "row_granularity": "Row granularity",
        "time_unit": "Time unit",
        "source_id": "Source ID",
    }
    return labels.get(field_name, field_name.replace("_", " ").title())


def _css() -> str:
    return """<style>
    :root {
      color-scheme: light;
      --facility-blue: #063853;
      --facility-teal: #40B7B5;
      --facility-red: #E73C40;
      --ink: #163342;
      --muted: #5f747e;
      --line: #d3e1e5;
      --surface: #ffffff;
      --surface-raised: #f8fbfb;
      --canvas: #edf4f5;
      --accent: #0e6f76;
      --accent-soft: #e4f5f4;
      --focus: rgba(64, 183, 181, .42);
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body {
      margin: 0;
      min-width: 320px;
      background: var(--canvas);
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      line-height: 1.45;
    }
    .report-shell { min-height: 100vh; }
    .report-header {
      padding: 32px clamp(18px, 4vw, 56px) 25px;
      background: linear-gradient(120deg, var(--facility-blue), #0a506b 68%, #146d79);
      color: var(--surface);
      border-top: 4px solid var(--facility-teal);
      border-bottom: 2px solid var(--facility-red);
      box-shadow: 0 3px 10px rgba(6, 56, 83, .12);
    }
    .report-header h1 {
      margin: 0;
      font-family: "Aptos Display", "Aptos", "Segoe UI", sans-serif;
      font-size: 32px;
      line-height: 1.1;
      font-weight: 700;
      letter-spacing: 0;
    }
    .report-header p {
      margin: 10px 0 0;
      color: #d8ebee;
      font-size: 13px;
      font-weight: 500;
    }
    .report-tabs {
      display: flex;
      gap: 2px;
      padding: 0 clamp(18px, 4vw, 56px);
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      overflow-x: auto;
      position: sticky;
      top: 0;
      z-index: 10;
      box-shadow: 0 2px 8px rgba(6, 56, 83, .08);
    }
    .report-tab {
      min-height: 48px;
      border: 0;
      border-bottom: 3px solid transparent;
      padding: 13px 16px 11px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font: 600 13px "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      white-space: nowrap;
      transition: color .15s ease, background-color .15s ease, border-color .15s ease;
    }
    .report-tab:hover {
      background: var(--accent-soft);
      color: var(--facility-blue);
    }
    .report-tab.is-active {
      border-bottom-color: var(--facility-teal);
      color: var(--facility-blue);
      background: linear-gradient(to bottom, var(--surface), #f4fbfb);
    }
    .report-tab:focus-visible,
    .metadata-sort-button:focus-visible,
    .report-toolbar select:focus-visible,
    .report-toolbar button:focus-visible,
    .report-fullscreen-toggle:focus-visible {
      outline: 3px solid var(--focus);
      outline-offset: 2px;
    }
    .report-panel {
      max-width: 1680px;
      margin: 0 auto;
      padding: 24px clamp(18px, 4vw, 56px) 48px;
    }
    .report-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 20px;
      align-items: center;
      margin-bottom: 16px;
      padding: 11px 13px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-left: 4px solid var(--facility-teal);
      border-radius: 6px;
      box-shadow: 0 2px 8px rgba(6, 56, 83, .06);
      color: var(--facility-blue);
      font-size: 12px;
      font-weight: 600;
    }
    .report-toolbar label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .report-toolbar select {
      min-height: 34px;
      border: 1px solid #b9ccd2;
      border-radius: 4px;
      padding: 6px 30px 6px 10px;
      background: var(--surface);
      color: var(--facility-blue);
      cursor: pointer;
      font: 600 13px "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
    }
    .report-toolbar select:hover {
      border-color: var(--accent);
      background: var(--surface-raised);
    }
    .report-control-ms select {
      width: 72px;
      padding-right: 22px;
    }
    .report-control-view select {
      width: 92px;
      padding-right: 22px;
    }
    .report-toolbar select:disabled,
    .report-toolbar button:disabled {
      cursor: not-allowed;
      opacity: .55;
    }
    .report-toolbar button {
      min-height: 34px;
      border: 1px solid #b9ccd2;
      border-radius: 4px;
      padding: 6px 10px;
      background: var(--surface);
      color: var(--facility-blue);
      cursor: pointer;
      font: 600 13px "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
    }
    .report-toolbar button:hover:not(:disabled) {
      border-color: var(--accent);
      background: var(--surface-raised);
    }
    .report-picker {
      position: relative;
    }
    .report-picker-toggle {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }
    .report-picker-toggle span {
      color: var(--muted);
      font-size: 12px;
    }
    .report-picker-menu {
      position: absolute;
      top: calc(100% + 7px);
      left: 0;
      z-index: 20;
      width: max-content;
      min-width: min(320px, calc(100vw - 36px));
      max-width: calc(100vw - 36px);
      padding: 10px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 8px 24px rgba(6, 56, 83, .16);
    }
    .report-picker-actions {
      display: flex;
      gap: 8px;
      padding-bottom: 9px;
      border-bottom: 1px solid var(--line);
    }
    .report-picker-actions button {
      min-height: 30px;
      padding: 5px 8px;
      font-size: 12px;
    }
    .report-picker-options {
      max-height: 280px;
      overflow: auto;
      scrollbar-gutter: stable;
      padding-top: 6px;
    }
    .report-toolbar .report-picker-option {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 7px 6px;
      border-radius: 4px;
      color: var(--ink);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
    }
    .report-picker-option:hover { background: var(--accent-soft); }
    .report-picker-option input {
      flex: 0 0 auto;
      margin: 2px 0 0;
      accent-color: var(--facility-teal);
    }
    .report-picker-empty {
      padding: 8px 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .report-pairwise-control {
      display: inline-flex;
      align-items: center;
      gap: 10px;
    }
    .report-pairwise-control > label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .report-pairwise-buttons {
      display: inline-flex;
      gap: 6px;
    }
    .report-pairwise-button {
      width: 34px;
      padding: 4px 6px;
      font-size: 19px !important;
      line-height: 1;
    }
    .report-plot-shell {
      width: 100%;
      min-height: 560px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 3px 12px rgba(6, 56, 83, .08);
      overflow: hidden;
    }
    .report-plot-shell.is-stacked {
      min-height: min(560px, calc(100vh - 190px));
      max-height: min(720px, calc(100vh - 190px));
      overflow-x: hidden;
      overflow-y: auto;
    }
    .report-plot-actions {
      display: flex;
      justify-content: flex-end;
      min-height: 45px;
      padding: 10px 10px 0;
      background: var(--surface);
    }
    .report-fullscreen-toggle {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      min-height: 34px;
      border: 1px solid #b9ccd2;
      border-radius: 4px;
      padding: 6px;
      background: rgba(255, 255, 255, .94);
      color: var(--facility-blue);
      cursor: pointer;
      font: 600 13px "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      box-shadow: 0 2px 8px rgba(6, 56, 83, .12);
    }
    .report-fullscreen-toggle span {
      font-size: 20px;
      line-height: 1;
    }
    .report-fullscreen-toggle:hover:not(:disabled) {
      border-color: var(--accent);
      background: var(--surface-raised);
    }
    .report-fullscreen-toggle:disabled {
      cursor: not-allowed;
      opacity: .55;
    }
    #report-plot {
      width: 100%;
      min-height: 560px;
      background: var(--surface);
    }
    .report-plot-shell:fullscreen,
    .report-plot-shell:-webkit-full-screen {
      width: 100vw;
      height: 100vh;
      min-height: 0;
      max-height: none;
      max-width: none;
      margin: 0;
      padding: 12px;
      background: var(--canvas);
      border: 0;
      border-radius: 0;
      box-shadow: none;
      overflow: auto;
    }
    .report-plot-shell:fullscreen #report-plot,
    .report-plot-shell:-webkit-full-screen #report-plot {
      border: 0;
      border-radius: 0;
      box-shadow: none;
    }
    #report-plot .modebar { top: 8px !important; right: 8px !important; }
    .metadata-table-wrap {
      overflow-x: auto;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      box-shadow: 0 3px 12px rgba(6, 56, 83, .07);
    }
    .metadata-table {
      width: 100%;
      min-width: 720px;
      border-collapse: collapse;
      font: 13px "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      font-variant-numeric: tabular-nums;
    }
    .metadata-table th, .metadata-table td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    .metadata-table th {
      background: var(--facility-blue);
      border-bottom: 3px solid var(--facility-teal);
      color: #ffffff;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .metadata-sort-button {
      display: inline-flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      width: 100%;
      border: 0;
      padding: 0;
      background: transparent;
      color: inherit;
      cursor: pointer;
      font: inherit;
      line-height: inherit;
      text-align: left;
      text-transform: inherit;
    }
    .metadata-sort-button:hover { color: #d8ebee; }
    .metadata-sort-indicator {
      min-width: 2.5em;
      color: var(--facility-teal);
      font-size: 10px;
      text-align: right;
    }
    .metadata-table tbody tr:nth-child(even) td { background: var(--surface-raised); }
    .metadata-table tbody tr:hover td { background: #eef9f8; }
    .metadata-table tr:last-child td { border-bottom: 0; }
    .empty-state {
      margin: 0;
      padding: 42px 18px;
      background: var(--surface);
      border: 1px dashed #b9ccd2;
      border-radius: 6px;
      color: var(--muted);
      font-size: 14px;
      text-align: center;
    }
    @media (max-width: 640px) {
      .report-header { padding: 24px 16px 20px; }
      .report-header h1 { font-size: 26px; }
      .report-tabs { padding: 0 12px; }
      .report-tab { padding-inline: 13px; }
      .report-panel { padding: 16px 12px 30px; }
      .report-toolbar { align-items: stretch; padding: 12px; }
      .report-toolbar label { flex: 1 1 160px; justify-content: space-between; }
      .report-toolbar select { flex: 1; }
      .report-control-ms select,
      .report-control-view select { width: auto; }
      .report-picker { flex: 1 1 160px; }
      .report-picker-toggle { width: 100%; justify-content: space-between; }
      .report-pairwise-control { flex: 1 1 260px; }
      .report-pairwise-control > label { flex: 1; justify-content: space-between; }
      .report-plot-shell { min-height: 420px; }
      #report-plot { min-height: 420px; }
      .metadata-table { min-width: 640px; }
    }
    </style>"""


def _javascript(active_panel: str) -> str:
    return f"""
    (function () {{
      var data = JSON.parse(
        document.getElementById('rawtrace-report-data').textContent
      );
      var metadataTable = document.querySelector('.metadata-table');
      var metadataBody = metadataTable
        ? metadataTable.querySelector('tbody')
        : null;
      var sortButtons = metadataTable
        ? metadataTable.querySelectorAll('.metadata-sort-button')
        : [];
      var metadataByTableIndex = {{}};
      (data.metadata_rows || []).forEach(function (row) {{
        metadataByTableIndex[row.table_index] = row.values || {{}};
      }});
      var plot = document.getElementById('report-plot');
      var plotShell = document.getElementById('report-plot-shell');
      var fullscreenToggle = document.getElementById(
        'report-fullscreen-toggle'
      );
      var palette = [
        '#063853', '#40B7B5', '#E69F00', '#56B4E9',
        '#009E73', '#7F1D1D', '#CC79A7', '#885ba6',
        '#8C6D31', '#6C757D'
      ];
      var REFERENCE_COLOR = '#E73C40';
      var NORMAL_PLOT_HEIGHT = 560;
      var STACKED_TRACE_HEIGHT = 280;
      var RETENTION_TIME_TITLE = 'Retention time (min)';
      var LEGEND_GAP_PX = 78;
      var LEGEND_BOTTOM_PADDING_PX = 12;
      var DEFAULT_BOTTOM_MARGIN_PX = 160;
      var NO_LEGEND_BOTTOM_MARGIN_PX = 64;
      var PAIRWISE_TOP_MARGIN_PX = 100;
      var state = {{
        channel: data.initial_channel,
        msLevel: data.available_ms_levels.length
          ? data.available_ms_levels[0]
          : null,
        cv: 'all',
        view: data.initial_view,
        referenceTrace: null,
        selectedTraceIndices: null,
        comparisonTrace: null,
        legendHeight: 59,
        sorts: [
          {{field: 'acquisition_start_time', direction: 1}},
          {{field: 'rawfile_name', direction: 1}}
        ]
      }};
      var reference = document.getElementById('report-reference');
      var selectedControl = document.getElementById(
        'report-selected-traces-control'
      );
      var selectedToggle = document.getElementById(
        'report-selected-traces-toggle'
      );
      var selectedMenu = document.getElementById('report-selected-traces-menu');
      var selectedOptions = document.getElementById(
        'report-selected-traces-options'
      );
      var selectedCountLabel = document.getElementById(
        'report-selected-traces-count'
      );
      var selectAll = document.getElementById('report-select-all');
      var selectNone = document.getElementById('report-select-none');
      var pairwiseControl = document.getElementById('report-pairwise-control');
      var comparison = document.getElementById('report-comparison-trace');
      var previousTrace = document.getElementById('report-previous-trace');
      var nextTrace = document.getElementById('report-next-trace');

      function sameCv(left, right) {{
        if (typeof left === 'number') return Number(right) === left;
        return String(left) === String(right);
      }}
      function compareMetadataValues(left, right) {{
        var leftMissing = left === null || left === undefined
          || typeof left === 'string' && !left.trim();
        var rightMissing = right === null || right === undefined
          || typeof right === 'string' && !right.trim();
        if (leftMissing || rightMissing) {{
          if (leftMissing && rightMissing) return 0;
          return leftMissing ? 1 : -1;
        }}
        if (Array.isArray(left)) left = left.join(', ') || 'None';
        if (Array.isArray(right)) right = right.join(', ') || 'None';
        if (typeof left === 'number' && typeof right === 'number') {{
          return left < right ? -1 : left > right ? 1 : 0;
        }}
        return String(left).localeCompare(String(right), undefined, {{
          numeric: true,
          sensitivity: 'base'
        }});
      }}
      function sortedTraces() {{
        var traces = data.traces.slice();
        if (!state.sorts.length) return traces;
        return traces.sort(function (left, right) {{
          var leftValues = metadataByTableIndex[left.table_index] || {{}};
          var rightValues = metadataByTableIndex[right.table_index] || {{}};
          for (var index = 0; index < state.sorts.length; index += 1) {{
            var sort = state.sorts[index];
            var result = compareMetadataValues(
              leftValues[sort.field],
              rightValues[sort.field]
            );
            if (result !== 0) return result * sort.direction;
          }}
          return left.table_index - right.table_index;
        }});
      }}
      function updateMetadataRows() {{
        if (!metadataBody) return;
        var rowsByIndex = {{}};
        metadataBody.querySelectorAll('tr[data-table-index]').forEach(
          function (row) {{
            rowsByIndex[row.dataset.tableIndex] = row;
          }}
        );
        sortedTraces().forEach(function (trace) {{
          var row = rowsByIndex[String(trace.table_index)];
          if (row) metadataBody.appendChild(row);
        }});
      }}
      function updateSortIndicators() {{
        sortButtons.forEach(function (button) {{
          var field = button.dataset.sortField;
          var sortIndex = state.sorts.findIndex(function (item) {{
            return item.field === field;
          }});
          var header = button.closest('th');
          var indicator = button.querySelector('.metadata-sort-indicator');
          var label = button.firstElementChild
            ? button.firstElementChild.textContent
            : 'column';
          if (sortIndex === -1) {{
            if (header) header.setAttribute('aria-sort', 'none');
            if (indicator) indicator.textContent = '';
            button.setAttribute('aria-label', 'Sort by ' + label);
            return;
          }}
          var sort = state.sorts[sortIndex];
          var directionLabel = sort.direction === 1 ? 'ascending' : 'descending';
          if (header) header.setAttribute('aria-sort', directionLabel);
          if (indicator) {{
            var symbol = sort.direction === 1
              ? String.fromCharCode(9650)
              : String.fromCharCode(9660);
            indicator.textContent = String(sortIndex + 1) + ' ' + symbol;
          }}
          button.setAttribute(
            'aria-label',
            'Sort by ' + label + ' ' + directionLabel
              + ', priority ' + String(sortIndex + 1)
          );
        }});
      }}
      function cycleMetadataSort(field) {{
        var sortIndex = state.sorts.findIndex(function (item) {{
          return item.field === field;
        }});
        if (sortIndex === -1) {{
          state.sorts.push({{field: field, direction: 1}});
        }} else if (state.sorts[sortIndex].direction === 1) {{
          state.sorts[sortIndex].direction = -1;
        }} else {{
          state.sorts.splice(sortIndex, 1);
        }}
        render();
      }}
      function isVisible(trace) {{
        if (state.msLevel !== null && trace.ms_level !== state.msLevel) return false;
        if (trace.faims_cv === null || trace.faims_cv === undefined) return true;
        return state.cv === 'all' || sameCv(trace.faims_cv, state.cv);
      }}
      function activeTraces() {{
        return sortedTraces().filter(isVisible).filter(function (trace) {{
          return trace.channels[state.channel] !== undefined;
        }});
      }}
      function selectableTraces(active) {{
        return active.filter(function (trace) {{
          return trace.table_index !== state.referenceTrace;
        }});
      }}
      function isSelectedTrace(trace) {{
        return trace.table_index === state.referenceTrace
          || state.selectedTraceIndices === null
          || state.selectedTraceIndices.has(trace.table_index);
      }}
      function selectedDisplayTraces(active) {{
        return active.filter(isSelectedTrace);
      }}
      function comparisonCandidates(active) {{
        if (state.referenceTrace === null) return [];
        return selectableTraces(active);
      }}
      function orderedTraces(active) {{
        if (state.view !== 'overlay' || state.referenceTrace === null) return active;
        var referenceTrace = active.find(function (trace) {{
          return trace.table_index === state.referenceTrace;
        }});
        if (!referenceTrace) return active;
        return active.filter(function (trace) {{
          return trace.table_index !== state.referenceTrace;
        }}).concat([referenceTrace]);
      }}
      function closeSelectedMenu() {{
        if (!selectedMenu || !selectedToggle) return;
        selectedMenu.hidden = true;
        selectedToggle.setAttribute('aria-expanded', 'false');
      }}
      function updateViewControls() {{
        var isPairwise = state.view === 'pairwise';
        if (selectedControl) selectedControl.hidden = isPairwise;
        if (pairwiseControl) pairwiseControl.hidden = !isPairwise;
        if (isPairwise) closeSelectedMenu();
      }}
      function updateSelectedTraceOptions(active) {{
        if (!selectedOptions) return;
        var candidates = selectableTraces(active);
        while (selectedOptions.firstChild) selectedOptions.removeChild(
          selectedOptions.firstChild
        );
        candidates.forEach(function (trace) {{
          var option = document.createElement('label');
          option.className = 'report-picker-option';
          var checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.value = String(trace.table_index);
          checkbox.checked = isSelectedTrace(trace);
          checkbox.setAttribute('aria-label', trace.name);
          checkbox.addEventListener('change', function () {{
            if (state.selectedTraceIndices === null) {{
              state.selectedTraceIndices = new Set(
                candidates.map(function (item) {{ return item.table_index; }})
              );
            }}
            if (checkbox.checked) {{
              state.selectedTraceIndices.add(trace.table_index);
            }} else {{
              state.selectedTraceIndices.delete(trace.table_index);
            }}
            render();
          }});
          option.appendChild(checkbox);
          option.appendChild(document.createTextNode(trace.name));
          selectedOptions.appendChild(option);
        }});
        if (!candidates.length) {{
          var empty = document.createElement('div');
          empty.className = 'report-picker-empty';
          empty.textContent = 'No other traces are available.';
          selectedOptions.appendChild(empty);
        }}
        var selectedCount = candidates.filter(isSelectedTrace).length;
        if (selectedCountLabel) {{
          selectedCountLabel.textContent = candidates.length === 0
            ? 'None'
            : selectedCount === candidates.length
              ? 'All'
              : String(selectedCount);
        }}
        if (selectAll) selectAll.disabled = candidates.length === 0;
        if (selectNone) selectNone.disabled = candidates.length === 0;
      }}
      function updateReferenceOptions(active) {{
        if (!reference) return;
        var selected = state.referenceTrace;
        var selectedIsVisible = active.some(function (trace) {{
          return trace.table_index === selected;
        }});
        if (!selectedIsVisible) {{
          state.referenceTrace = null;
          selected = null;
        }}
        while (reference.firstChild) reference.removeChild(reference.firstChild);
        var none = document.createElement('option');
        none.value = '';
        none.textContent = 'None';
        reference.appendChild(none);
        active.forEach(function (trace) {{
          var option = document.createElement('option');
          option.value = String(trace.table_index);
          option.textContent = trace.name;
          reference.appendChild(option);
        }});
        reference.value = selected === null ? '' : String(selected);
      }}
      function updatePairwiseOptions(active) {{
        if (!comparison) return;
        var candidates = comparisonCandidates(active);
        var selected = state.comparisonTrace;
        var selectedIsAvailable = candidates.some(function (trace) {{
          return trace.table_index === selected;
        }});
        if (!selectedIsAvailable) {{
          state.comparisonTrace = candidates.length
            ? candidates[0].table_index
            : null;
        }}
        while (comparison.firstChild) comparison.removeChild(comparison.firstChild);
        if (state.referenceTrace === null) {{
          var referencePrompt = document.createElement('option');
          referencePrompt.value = '';
          referencePrompt.textContent = 'Select a reference first';
          comparison.appendChild(referencePrompt);
        }} else if (!candidates.length) {{
          var noCandidates = document.createElement('option');
          noCandidates.value = '';
          noCandidates.textContent = 'No comparison traces available';
          comparison.appendChild(noCandidates);
        }} else {{
          candidates.forEach(function (trace) {{
            var option = document.createElement('option');
            option.value = String(trace.table_index);
            option.textContent = trace.name;
            comparison.appendChild(option);
          }});
        }}
        comparison.disabled = state.referenceTrace === null || !candidates.length;
        comparison.value = state.comparisonTrace === null
          ? ''
          : String(state.comparisonTrace);
        var navigationDisabled = candidates.length < 2 || comparison.disabled;
        if (previousTrace) previousTrace.disabled = navigationDisabled;
        if (nextTrace) nextTrace.disabled = navigationDisabled;
      }}
      function pairwiseDisplayTraces(active) {{
        if (state.referenceTrace === null || state.comparisonTrace === null) {{
          return [];
        }}
        var referenceTrace = active.find(function (trace) {{
          return trace.table_index === state.referenceTrace;
        }});
        var comparisonTrace = active.find(function (trace) {{
          return trace.table_index === state.comparisonTrace;
        }});
        if (!referenceTrace || !comparisonTrace) return [];
        // Plotly draws later traces on top, so the reference stays behind.
        return [referenceTrace, comparisonTrace];
      }}
      function cycleComparison(direction) {{
        if (state.view !== 'pairwise' || state.referenceTrace === null) return;
        var candidates = comparisonCandidates(activeTraces());
        if (!candidates.length) return;
        var currentIndex = candidates.findIndex(function (trace) {{
          return trace.table_index === state.comparisonTrace;
        }});
        var nextIndex;
        if (currentIndex === -1) {{
          nextIndex = direction > 0 ? 0 : candidates.length - 1;
        }} else {{
          nextIndex = (currentIndex + direction + candidates.length)
            % candidates.length;
        }}
        state.comparisonTrace = candidates[nextIndex].table_index;
        render();
        if (comparison && !comparison.disabled) comparison.focus();
      }}
      function handleComparisonKey(event) {{
        if (state.view !== 'pairwise' || !comparison || comparison.disabled) return;
        var direction = 0;
        if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') direction = -1;
        if (event.key === 'ArrowDown' || event.key === 'ArrowRight') direction = 1;
        if (direction === 0) return;
        event.preventDefault();
        cycleComparison(direction);
      }}
      function baseLayout() {{
        var channelSpec = data.channels[state.channel] || {{}};
        return {{
          template: 'plotly_white',
          paper_bgcolor: '#ffffff',
          plot_bgcolor: '#fbfdfd',
          autosize: true,
          font: {{
            family: '"Aptos", "Segoe UI", "Helvetica Neue", sans-serif',
            color: '#163342',
            size: 12
          }},
          title: {{
            text: 'MS' + state.msLevel + ' ' + String.fromCharCode(183) + ' '
              + (channelSpec.label || state.channel),
            x: 0.02,
            xanchor: 'left',
            font: {{
              family: '"Aptos Display", "Aptos", "Segoe UI", sans-serif',
              color: '#063853',
              size: 16,
              weight: 600
            }}
          }},
          margin: {{l: 78, r: 24, t: 58, b: 82}},
          hovermode: 'x unified',
          hoverlabel: {{
            bgcolor: '#063853',
            bordercolor: '#40B7B5',
            font: {{color: '#ffffff'}}
          }},
          xaxis: {{
            title: {{text: RETENTION_TIME_TITLE}},
            showgrid: true,
            gridcolor: '#dce8eb',
            zerolinecolor: '#b9ccd2',
            linecolor: '#b9ccd2',
            ticks: 'outside'
          }},
          yaxis: {{
            title: {{text: channelSpec.y_axis_title || 'Intensity'}},
            showgrid: true,
            gridcolor: '#dce8eb',
            zerolinecolor: '#b9ccd2',
            linecolor: '#b9ccd2',
            exponentformat: 'E',
            ticks: 'outside'
          }},
          legend: {{
            orientation: 'h',
            x: 0,
            xanchor: 'left',
            yanchor: 'top',
            bgcolor: 'rgba(255, 255, 255, .9)',
            bordercolor: '#d3e1e5',
            borderwidth: 1,
            groupclick: 'togglegroup',
            font: {{size: 11, color: '#163342'}}
          }},
        }};
      }}
      function fullscreenElement() {{
        return document.fullscreenElement
          || document.webkitFullscreenElement
          || null;
      }}
      function isPlotFullscreen() {{
        return Boolean(plotShell && fullscreenElement() === plotShell);
      }}
      function fullscreenSupported() {{
        return Boolean(
          plotShell
          && (plotShell.requestFullscreen || plotShell.webkitRequestFullscreen)
        );
      }}
      function updateFullscreenToggle() {{
        if (!fullscreenToggle) return;
        if (!fullscreenSupported()) {{
          fullscreenToggle.disabled = true;
          fullscreenToggle.setAttribute(
            'aria-label',
            'Fullscreen is not supported by this browser'
          );
          fullscreenToggle.title = 'Fullscreen is not supported by this browser';
          return;
        }}
        var active = isPlotFullscreen();
        fullscreenToggle.disabled = false;
        fullscreenToggle.setAttribute(
          'aria-label',
          active ? 'Exit fullscreen plot' : 'Enter fullscreen plot'
        );
        fullscreenToggle.setAttribute('aria-pressed', active ? 'true' : 'false');
        fullscreenToggle.title = active
          ? 'Exit fullscreen plot'
          : 'Enter fullscreen plot';
      }}
      function exitPlotFullscreen() {{
        var exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) exit.call(document);
      }}
      function togglePlotFullscreen() {{
        if (!plotShell || !fullscreenSupported()) return;
        if (isPlotFullscreen()) {{
          exitPlotFullscreen();
          return;
        }}
        var request = plotShell.requestFullscreen
          || plotShell.webkitRequestFullscreen;
        var result = request.call(plotShell);
        if (result && typeof result.catch === 'function') {{
          result.catch(updateFullscreenToggle);
        }}
      }}
      function fullscreenPlotHeight(defaultHeight) {{
        if (!isPlotFullscreen() || !plotShell) return defaultHeight;
        var actions = document.querySelector('.report-plot-actions');
        var actionHeight = actions ? actions.offsetHeight : 0;
        return Math.max(
          320,
          plotShell.clientHeight - 24 - actionHeight,
          defaultHeight
        );
      }}
      function addEmptyMessage(layout, message) {{
        layout.annotations = [{{
          text: message,
          x: 0.5,
          y: 0.5,
          xref: 'paper',
          yref: 'paper',
          showarrow: false,
          font: {{size: 14, color: '#5f747e'}},
          align: 'center'
        }}];
      }}
      function traceColor(trace) {{
        return trace.table_index === state.referenceTrace
          ? REFERENCE_COLOR
          : palette[trace.color_index % palette.length];
      }}
      function traceLegendGroup(trace) {{
        return 'trace-' + String(trace.table_index);
      }}
      function makeTrace(trace, index, xAxis, yAxis) {{
        var color = traceColor(trace);
        var item = {{
          x: trace.retention_time_min,
          y: trace.channels[state.channel],
          type: 'scattergl',
          mode: 'lines',
          name: trace.name,
          legendgroup: traceLegendGroup(trace),
          meta: {{rawtraceTableIndex: trace.table_index}},
          showlegend: false,
          line: {{
            color: color,
            width: 1.25
          }},
          hovertemplate: 'RT: %{{x:.2f}} min<br>Intensity: %{{y:.3e}}<extra>'
            + trace.name + '</extra>'
        }};
        if (xAxis) item.xaxis = xAxis;
        if (yAxis) item.yaxis = yAxis;
        return item;
      }}
      function makeLegendTrace(trace) {{
        return {{
          x: [null],
          y: [null],
          type: 'scatter',
          mode: 'markers',
          name: trace.name,
          legendgroup: traceLegendGroup(trace),
          meta: {{
            rawtraceTableIndex: trace.table_index,
            rawtraceLegendProxy: true
          }},
          marker: {{
            color: traceColor(trace),
            symbol: 'square',
            size: 8
          }},
          hoverinfo: 'skip',
          visible: true,
          showlegend: true
        }};
      }}
      function toggleLegendTrace(event) {{
        if (!plot || !event || !plot.data) return;
        var clicked = plot.data[event.curveNumber];
        if (!clicked || !clicked.meta || !clicked.meta.rawtraceLegendProxy) return;
        var tableIndex = clicked.meta.rawtraceTableIndex;
        var targetIndex = plot.data.findIndex(function (trace) {{
          return trace.meta
            && trace.meta.rawtraceTableIndex === tableIndex
            && !trace.meta.rawtraceLegendProxy;
        }});
        if (targetIndex === -1) return false;
        var target = plot.data[targetIndex];
        var isVisible = target.visible !== false
          && target.visible !== 'legendonly';
        Plotly.restyle(
          plot,
          {{visible: isVisible ? 'legendonly' : true}},
          [targetIndex, event.curveNumber]
        );
        return false;
      }}
      function bindLegendClick() {{
        if (!plot || plot.rawtraceLegendClickBound
            || typeof plot.on !== 'function') return;
        plot.on('plotly_legendclick', toggleLegendTrace);
        plot.rawtraceLegendClickBound = true;
      }}
      function addPairwiseHeader(layout, referenceTrace, comparisonTrace) {{
        function row(role, trace) {{
          return '<span style="color:' + traceColor(trace) + '">'
            + String.fromCharCode(9632) + '</span> ' + role + ': ' + trace.name;
        }}
        layout.margin.t = PAIRWISE_TOP_MARGIN_PX;
        layout.annotations = [{{
          text: row('Reference', referenceTrace) + '<br>'
            + row('Comparison', comparisonTrace),
          x: 0,
          y: 1,
          xref: 'paper',
          yref: 'paper',
          xanchor: 'left',
          yanchor: 'bottom',
          yshift: 4,
          align: 'left',
          showarrow: false,
          font: {{size: 12, color: '#163342', weight: 600}}
        }}];
      }}
      function applyBottomLayout(layout, showsLegend) {{
        layout.showlegend = showsLegend;
        if (!showsLegend) {{
          layout.margin.b = NO_LEGEND_BOTTOM_MARGIN_PX;
          plot.style.height = layout.height + 'px';
          plot.style.minHeight = layout.height + 'px';
          return;
        }}
        layout.margin.b = LEGEND_GAP_PX + state.legendHeight
          + LEGEND_BOTTOM_PADDING_PX;
        if (!isPlotFullscreen()) {{
          layout.height += Math.max(
            0,
            layout.margin.b - DEFAULT_BOTTOM_MARGIN_PX
          );
        }}
        plot.style.height = layout.height + 'px';
        plot.style.minHeight = layout.height + 'px';
        layout.legend.y = -LEGEND_GAP_PX
          / (layout.height - layout.margin.t - layout.margin.b);
      }}
      function measuredLegendHeight() {{
        var background = plot.querySelector('.legend .bg');
        return background ? Number(background.getAttribute('height')) : 0;
      }}
      function render(isLegendRefit) {{
        updateMetadataRows();
        updateSortIndicators();
        if (!plot || !window.Plotly || !state.channel) return;
        var active = activeTraces();
        updateViewControls();
        updateReferenceOptions(active);
        var layout = baseLayout();
        var traces;
        var legendTraces = [];
        if (state.view === 'pairwise') {{
          updatePairwiseOptions(active);
          traces = pairwiseDisplayTraces(active);
        }} else {{
          updateSelectedTraceOptions(active);
          traces = orderedTraces(selectedDisplayTraces(active));
        }}
        if (plotShell) plotShell.classList.toggle(
          'is-stacked',
          state.view === 'stacked' && traces.length > 0
        );
        if (!traces.length) {{
          var emptyMessage = state.view === 'pairwise'
            ? state.referenceTrace === null
              ? 'Select a reference trace to start a pairwise comparison.'
              : 'No comparison traces are available.'
            : 'Select at least one trace to display.';
          addEmptyMessage(layout, emptyMessage);
        }}
        var showsLegend = state.view === 'overlay' && traces.length > 0;
        if (state.view === 'pairwise' && traces.length) {{
          addPairwiseHeader(layout, traces[0], traces[1]);
        }}
        if (state.view === 'stacked' && traces.length) {{
          var stackedHeight = Math.max(
            NORMAL_PLOT_HEIGHT,
            traces.length * STACKED_TRACE_HEIGHT
          );
          var displayHeight = fullscreenPlotHeight(stackedHeight);
          plot.style.height = displayHeight + 'px';
          plot.style.minHeight = displayHeight + 'px';
          layout.height = displayHeight;
          layout.grid = {{
            rows: traces.length,
            columns: 1,
            pattern: 'independent',
            roworder: 'top to bottom'
          }};
          var stackedYTitle = layout.yaxis.title;
          delete layout.xaxis;
          delete layout.yaxis;
          layout.margin.t = 76;
          layout.annotations = [];
          traces = traces.map(function (trace, index) {{
            var suffix = index === 0 ? '' : String(index + 1);
            layout.annotations.push({{
              text: '<span style="color:' + traceColor(trace) + '">'
                + String.fromCharCode(9632) + '</span> ' + trace.name,
              x: 0,
              y: 1,
              xref: 'x' + suffix + ' domain',
              yref: 'y' + suffix + ' domain',
              xanchor: 'left',
              yanchor: 'bottom',
              yshift: 2,
              showarrow: false,
              font: {{size: 12, color: '#163342', weight: 600}}
            }});
            layout['xaxis' + suffix] = {{
              title: {{
                text: index === traces.length - 1 ? RETENTION_TIME_TITLE : ''
              }},
              matches: index ? 'x' : undefined,
              showgrid: true,
              gridcolor: '#dce8eb',
              zerolinecolor: '#b9ccd2',
              linecolor: '#b9ccd2',
              ticks: 'outside'
            }};
            layout['yaxis' + suffix] = {{
              title: stackedYTitle,
              showgrid: true,
              gridcolor: '#dce8eb',
              zerolinecolor: '#b9ccd2',
              linecolor: '#b9ccd2',
              exponentformat: 'E',
              ticks: 'outside'
            }};
            return makeTrace(trace, index, 'x' + suffix, 'y' + suffix);
          }});
        }} else {{
          var displayHeight = fullscreenPlotHeight(NORMAL_PLOT_HEIGHT);
          traces = traces.map(function (trace, index) {{
            if (showsLegend) legendTraces.push(makeLegendTrace(trace));
            return makeTrace(trace, index, null, null);
          }});
          plot.style.height = displayHeight + 'px';
          plot.style.minHeight = displayHeight + 'px';
          layout.height = displayHeight;
        }}
        applyBottomLayout(layout, showsLegend);
        var reactResult = Plotly.react(
          plot,
          traces.concat(legendTraces),
          layout,
          {{responsive: true, displaylogo: false, scrollZoom: true}}
        );
        function afterPlot() {{
          bindLegendClick();
          if (
            !showsLegend
            || isLegendRefit === true
            || plot.offsetParent === null
          ) return;
          var legendHeight = measuredLegendHeight();
          if (legendHeight !== state.legendHeight) {{
            state.legendHeight = legendHeight;
            render(true);
          }}
        }}
        if (reactResult && typeof reactResult.then === 'function') {{
          reactResult.then(afterPlot);
        }} else {{
          afterPlot();
        }}
      }}
      function activateTab(button) {{
        document.querySelectorAll('.report-tab').forEach(function (item) {{
          var active = item === button;
          item.classList.toggle('is-active', active);
          item.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        document.querySelectorAll('.report-panel').forEach(function (panel) {{
          panel.hidden = panel.id !== button.dataset.panel;
        }});
        if (button.dataset.channel) {{
          state.channel = button.dataset.channel;
          render();
        }}
      }}
      document.querySelectorAll('.report-tab').forEach(function (button) {{
        button.addEventListener('click', function () {{ activateTab(button); }});
      }});
      sortButtons.forEach(function (button) {{
        button.addEventListener('click', function () {{
          cycleMetadataSort(button.dataset.sortField);
        }});
      }});
      var ms = document.getElementById('report-ms-level');
      if (ms) {{
        ms.value = String(state.msLevel);
        ms.addEventListener('change', function () {{
          state.msLevel = Number(ms.value);
          render();
        }});
      }}
      var cv = document.getElementById('report-faims');
      if (cv) cv.addEventListener('change', function () {{
        state.cv = cv.value;
        render();
      }});
      var view = document.getElementById('report-view');
      if (view) {{
        view.value = state.view;
        view.addEventListener('change', function () {{
          state.view = view.value;
          render();
        }});
      }}
      if (reference) reference.addEventListener('change', function () {{
        state.referenceTrace = reference.value === ''
          ? null
          : Number(reference.value);
        render();
      }});
      if (selectedToggle) selectedToggle.addEventListener('click', function () {{
        var isOpen = selectedMenu && !selectedMenu.hidden;
        if (isOpen) {{
          closeSelectedMenu();
        }} else if (selectedMenu) {{
          selectedMenu.hidden = false;
          selectedMenu.style.left = '';
          var viewportWidth = document.documentElement.clientWidth;
          var overflow = selectedMenu.getBoundingClientRect().right
            - (viewportWidth - 18);
          if (overflow > 0) selectedMenu.style.left = -overflow + 'px';
          selectedToggle.setAttribute('aria-expanded', 'true');
        }}
      }});
      if (selectAll) selectAll.addEventListener('click', function () {{
        state.selectedTraceIndices = null;
        render();
      }});
      if (selectNone) selectNone.addEventListener('click', function () {{
        state.selectedTraceIndices = new Set();
        render();
      }});
      document.addEventListener('click', function (event) {{
        if (selectedControl && !selectedControl.contains(event.target)) {{
          closeSelectedMenu();
        }}
      }});
      document.addEventListener('keydown', function (event) {{
        if (event.key === 'Escape' && isPlotFullscreen()) {{
          exitPlotFullscreen();
          return;
        }}
        if (event.key === 'Escape' && selectedMenu && !selectedMenu.hidden) {{
          closeSelectedMenu();
          if (selectedToggle) selectedToggle.focus();
        }}
        if (
          event.target !== comparison
          && event.target
          && !event.target.matches(
            'select, input, textarea, [contenteditable="true"]'
          )
        ) {{
          handleComparisonKey(event);
        }}
      }});
      if (comparison) {{
        comparison.addEventListener('change', function () {{
          state.comparisonTrace = comparison.value === ''
            ? null
            : Number(comparison.value);
          render();
        }});
        comparison.addEventListener('keydown', function (event) {{
          handleComparisonKey(event);
        }});
      }}
      if (previousTrace) previousTrace.addEventListener('click', function () {{
        cycleComparison(-1);
      }});
      if (nextTrace) nextTrace.addEventListener('click', function () {{
        cycleComparison(1);
      }});
      function handleFullscreenChange() {{
        updateFullscreenToggle();
        render();
      }}
      if (fullscreenToggle) {{
        fullscreenToggle.addEventListener('click', togglePlotFullscreen);
        updateFullscreenToggle();
      }}
      document.addEventListener('fullscreenchange', handleFullscreenChange);
      document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
      document.getElementById('{active_panel}').hidden = false;
      document.querySelectorAll('.report-panel').forEach(function (panel) {{
        if (panel.id !== '{active_panel}') panel.hidden = true;
      }});
      render();
    }})();
    """

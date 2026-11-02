"""Persistent configuration for the rawtrace-qc desktop application."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rawtrace_qc.discovery import DiscoveryOptions, DiscoveryScope
from rawtrace_qc.environment import default_data_directory
from rawtrace_qc.errors import ConfigurationError
from rawtrace_qc.gui.patterns import FilenamePattern, PatternMode


@dataclass(frozen=True, slots=True)
class GuiSettings:
    """Store persisted discovery, cache, and report settings."""

    scope: DiscoveryScope = DiscoveryScope.DIRECT
    min_size_mb: int = 1
    min_age_minutes: float = 2
    patterns: tuple[FilenamePattern, ...] = ()
    cache_directory: Path = field(
        default_factory=lambda: default_data_directory() / "traces"
    )
    report_directory: Path = field(
        default_factory=lambda: default_data_directory() / "reports"
    )
    theme_mode: str = "system"

    def __post_init__(self) -> None:
        """Validate persisted values and normalize enum and path fields."""
        if self.theme_mode not in ("system", "light", "dark"):
            raise ConfigurationError(
                f"GUI theme mode {self.theme_mode!r} is invalid; choose 'system', "
                "'light', or 'dark'."
            )
        try:
            scope = DiscoveryScope(self.scope)
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                f"GUI discovery scope {self.scope!r} is invalid; choose 'direct' "
                "or 'recursive'."
            ) from error
        try:
            DiscoveryOptions(
                scope=scope,
                min_size_bytes=self.min_size_mb * 1024 * 1024,
                min_age_seconds=self.min_age_minutes * 60,
            )
        except (TypeError, ValueError) as error:
            raise ConfigurationError(
                "GUI discovery thresholds must be non-negative numeric values."
            ) from error
        patterns = tuple(self.patterns)
        if any(not isinstance(pattern, FilenamePattern) for pattern in patterns):
            raise ConfigurationError(
                "GUI patterns must contain only FilenamePattern instances."
            )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "patterns", patterns)
        object.__setattr__(self, "cache_directory", Path(self.cache_directory))
        object.__setattr__(self, "report_directory", Path(self.report_directory))

    def discovery_options(self) -> DiscoveryOptions:
        """Return discovery options represented by this configuration."""
        return DiscoveryOptions(
            scope=self.scope,
            min_size_bytes=self.min_size_mb * 1024 * 1024,
            min_age_seconds=self.min_age_minutes * 60,
        )


def default_config_path() -> Path:
    """Return the GUI configuration path inside the application data directory."""
    return default_data_directory() / "config.json"


def load_settings(path: Path | None = None) -> GuiSettings:
    """Load GUI settings from JSON, returning defaults for a missing file.

    Args:
        path: Configuration file path. If None (default), uses
            `default_config_path()`.

    Returns:
        Validated GUI settings.

    Raises:
        ConfigurationError: If the file cannot be decoded or contains invalid
            settings.
    """
    resolved_path = (path or default_config_path()).expanduser().resolve()
    if not resolved_path.exists():
        return GuiSettings()
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(
            f"Could not load GUI configuration {resolved_path}: {error}."
        ) from error
    try:
        return _settings_from_mapping(payload)
    except (TypeError, ValueError, KeyError) as error:
        raise ConfigurationError(
            f"GUI configuration {resolved_path} has an invalid structure: {error}."
        ) from error


def save_settings(settings: GuiSettings, path: Path | None = None) -> Path:
    """Write validated GUI settings to JSON and return the resolved path."""
    if not isinstance(settings, GuiSettings):
        raise ConfigurationError(
            f"Expected GuiSettings, got {type(settings).__name__!r}."
        )
    resolved_path = (path or default_config_path()).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved_path.write_text(
            json.dumps(_settings_to_mapping(settings), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise ConfigurationError(
            f"Could not save GUI configuration {resolved_path}: {error}."
        ) from error
    return resolved_path


def _settings_from_mapping(payload: Any) -> GuiSettings:
    if not isinstance(payload, dict):
        raise TypeError("the root value must be an object")
    discovery = payload.get("discovery", {})
    if not isinstance(discovery, dict):
        raise TypeError("discovery must be an object")
    patterns_payload = payload.get("patterns", [])
    if not isinstance(patterns_payload, list):
        raise TypeError("patterns must be a list")
    patterns = tuple(
        FilenamePattern(
            name=item["name"],
            expression=item["expression"],
            mode=item.get("mode", PatternMode.INCLUDE),
        )
        for item in patterns_payload
        if isinstance(item, dict)
    )
    if len(patterns) != len(patterns_payload):
        raise TypeError("every pattern must be an object")
    min_size_mb = discovery.get("min_size_mb")
    if min_size_mb is None and "min_size_bytes" in discovery:
        min_size_mb = int(discovery["min_size_bytes"] / (1024 * 1024))
    min_age_minutes = discovery.get("min_age_minutes")
    if min_age_minutes is None and "min_age_seconds" in discovery:
        min_age_minutes = discovery["min_age_seconds"] / 60
    return GuiSettings(
        scope=discovery.get("scope", DiscoveryScope.DIRECT),
        min_size_mb=1 if min_size_mb is None else min_size_mb,
        min_age_minutes=2 if min_age_minutes is None else min_age_minutes,
        patterns=patterns,
        cache_directory=Path(
            payload.get("cache_directory", default_data_directory() / "traces")
        ),
        report_directory=Path(
            payload.get("report_directory", default_data_directory() / "reports")
        ),
        theme_mode=payload.get("theme_mode", "system"),
    )


def _settings_to_mapping(settings: GuiSettings) -> dict[str, Any]:
    return {
        "cache_directory": str(settings.cache_directory),
        "discovery": {
            "min_age_minutes": settings.min_age_minutes,
            "min_size_mb": settings.min_size_mb,
            "scope": settings.scope.value,
        },
        "patterns": [
            {
                "expression": pattern.expression,
                "mode": pattern.mode.value,
                "name": pattern.name,
            }
            for pattern in settings.patterns
        ],
        "report_directory": str(settings.report_directory),
        "theme_mode": settings.theme_mode,
    }

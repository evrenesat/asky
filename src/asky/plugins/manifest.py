"""Plugin manifest schema and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

REQUIRED_MANIFEST_KEYS = ("enabled", "module", "class")
OPTIONAL_MANIFEST_KEYS = ("dependencies", "capabilities", "config_file")
KNOWN_MANIFEST_KEYS = set(REQUIRED_MANIFEST_KEYS + OPTIONAL_MANIFEST_KEYS)


@dataclass(frozen=True)
class PluginManifest:
    """Normalized plugin manifest entry."""

    name: str
    enabled: bool
    module: str
    plugin_class: str
    dependencies: Tuple[str, ...] = ()
    capabilities: Tuple[str, ...] = ()
    config_file: Optional[str] = None


@dataclass(frozen=True)
class ManifestBuildResult:
    """Result of building one manifest entry."""

    manifest: Optional[PluginManifest]
    warnings: Tuple[str, ...] = ()
    error: Optional[str] = None


def _normalize_string_list(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        token = value.strip()
        return (token,) if token else ()
    if not isinstance(value, Iterable):
        return ()

    normalized = []
    for item in value:
        token = str(item or "").strip()
        if token:
            normalized.append(token)
    return tuple(normalized)


def build_manifest_entry(name: str, raw_entry: Any) -> ManifestBuildResult:
    """Validate and normalize one manifest block."""
    if not isinstance(raw_entry, dict):
        return ManifestBuildResult(
            manifest=None,
            error="manifest entry must be a TOML table",
        )

    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in raw_entry]
    if missing:
        return ManifestBuildResult(
            manifest=None,
            error=f"missing required field(s): {', '.join(sorted(missing))}",
        )

    enabled = bool(raw_entry.get("enabled"))
    module = str(raw_entry.get("module", "") or "").strip()
    plugin_class = str(raw_entry.get("class", "") or "").strip()
    if not module:
        return ManifestBuildResult(
            manifest=None,
            error="field 'module' must be a non-empty string",
        )
    if not plugin_class:
        return ManifestBuildResult(
            manifest=None,
            error="field 'class' must be a non-empty string",
        )

    config_file = raw_entry.get("config_file")
    normalized_config_file = None
    if config_file is not None:
        normalized_config_file = str(config_file).strip() or None

    dependencies = _normalize_string_list(raw_entry.get("dependencies"))
    capabilities = _normalize_string_list(raw_entry.get("capabilities"))

    unknown_keys = sorted(set(raw_entry.keys()) - KNOWN_MANIFEST_KEYS)
    warnings = tuple(
        f"plugin '{name}': ignoring unknown manifest key '{key}'"
        for key in unknown_keys
    )

    return ManifestBuildResult(
        manifest=PluginManifest(
            name=name,
            enabled=enabled,
            module=module,
            plugin_class=plugin_class,
            dependencies=dependencies,
            capabilities=capabilities,
            config_file=normalized_config_file,
        ),
        warnings=warnings,
    )

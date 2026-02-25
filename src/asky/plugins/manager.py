"""Plugin manager: manifest loading, import, dependency ordering, lifecycle."""

from __future__ import annotations

import importlib
import logging
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from asky.config.loader import _get_config_dir
from asky.plugins.base import AskyPlugin, PluginContext, PluginStatus
from asky.plugins.hooks import HookRegistry
from asky.plugins.manifest import PluginManifest, build_manifest_entry

logger = logging.getLogger(__name__)
PLUGIN_ROSTER_FILENAME = "plugins.toml"
PLUGIN_CONFIG_SUBDIR = "plugins"
PLUGIN_DATA_SUBDIR = "plugins"
_BUNDLED_PLUGINS_TOML = resources.files("asky.data.config").joinpath("plugins.toml")
ACTIVE_PLUGIN_STATE = "active"
IMPORTED_PLUGIN_STATE = "imported"
DISABLED_PLUGIN_STATE = "disabled"
FAILED_MANIFEST_STATE = "failed_manifest"
FAILED_DEPENDENCY_STATE = "failed_dependency"
SKIPPED_DEPENDENCY_STATE = "skipped_dependency"
FAILED_IMPORT_STATE = "failed_import"
FAILED_ACTIVATION_STATE = "failed_activation"
INACTIVE_PLUGIN_STATE = "inactive"


class PluginManager:
    """Load, resolve, and manage plugin lifecycle."""

    def __init__(
        self,
        *,
        hook_registry: Optional[HookRegistry] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        self.hook_registry = hook_registry or HookRegistry()
        self.config_dir = (config_dir or _get_config_dir()).expanduser()
        self.roster_path = self.config_dir / PLUGIN_ROSTER_FILENAME
        self.plugin_config_root = self.config_dir
        self.plugin_data_root = self.config_dir / PLUGIN_DATA_SUBDIR

        self._manifests: Dict[str, PluginManifest] = {}
        self._plugins: Dict[str, AskyPlugin] = {}
        self._contexts: Dict[str, PluginContext] = {}
        self._statuses: Dict[str, PluginStatus] = {}
        self._load_order: List[str] = []
        self._activation_order: List[str] = []

    def load_roster(self) -> List[PluginManifest]:
        """Load plugin roster from ~/.config/asky/plugins.toml."""
        self._ensure_roster_file()

        try:
            with self.roster_path.open("rb") as file_obj:
                payload = tomllib.load(file_obj)
        except tomllib.TOMLDecodeError as exc:
            logger.error("Invalid plugins.toml at %s: %s", self.roster_path, exc)
            return []
        except Exception:
            logger.exception("Failed to read plugin roster at %s", self.roster_path)
            return []

        plugin_table = payload.get("plugin", {})
        if not isinstance(plugin_table, dict):
            logger.warning("plugins.toml entry [plugin] must be a table")
            return []

        self._manifests = {}
        self._plugins = {}
        self._contexts = {}
        self._statuses = {}
        self._load_order = []
        self._activation_order = []

        normalized_name_map: Dict[str, str] = {}
        for plugin_name in sorted(plugin_table.keys()):
            raw_entry = plugin_table.get(plugin_name)
            name = str(plugin_name or "").strip()
            if not name:
                continue

            normalized_name = name.casefold()
            if normalized_name in normalized_name_map:
                conflict_name = normalized_name_map[normalized_name]
                self._statuses[name] = PluginStatus(
                    name=name,
                    enabled=False,
                    state=FAILED_MANIFEST_STATE,
                    message=f"name collision with plugin '{conflict_name}'",
                )
                logger.error(
                    "Plugin name collision: '%s' conflicts with '%s'",
                    name,
                    conflict_name,
                )
                continue
            normalized_name_map[normalized_name] = name

            build_result = build_manifest_entry(name, raw_entry)
            for warning in build_result.warnings:
                logger.warning(warning)

            if build_result.manifest is None:
                message = build_result.error or "invalid manifest entry"
                self._statuses[name] = PluginStatus(
                    name=name,
                    enabled=False,
                    state=FAILED_MANIFEST_STATE,
                    message=message,
                )
                logger.error("Plugin '%s' manifest invalid: %s", name, message)
                continue

            manifest = build_result.manifest
            self._manifests[name] = manifest
            state = DISABLED_PLUGIN_STATE if not manifest.enabled else "loaded"
            status_message = "plugin is disabled" if not manifest.enabled else ""
            self._statuses[name] = PluginStatus(
                name=name,
                enabled=manifest.enabled,
                module=manifest.module,
                plugin_class=manifest.plugin_class,
                state=state,
                message=status_message,
                active=False,
                dependencies=manifest.dependencies,
            )

        return [self._manifests[name] for name in sorted(self._manifests.keys())]

    def discover_and_import(self) -> None:
        """Import plugin classes and instantiate plugin objects."""
        order = self._resolve_dependency_order()
        self._load_order = []

        for plugin_name in order:
            manifest = self._manifests[plugin_name]
            if not manifest.enabled:
                continue
            dependency_failure = self._first_failed_dependency(manifest)
            if dependency_failure is not None:
                self._set_status(
                    plugin_name,
                    state=SKIPPED_DEPENDENCY_STATE,
                    message=(
                        f"dependency '{dependency_failure}' is not available"
                    ),
                )
                continue

            try:
                plugin_module = importlib.import_module(manifest.module)
                plugin_class = getattr(plugin_module, manifest.plugin_class)
                plugin_instance = plugin_class()
                if not isinstance(plugin_instance, AskyPlugin):
                    raise TypeError(
                        f"{manifest.module}.{manifest.plugin_class} is not an AskyPlugin"
                    )
            except Exception as exc:
                self._set_status(
                    plugin_name,
                    state=FAILED_IMPORT_STATE,
                    message=str(exc),
                )
                logger.exception(
                    "Plugin '%s' import failed module=%s class=%s",
                    plugin_name,
                    manifest.module,
                    manifest.plugin_class,
                )
                continue

            self._plugins[plugin_name] = plugin_instance
            self._load_order.append(plugin_name)
            self._set_status(plugin_name, state=IMPORTED_PLUGIN_STATE, message="")

    def activate_all(self) -> None:
        """Activate all imported plugins in deterministic dependency order."""
        self.plugin_data_root.mkdir(parents=True, exist_ok=True)
        self._activation_order = []

        for plugin_name in self._load_order:
            manifest = self._manifests[plugin_name]
            if not manifest.enabled:
                continue

            dependency_failure = self._first_failed_dependency(manifest)
            if dependency_failure is not None:
                self._set_status(
                    plugin_name,
                    state=SKIPPED_DEPENDENCY_STATE,
                    message=(
                        f"dependency '{dependency_failure}' is not active"
                    ),
                )
                continue

            plugin = self._plugins.get(plugin_name)
            if plugin is None:
                continue

            try:
                plugin_config = self._load_plugin_config(manifest)
            except Exception as exc:
                self._set_status(
                    plugin_name,
                    state=FAILED_ACTIVATION_STATE,
                    message=f"config load failed: {exc}",
                )
                logger.exception(
                    "Plugin '%s' config load failed from %s",
                    plugin_name,
                    manifest.config_file,
                )
                continue

            context = PluginContext(
                plugin_name=plugin_name,
                config_dir=self.config_dir,
                data_dir=self._get_plugin_data_dir(plugin_name),
                config=plugin_config,
                hook_registry=self.hook_registry,
                logger=logger.getChild(plugin_name),
            )

            capability_mismatches = [
                capability
                for capability in manifest.capabilities
                if capability not in plugin.declared_capabilities
            ]
            for capability in capability_mismatches:
                logger.warning(
                    "Plugin '%s' manifest capability '%s' is not declared by plugin class",
                    plugin_name,
                    capability,
                )

            try:
                context.data_dir.mkdir(parents=True, exist_ok=True)
                plugin.activate(context)
            except Exception as exc:
                self._set_status(
                    plugin_name,
                    state=FAILED_ACTIVATION_STATE,
                    message=str(exc),
                )
                logger.exception("Plugin '%s' activation failed", plugin_name)
                continue

            self._contexts[plugin_name] = context
            self._activation_order.append(plugin_name)
            self._set_status(
                plugin_name,
                state=ACTIVE_PLUGIN_STATE,
                message="",
                active=True,
            )

        self.hook_registry.freeze()

    def deactivate_all(self) -> None:
        """Deactivate plugins in reverse activation order."""
        for plugin_name in reversed(self._activation_order):
            plugin = self._plugins.get(plugin_name)
            if plugin is None:
                continue
            try:
                plugin.deactivate()
            except Exception:
                logger.exception("Plugin '%s' deactivation failed", plugin_name)
            self._set_status(
                plugin_name,
                state=INACTIVE_PLUGIN_STATE,
                message="",
                active=False,
            )
        self._activation_order = []

    def list_status(self) -> List[PluginStatus]:
        """Return plugin statuses sorted by plugin name."""
        return [self._statuses[name] for name in sorted(self._statuses.keys())]

    def is_active(self, name: str) -> bool:
        """Return True when plugin is active."""
        status = self._statuses.get(name)
        return bool(status and status.active and status.state == ACTIVE_PLUGIN_STATE)

    def get_plugin(self, name: str) -> Optional[AskyPlugin]:
        """Return plugin instance by name."""
        return self._plugins.get(name)

    def has_enabled_plugins(self) -> bool:
        """Return whether manifest contains any enabled plugins."""
        return any(manifest.enabled for manifest in self._manifests.values())

    def _ensure_roster_file(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if self.roster_path.exists():
            return
        try:
            self.roster_path.write_bytes(_BUNDLED_PLUGINS_TOML.read_bytes())
            logger.info("Created plugin roster template at %s", self.roster_path)
        except Exception:
            logger.exception("Failed to create plugin roster template at %s", self.roster_path)

    def _set_status(
        self,
        plugin_name: str,
        *,
        state: str,
        message: str,
        active: Optional[bool] = None,
    ) -> None:
        status = self._statuses.get(plugin_name)
        if status is None:
            status = PluginStatus(name=plugin_name, enabled=True)
            self._statuses[plugin_name] = status

        status.state = state
        status.message = message
        if active is not None:
            status.active = active

    def _resolve_dependency_order(self) -> List[str]:
        enabled_names = {
            name for name, manifest in self._manifests.items() if manifest.enabled
        }

        # Early dependency validation for unknown/disabled dependencies.
        valid_names: Set[str] = set()
        for name in sorted(enabled_names):
            manifest = self._manifests[name]
            invalid_dependency = None
            for dependency in manifest.dependencies:
                dependency_manifest = self._manifests.get(dependency)
                if dependency_manifest is None:
                    invalid_dependency = f"unknown dependency '{dependency}'"
                    break
                if not dependency_manifest.enabled:
                    invalid_dependency = f"dependency '{dependency}' is disabled"
                    break
            if invalid_dependency:
                self._set_status(
                    name,
                    state=FAILED_DEPENDENCY_STATE,
                    message=invalid_dependency,
                )
                continue
            valid_names.add(name)

        adjacency: Dict[str, Set[str]] = {name: set() for name in valid_names}
        indegree: Dict[str, int] = {name: 0 for name in valid_names}

        for name in sorted(valid_names):
            manifest = self._manifests[name]
            for dependency in manifest.dependencies:
                if dependency not in valid_names:
                    continue
                adjacency[dependency].add(name)
                indegree[name] += 1

        available = sorted([name for name, degree in indegree.items() if degree == 0])
        order: List[str] = []
        while available:
            current = available.pop(0)
            order.append(current)
            for dependent in sorted(adjacency.get(current, set())):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    available.append(dependent)
                    available.sort()

        cycle_nodes = sorted(set(valid_names) - set(order))
        for name in cycle_nodes:
            self._set_status(
                name,
                state=FAILED_DEPENDENCY_STATE,
                message="dependency cycle detected",
            )

        # Skip plugins depending on failed dependency nodes.
        failed_names = {
            name
            for name, status in self._statuses.items()
            if status.state in {FAILED_DEPENDENCY_STATE, FAILED_MANIFEST_STATE}
        }
        if failed_names:
            for name in order:
                manifest = self._manifests[name]
                failed_dependency = next(
                    (dependency for dependency in manifest.dependencies if dependency in failed_names),
                    None,
                )
                if failed_dependency is not None:
                    self._set_status(
                        name,
                        state=SKIPPED_DEPENDENCY_STATE,
                        message=f"dependency '{failed_dependency}' failed",
                    )

        return order

    def _first_failed_dependency(self, manifest: PluginManifest) -> Optional[str]:
        for dependency in manifest.dependencies:
            if dependency not in self._manifests:
                return dependency
            dep_status = self._statuses.get(dependency)
            if dep_status is None:
                return dependency
            if dep_status.state not in {
                "loaded",
                IMPORTED_PLUGIN_STATE,
                ACTIVE_PLUGIN_STATE,
                INACTIVE_PLUGIN_STATE,
                DISABLED_PLUGIN_STATE,
            }:
                return dependency
            if dep_status.state == DISABLED_PLUGIN_STATE:
                return dependency
            if dep_status.state == INACTIVE_PLUGIN_STATE and dependency not in self._activation_order:
                return dependency
        return None

    def _get_plugin_data_dir(self, plugin_name: str) -> Path:
        return self.plugin_data_root / plugin_name

    def _load_plugin_config(self, manifest: PluginManifest) -> Dict[str, Any]:
        if not manifest.config_file:
            return {}

        config_path = (self.plugin_config_root / manifest.config_file).expanduser()
        if not config_path.exists():
            return {}

        with config_path.open("rb") as file_obj:
            loaded = tomllib.load(file_obj)

        if not isinstance(loaded, dict):
            return {}
        return loaded

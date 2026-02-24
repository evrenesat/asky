"""Plugin runtime assembly and process-level caching."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from asky.plugins.hooks import HookRegistry
from asky.plugins.manager import PluginManager

logger = logging.getLogger(__name__)


@dataclass
class PluginRuntime:
    """Container for manager + hook registry."""

    manager: PluginManager
    hooks: HookRegistry

    def shutdown(self) -> None:
        """Deactivate all active plugins."""
        self.manager.deactivate_all()


def create_plugin_runtime(config_dir: Optional[Path] = None) -> Optional[PluginRuntime]:
    """Create and fully initialize plugin runtime from local roster."""
    hooks = HookRegistry()
    manager = PluginManager(hook_registry=hooks, config_dir=config_dir)
    manager.load_roster()
    if not manager.has_enabled_plugins():
        return None

    manager.discover_and_import()
    manager.activate_all()
    return PluginRuntime(manager=manager, hooks=hooks)


_RUNTIME_LOCK = threading.Lock()
_RUNTIME_CACHE: Optional[PluginRuntime] = None
_RUNTIME_INITIALIZED = False


def get_or_create_plugin_runtime(
    *,
    config_dir: Optional[Path] = None,
    force_reload: bool = False,
) -> Optional[PluginRuntime]:
    """Return cached runtime or create one once per process."""
    global _RUNTIME_CACHE, _RUNTIME_INITIALIZED

    with _RUNTIME_LOCK:
        if force_reload and _RUNTIME_CACHE is not None:
            _RUNTIME_CACHE.shutdown()
            _RUNTIME_CACHE = None
            _RUNTIME_INITIALIZED = False

        if _RUNTIME_INITIALIZED:
            return _RUNTIME_CACHE

        runtime = create_plugin_runtime(config_dir=config_dir)
        _RUNTIME_CACHE = runtime
        _RUNTIME_INITIALIZED = True
        if runtime is None:
            logger.debug("Plugin runtime disabled (no enabled plugins in roster)")
        else:
            logger.info(
                "Plugin runtime initialized with %d status entries",
                len(runtime.manager.list_status()),
            )
        return runtime

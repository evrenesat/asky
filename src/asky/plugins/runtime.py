"""Plugin runtime assembly and process-level caching."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from asky.plugins.hooks import HookRegistry
from asky.plugins.manager import PluginManager

logger = logging.getLogger(__name__)


@dataclass
class PluginRuntime:
    """Container for manager + hook registry."""

    manager: PluginManager
    hooks: HookRegistry
    _startup_warnings: List[str] = field(default_factory=list)

    def get_startup_warnings(self) -> List[str]:
        """Return warnings collected at startup (e.g. dependency issues)."""
        return list(self._startup_warnings)

    def shutdown(self) -> None:
        """Deactivate all active plugins."""
        self.manager.deactivate_all()


def _handle_dependency_issues(manager: PluginManager) -> List[str]:
    """Surface dependency issues; prompt to enable in interactive mode.

    Returns warning strings for non-interactive contexts so they can be
    forwarded to the tray UI.
    """
    issues = manager.get_dependency_issues()
    if not issues:
        return []

    from asky.daemon.launch_context import is_interactive

    warnings: List[str] = []
    for issue in issues:
        if issue.reason == "disabled" and is_interactive():
            try:
                answer = input(
                    f"Plugin '{issue.plugin_name}' requires '{issue.dep_name}'"
                    " which is disabled. Enable it? [y/N] "
                )
            except (EOFError, OSError):
                answer = ""
            if answer.strip().lower() == "y":
                manager.enable_plugin(issue.dep_name)
                continue

        if issue.reason == "disabled":
            hint = (
                f"To enable: set enabled = true for '{issue.dep_name}' in plugins.toml."
            )
        else:
            hint = ""

        msg = (
            f"Plugin '{issue.plugin_name}' requires '{issue.dep_name}'"
            f" ({issue.reason})."
            + (f" {hint}" if hint else "")
        )
        warnings.append(msg)
        logger.warning(msg)
    return warnings


def create_plugin_runtime(config_dir: Optional[Path] = None) -> Optional[PluginRuntime]:
    """Create and fully initialize plugin runtime from local roster."""
    hooks = HookRegistry()
    manager = PluginManager(hook_registry=hooks, config_dir=config_dir)
    manager.load_roster()
    if not manager.has_enabled_plugins():
        return None

    startup_warnings = _handle_dependency_issues(manager)
    manager.discover_and_import()
    manager.activate_all()
    runtime = PluginRuntime(manager=manager, hooks=hooks)
    runtime._startup_warnings = startup_warnings
    return runtime


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

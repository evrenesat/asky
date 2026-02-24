# Plugin System API Specification

Companion to [plugin-system.md](plugin-system.md). This document defines the exact classes, protocols, and contracts that implementors must follow.

---

## AskyPlugin Base Class

```python
# src/asky/plugins/base.py

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging


@dataclass
class PluginContext:
    """Passed to plugin.activate(). Provides access to Asky internals."""

    config: Dict[str, Any]
    """Plugin-specific config from plugins/<name>.toml."""

    global_config: Dict[str, Any]
    """Read-only snapshot of the full Asky config."""

    data_dir: Path
    """Plugin-specific persistent data directory (~/.config/asky/plugins/<name>/)."""

    hooks: "HookRegistry"
    """Hook registry for subscribing to pipeline events."""

    logger: logging.Logger
    """Logger scoped to this plugin (asky.plugins.<name>)."""


class AskyPlugin(ABC):
    """Base class for all Asky plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier. Must match the key in plugins.toml."""

    @property
    def version(self) -> str:
        """Semantic version string."""
        return "0.1.0"

    @property
    def dependencies(self) -> List[str]:
        """List of plugin names this plugin depends on (loaded first)."""
        return []

    @abstractmethod
    def activate(self, context: PluginContext) -> None:
        """Called once at startup. Register hooks, tools, servers here."""

    def deactivate(self) -> None:
        """Called at shutdown. Clean up resources. Optional override."""
```

---

## PluginManager

```python
# src/asky/plugins/manager.py (key interface — not full implementation)

class PluginManager:
    """Discovers, loads, orders, and manages plugin lifecycles."""

    def __init__(self, config: Dict[str, Any], config_dir: Path) -> None:
        """
        Args:
            config: The full Asky config dict (result of load_config()).
            config_dir: Path to ~/.config/asky/ (for plugin config/data dirs).
        """

    @property
    def hook_registry(self) -> HookRegistry:
        """The shared hook registry used by all plugins."""

    def discover_and_load(self) -> None:
        """
        Read plugins.toml, import plugin modules, instantiate AskyPlugin subclasses.
        Skips disabled plugins. Logs errors for bad modules without raising.
        """

    def activate_all(self) -> None:
        """
        Topologically sort by dependencies, then call activate(context) on each.
        Creates data dirs on first activation.
        If a plugin raises during activate(), log error, mark it failed, continue.
        """

    def deactivate_all(self) -> None:
        """Call deactivate() on all active plugins in reverse activation order."""

    def get_plugin(self, name: str) -> Optional[AskyPlugin]:
        """Retrieve an active plugin by name. Returns None if not found/failed."""

    def is_active(self, name: str) -> bool:
        """Check if a plugin is loaded and successfully activated."""
```

---

## HookRegistry

```python
# src/asky/plugins/hooks.py (key interface)

from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

# Hook point constants
TOOL_REGISTRY_BUILD = "tool_registry_build"
SYSTEM_PROMPT_EXTEND = "system_prompt_extend"
PRE_LLM_CALL = "pre_llm_call"
POST_LLM_RESPONSE = "post_llm_response"
PRE_TOOL_EXECUTE = "pre_tool_execute"
POST_TOOL_EXECUTE = "post_tool_execute"
DAEMON_SERVER_REGISTER = "daemon_server_register"
CONFIG_LOADED = "config_loaded"
SESSION_START = "session_start"
SESSION_END = "session_end"
PRE_PRELOAD = "pre_preload"
POST_PRELOAD = "post_preload"

HookCallback = Callable[..., Any]


class HookRegistry:
    """Central registry for pipeline hook subscriptions."""

    def register(
        self,
        hook_point: str,
        callback: HookCallback,
        priority: int = 100,
        plugin_name: Optional[str] = None,
    ) -> None:
        """
        Subscribe to a hook point.

        Args:
            hook_point: One of the hook point constants.
            callback: Callable invoked when the hook fires.
            priority: Lower = earlier execution. Default 100.
            plugin_name: For debugging/logging. Auto-set during plugin activation.
        """

    def unregister(self, hook_point: str, callback: HookCallback) -> None:
        """Remove a subscription."""

    def invoke(self, hook_point: str, **payload: Any) -> None:
        """
        Fire a hook point. All subscribers called in priority order.
        Exceptions in callbacks are logged but don't propagate.

        Usage: hooks.invoke(TOOL_REGISTRY_BUILD, registry=registry)
        """

    def invoke_chain(self, hook_point: str, data: Any, **context: Any) -> Any:
        """
        Sequential pipeline invocation. Each callback receives the output
        of the previous one as its first argument.

        Usage: prompt = hooks.invoke_chain(SYSTEM_PROMPT_EXTEND, data=prompt, config=config)

        Returns:
            The final transformed data value.
        """

    def freeze(self) -> None:
        """
        Called after all plugins are activated. Prevents further registrations.
        Invocation remains unlocked (thread-safe reads on frozen data).
        """
```

---

## Plugin Configuration Contract

### `plugins.toml` (main plugin roster)

Location: `~/.config/asky/plugins.toml`

```toml
# Each [plugin.<name>] section declares a plugin.
# "module" is the Python dotted path to the package containing the AskyPlugin subclass.
# "enabled" controls whether the plugin is loaded.

[plugin.manual_persona_creator]
enabled = true
module = "asky.plugins.persona_creator"

[plugin.persona_manager]
enabled = true
module = "asky.plugins.persona_manager"

[plugin.gui_server]
enabled = false
module = "asky.plugins.gui_server"

[plugin.puppeteer_browser]
enabled = false
module = "asky.plugins.puppeteer_browser"
```

### Per-plugin config: `~/.config/asky/plugins/<name>.toml`

Each plugin can have its own TOML file. The contents are passed as `PluginContext.config`.

```toml
# Example: ~/.config/asky/plugins/gui_server.toml
host = "127.0.0.1"
port = 8765
auth_enabled = false
```

### Plugin module contract

Each plugin module (e.g., `asky.plugins.persona_creator`) must contain exactly one class that subclasses `AskyPlugin`. The `PluginManager` finds it via:

```python
for obj in vars(module).values():
    if isinstance(obj, type) and issubclass(obj, AskyPlugin) and obj is not AskyPlugin:
        return obj()
```

If multiple subclasses exist, the first found is used (non-deterministic — avoid this). If none found, the module is skipped with a warning.

---

## Tool Registration via Plugin

Plugins register tools during `TOOL_REGISTRY_BUILD`. The callback receives the `ToolRegistry` instance.

```python
class MyPlugin(AskyPlugin):
    name = "my_plugin"

    def activate(self, ctx: PluginContext) -> None:
        ctx.hooks.register(TOOL_REGISTRY_BUILD, self._register_tools)

    def _register_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            name="my_tool",
            schema={
                "name": "my_tool",
                "description": "Does something useful.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The query."}
                    },
                    "required": ["query"],
                },
                "system_prompt_guideline": "Use my_tool when the user asks about X.",
            },
            executor=self._execute_my_tool,
        )

    def _execute_my_tool(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"result": f"Processed: {args['query']}"}
```

---

## Daemon Server Registration via Plugin

Plugins register additional servers during `DAEMON_SERVER_REGISTER`. The callback receives a `DaemonContext` with methods to register servers.

```python
@dataclass
class DaemonServerSpec:
    """Specification for a daemon server to be started alongside XMPP."""

    name: str
    """Unique server name for logging/status."""

    start: Callable[[], None]
    """Called to start the server (should be non-blocking or run in a thread)."""

    stop: Callable[[], None]
    """Called to stop the server on shutdown."""

    is_running: Callable[[], bool]
    """Health check."""


class GUIServerPlugin(AskyPlugin):
    name = "gui_server"

    def activate(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        ctx.hooks.register(DAEMON_SERVER_REGISTER, self._register_server)

    def _register_server(self, daemon_service: Any, servers: List[DaemonServerSpec]) -> None:
        servers.append(DaemonServerSpec(
            name="gui_server",
            start=self._start_gui,
            stop=self._stop_gui,
            is_running=self._is_gui_running,
        ))
```

---

## Error Handling Contract

1. **Plugin loading errors** (import failures, missing class): logged at ERROR level, plugin skipped, other plugins unaffected.
2. **Plugin activation errors**: logged at ERROR level, plugin marked as failed, dependents also skipped.
3. **Hook callback errors**: logged at WARNING level, other callbacks for the same hook still execute.
4. **Plugin deactivation errors**: logged at WARNING level, deactivation continues for remaining plugins.

No plugin error ever raises to the user or crashes Asky.

---

## Thread Safety Contract

- `HookRegistry.register()` and `unregister()` are protected by a `threading.Lock`.
- After `freeze()`, the internal data structures are immutable. `invoke()` and `invoke_chain()` are lock-free.
- Plugin `activate()` is called from the main thread, sequentially.
- Hook callbacks may be invoked from daemon worker threads. Plugins must handle their own internal thread safety if they maintain mutable state.

# Plugin System API Specification (Revised)

Companion to [plugin-system.md](plugin-system.md). This file defines the concrete runtime contracts for implementation.

---

## Version Scope

This spec is for plugin-system v1 (initial rollout). It is intentionally strict on determinism and failure isolation.

---

## Terminology

- **Plugin manifest**: one roster entry from `plugins.toml`.
- **Plugin runtime**: active `PluginManager` + `HookRegistry` passed through chat/daemon flows.
- **Hook context**: typed payload object for a hook call.
- **Capability**: declared permission bucket for what a plugin can do.

---

## Manifest Contract

`plugins.toml` lives at `~/.config/asky/plugins.toml`.

### Required Fields

- `enabled` (`bool`)
- `module` (`str`)

### Recommended/Optional Fields

- `class` (`str`) - recommended for deterministic class loading
- `dependencies` (`list[str]`)
- `capabilities` (`list[str]`)
- `config_file` (`str`) - defaults to `plugins/<name>.toml`

### Example

```toml
[plugin.manual_persona_creator]
enabled = true
module = "asky.plugins.persona_creator.plugin"
class = "ManualPersonaCreatorPlugin"
dependencies = []
capabilities = ["tool_registry", "prompt", "preload"]
config_file = "plugins/manual_persona_creator.toml"

[plugin.gui_server]
enabled = false
module = "asky.plugins.gui_server.plugin"
class = "GUIServerPlugin"
dependencies = []
capabilities = ["daemon_server"]
```

### Dataclass

```python
@dataclass(frozen=True)
class PluginManifest:
    name: str
    enabled: bool
    module: str
    class_name: str | None = None
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    config_file: str | None = None
```

---

## Capability Constants

```python
CAP_TOOL_REGISTRY = "tool_registry"
CAP_PROMPT = "prompt"
CAP_PRELOAD = "preload"
CAP_LLM_IO = "llm_io"
CAP_TOOL_EXEC = "tool_exec"
CAP_DAEMON_SERVER = "daemon_server"
CAP_TURN_LIFECYCLE = "turn_lifecycle"
```

Manager must warn when plugin registers hook points outside declared capabilities.

---

## Plugin Base Contract

```python
# src/asky/plugins/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import logging


@dataclass(frozen=True)
class PluginContext:
    manifest: PluginManifest
    plugin_config: Mapping[str, Any]
    global_config: Mapping[str, Any]
    data_dir: Path
    hooks: "HookRegistry"
    logger: logging.Logger


class AskyPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Must match manifest name."""

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def dependencies(self) -> tuple[str, ...]:
        return ()

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ()

    @abstractmethod
    def activate(self, context: PluginContext) -> None:
        """Register hooks, initialize state, validate config."""

    def deactivate(self) -> None:
        """Best-effort cleanup. Must not raise fatal errors."""
```

---

## Plugin Runtime and Manager

```python
@dataclass(frozen=True)
class PluginRuntime:
    manager: "PluginManager"
    hooks: "HookRegistry"


class PluginManager:
    def __init__(self, *, global_config: Mapping[str, Any], config_dir: Path) -> None: ...

    @property
    def hook_registry(self) -> "HookRegistry": ...

    def load_roster(self) -> list[PluginManifest]: ...
    def discover_and_import(self) -> None: ...
    def activate_all(self) -> None: ...
    def deactivate_all(self) -> None: ...

    def get_plugin(self, name: str) -> AskyPlugin | None: ...
    def is_active(self, name: str) -> bool: ...
    def list_status(self) -> list["PluginStatus"]: ...
```

### Deterministic Ordering

Activation order is:

1. topological dependency order,
2. then plugin name ascending for ties.

### Plugin Status Contract

```python
@dataclass(frozen=True)
class PluginStatus:
    name: str
    state: str  # discovered|loaded|active|failed|disabled|skipped_dependency
    reason: str | None = None
    version: str | None = None
```

---

## Hook Registry Contract

```python
HookCallback = Callable[..., Any]

@dataclass(frozen=True)
class HookSubscription:
    hook_point: str
    callback: HookCallback
    priority: int
    plugin_name: str
    order: int


class HookRegistry:
    def register(
        self,
        hook_point: str,
        callback: HookCallback,
        *,
        priority: int = 100,
        plugin_name: str,
    ) -> None: ...

    def unregister(self, hook_point: str, callback: HookCallback) -> None: ...
    def invoke(self, hook_point: str, **payload: Any) -> None: ...
    def invoke_chain(self, hook_point: str, data: Any, **context: Any) -> Any: ...
    def freeze(self) -> None: ...
```

### Ordering Rules

Callbacks execute in ascending order of:

1. `priority`
2. `plugin_name`
3. registration `order`

### Error Rules

- Callback exceptions are logged with plugin + hook metadata.
- Other callbacks for the same hook continue.
- Exceptions do not propagate to user-facing turn execution.

---

## Integration Contracts (Call Sites)

## AskyClient

```python
class AskyClient:
    def __init__(
        self,
        config: AskyConfig,
        *,
        usage_tracker: UsageTracker | None = None,
        summarization_tracker: UsageTracker | None = None,
        plugin_runtime: PluginRuntime | None = None,
    ) -> None: ...
```

Hook call sites in `src/asky/api/client.py`:

- `SESSION_RESOLVED`
- `PRE_PRELOAD`
- `POST_PRELOAD`
- `SYSTEM_PROMPT_EXTEND` (chain)
- `TURN_COMPLETED`

## Tool Registry Factory

Factory functions accept optional hook registry:

```python
def create_tool_registry(..., hook_registry: HookRegistry | None = None) -> ToolRegistry: ...
def create_research_tool_registry(..., hook_registry: HookRegistry | None = None) -> ToolRegistry: ...
```

Call `TOOL_REGISTRY_BUILD` after built-ins/custom tools are registered and before return.

## Conversation Engine

`src/asky/core/engine.py` invokes:

- `PRE_LLM_CALL`
- `POST_LLM_RESPONSE`

## Tool Dispatch

`src/asky/core/registry.py` invokes:

- `PRE_TOOL_EXECUTE`
- `POST_TOOL_EXECUTE`

## Daemon Service

`src/asky/daemon/service.py` invokes:

- `DAEMON_SERVER_REGISTER`

---

## Plugin Config and Data Contract

For plugin `<name>`:

- config file: `~/.config/asky/plugins/<name>.toml`
- data directory: `~/.config/asky/plugins/<name>/`

`PluginContext.plugin_config` receives parsed TOML mapping (or `{}` if missing).

`PluginContext.global_config` is read-only and must not mutate `asky.config` module exports.

---

## Class Resolution Contract

Preferred:

- use manifest `class` field and resolve exact class by name.

Fallback (only when `class` missing):

- module must contain exactly one `AskyPlugin` subclass.
- 0 or >1 matches -> plugin load error.

This avoids non-deterministic "first class found" behavior.

---

## Error Handling Contract

1. **Roster parse/import/class resolution** errors -> plugin marked `failed`, startup continues.
2. **Activation** error -> plugin marked `failed`, dependents marked `skipped_dependency`.
3. **Hook callback** error -> warning log, continue same hook chain/invoke sequence.
4. **Deactivation** error -> warning log, continue reverse shutdown.

No plugin exception should crash normal turn execution.

---

## Thread-Safety Contract

1. `register`/`unregister` are lock-protected.
2. After `freeze`, subscription lists are immutable snapshots.
3. `invoke`/`invoke_chain` are lock-free reads over frozen snapshots.
4. Hook callbacks may run on daemon worker threads; plugin internals must guard mutable shared state.

---

## Test Contract

Minimum dedicated tests:

- `tests/test_plugin_manager.py`
- `tests/test_plugin_hooks.py`
- `tests/test_plugin_integration.py`
- `tests/test_plugin_daemon_integration.py`
- `tests/test_plugin_config.py`

All run commands use `uv`:

```bash
uv run pytest tests/test_plugin_manager.py -v
uv run pytest tests/test_plugin_hooks.py -v
uv run pytest tests/test_plugin_integration.py -v
uv run pytest tests/test_plugin_daemon_integration.py -v
uv run pytest tests/test_plugin_config.py -v
uv run pytest
```

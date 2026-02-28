---
name: asky-plugin-dev
description: >
  Guide for creating asky plugins — Python packages that extend the asky CLI and daemon
  through a hook-based plugin system. Use this skill when asked to build, scaffold, or
  modify an asky plugin; when a user wants to integrate an external CLI tool (ffmpeg,
  yt-dlp, ImageMagick, etc.) into asky; when adding XMPP-triggered automation; when
  registering custom LLM tools; or when wiring post-turn output delivery (email, webhook,
  etc.). Covers directory layout, manifest entry, hook registration, LLM tool registration,
  external-process patterns, XMPP file handling, configuration, data storage, and testing.
---

# Asky Plugin Dev

## Quick Start (5 steps)

1. Create `src/asky/plugins/<plugin_name>/` with `__init__.py` and `plugin.py`.
2. Subclass `AskyPlugin`, implement `activate()`, register hooks.
3. Add a `[plugin.<name>]` block to `~/.config/asky/plugins.toml`.
4. Write tests under `src/asky/plugins/<plugin_name>/tests/` or `tests/plugins/`.
5. Run `uv run pytest -x -q` to verify no regressions.

## Directory Layout

```
src/asky/plugins/
└── my_plugin/
    ├── __init__.py      # empty
    ├── plugin.py        # AskyPlugin subclass (required)
    └── tests/           # optional, or put tests in tests/plugins/
```

No other files are required. Add `worker.py`, `config.py`, etc. only when the logic warrants.

## plugins.toml Manifest Entry

Path: `~/.config/asky/plugins.toml`

```toml
[plugin.my_plugin]
enabled = true
module  = "asky.plugins.my_plugin.plugin"
class   = "MyPlugin"
# optional:
# dependencies = ["other_plugin"]
# config_file  = "plugins/my_plugin.toml"   # relative to ~/.config/asky/
```

## Minimal Plugin Skeleton

```python
from __future__ import annotations
from typing import Optional
from asky.plugins.base import AskyPlugin, PluginContext

class MyPlugin(AskyPlugin):
    def __init__(self) -> None:
        self._ctx: Optional[PluginContext] = None

    def activate(self, context: PluginContext) -> None:
        self._ctx = context
        context.hook_registry.register(
            "HOOK_NAME",
            self._on_hook,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._ctx = None

    def _on_hook(self, payload) -> None:
        ...  # mutate payload in-place
```

`PluginContext` fields:

| Field | Type | Contents |
|---|---|---|
| `plugin_name` | str | name from manifest |
| `config_dir` | Path | `~/.config/asky/` |
| `data_dir` | Path | `~/.config/asky/plugins/<name>/` |
| `config` | Mapping | loaded from `config_file` TOML or `{}` |
| `hook_registry` | HookRegistry | register hooks here |
| `logger` | Logger | pre-configured for this plugin |

## Hook Selection Guide

| Goal | Hook constant | Payload type |
|---|---|---|
| Add LLM tools | `TOOL_REGISTRY_BUILD` | `ToolRegistryBuildContext` |
| Append to system prompt | `SYSTEM_PROMPT_EXTEND` | `str` (chain — return new str) |
| Act after final answer (email, push) | `POST_TURN_RENDER` | `PostTurnRenderContext` |
| Intercept URL fetch | `FETCH_URL_OVERRIDE` | `FetchURLContext` |
| Modify query before retrieval | `PRE_PRELOAD` | `PrePreloadContext` |
| Register a background sidecar server | `DAEMON_SERVER_REGISTER` | `DaemonServerRegisterContext` |
| Register the daemon transport | `DAEMON_TRANSPORT_REGISTER` | `DaemonTransportRegisterContext` |
| Add macOS tray menu entries | `TRAY_MENU_REGISTER` | `TrayMenuRegisterContext` |

Full payload field reference: see `references/hooks.md`.

## Registering LLM Tools (most common for external-tool plugins)

```python
from asky.plugins.hook_types import TOOL_REGISTRY_BUILD, ToolRegistryBuildContext

def activate(self, context: PluginContext) -> None:
    self._ctx = context
    context.hook_registry.register(
        TOOL_REGISTRY_BUILD,
        self._on_tool_registry_build,
        plugin_name=context.plugin_name,
    )

def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
    if "my_tool" in payload.disabled_tools:
        return
    payload.registry.register(
        "my_tool",
        {
            "name": "my_tool",
            "description": "What this tool does (seen by the LLM).",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input value."},
                },
                "required": ["input"],
            },
        },
        self._execute_my_tool,
    )

def _execute_my_tool(self, arguments: dict) -> dict:
    value = str(arguments.get("input", "")).strip()
    # ... do work ...
    return {"result": "...", "error": None}
```

The executor return dict is serialised and sent back to the LLM as the tool result.

## External Process Plugins (ffmpeg, yt-dlp, etc.)

See `references/external-tools.md` for complete worked examples:
- **yt-dlp plugin**: download YouTube URLs when the LLM decides it is needed
- **ffmpeg plugin**: transcode / process files sent via XMPP OOB URL
- Error handling, data_dir file storage, and subprocess safety patterns

## CLI Contributions (optional)

```python
from asky.plugins.base import CapabilityCategory, CLIContribution

@classmethod
def get_cli_contributions(cls) -> list[CLIContribution]:
    return [
        CLIContribution(
            category=CapabilityCategory.OUTPUT_DELIVERY,
            flags=("--my-flag",),
            kwargs=dict(action="store_true", help="Enable my feature."),
        ),
    ]
```

CLI flag categories: `OUTPUT_DELIVERY`, `SESSION_CONTROL`, `BROWSER_SETUP`, `BACKGROUND_SERVICE`.

Read the flag value in `POST_TURN_RENDER` via `ctx.cli_args.my_flag`.

## Config & Data Storage

**Config** (`config_file` in manifest, TOML, auto-loaded into `context.config`):

```python
host = str(context.config.get("host", "localhost"))
port = int(context.config.get("port", 9000))
```

**File storage** (use `context.data_dir`; directory is pre-created by the runtime):

```python
output_path = context.data_dir / "downloads" / "file.mp4"
output_path.parent.mkdir(parents=True, exist_ok=True)
```

**KV store** (SQLite, auto-scoped to this plugin):

```python
from asky.plugins.kvstore import PluginKVStore
store = PluginKVStore(context.plugin_name)
store.set("key", {"data": 1})
value = store.get("key")
```

## Testing

See `references/testing.md` for full test scaffold and mock patterns. Minimal fixture:

```python
from asky.plugins.manager import PluginManager

def test_activates(tmp_path):
    (tmp_path / "plugins.toml").write_text("""
[plugin.my_plugin]
enabled = true
module  = "asky.plugins.my_plugin.plugin"
class   = "MyPlugin"
""")
    mgr = PluginManager(config_dir=tmp_path)
    mgr.load_roster()
    mgr.discover_and_import()
    mgr.activate_all()
    assert any(s.name == "my_plugin" and s.state == "active"
               for s in mgr.list_status())
```

## One-Way Dependency Rule

Core code (`asky.daemon.*`, `asky.core.*`) must never import from individual plugin packages.
Plugins may import from `asky.daemon.errors` only. All business logic lives inside the plugin directory.

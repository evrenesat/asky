# Plugins Package (`asky/plugins/`)

Optional plugin runtime for asky.

## Module Overview

| Module | Purpose |
| --- | --- |
| `manifest.py` | Plugin roster entry validation (`plugins.toml`) |
| `manager.py` | Plugin discovery, import, dependency order, lifecycle |
| `hooks.py` | Ordered hook registration and invocation |
| `hook_types.py` | Hook constants and mutable payload contracts |
| `runtime.py` | Runtime bootstrap and process-level cache |
| `base.py` | `AskyPlugin`, `PluginContext`, `PluginStatus`, `CLIContribution`, `CapabilityCategory` contracts |

## Plugin Boundary Rule

**One-way dependency:** core code may import only the plugin infrastructure from `asky.plugins.runtime` or `asky.plugins.hooks`. Core code must not import individual plugin packages.

Each plugin owns its own business logic. CLI flags, hook handlers, browser routes, transport integrations, and service helpers should stay inside the owning plugin package.

## GUI Extension Contract

asky's browser UI has one host: `gui_server`.

That means:

- `gui_server` is the only plugin that owns NiceGUI lifecycle and `ui.run(...)`.
- Extension plugins must not start their own NiceGUI app.
- Extension plugins must not register extension routes with direct `@ui.page(...)`.
- Extension plugins contribute browser UI through `GUI_EXTENSION_REGISTER`.
- Browser UI is currently an authenticated admin/review console, not a second chat surface.

Current split of responsibilities:

- `gui_server` owns:
  - daemon sidecar lifecycle
  - authentication and middleware
  - shared layout shell
  - extension-page mounting
  - queue bootstrap and jobs page
- owning plugins own:
  - route registration through `GUIPageSpec`
  - render functions
  - service adapters
  - job handlers for domain-specific long-running work

Use this contract:

```python
from asky.plugins.hook_types import GUIPageSpec

def _on_gui_extension_register(payload) -> None:
    payload.register_page(
        GUIPageSpec(
            route="/my-plugin/{item_id}",
            title="My Plugin: {item_id}",
            render=_render_item_page,
            nav_title="My Plugin",
        )
    )

    payload.register_job_handler("my_plugin_job", _run_my_plugin_job)
```

`GUIPageSpec` remains:

- `route`
- `title`
- `render`
- `nav_title=None`

`render` receives the NiceGUI `ui` module plus any path parameters extracted from the route.

## GUI Development Rules

When adding browser UI from a plugin:

1. Put domain logic in a service layer or existing domain module.
2. Register a page through `GUI_EXTENSION_REGISTER`.
3. Keep render functions thin and UI-focused.
4. Use `JobQueue` for long-running or durable work.
5. Use direct page handlers only for small immediate actions.

Do not:

- call CLI handlers from browser code just to reuse behavior
- perform ingestion, crawling, or LLM-heavy work inline in page callbacks
- bypass the shared auth and host shell
- document or build browser-chat features unless the architecture changes explicitly

## Plugin CLI Contributions

Plugins declare CLI flags via the `get_cli_contributions()` classmethod on `AskyPlugin`. This is a classmethod so flags can be collected before activation. Flags are grouped by `CapabilityCategory`:

| Category constant | `--help` group title | Intended use |
| --- | --- | --- |
| `OUTPUT_DELIVERY` | Output Delivery | Actions applied to the final answer |
| `SESSION_CONTROL` | Session & Query | Query and session behavior modifiers |
| `BROWSER_SETUP` | Browser Setup | Browser auth and extension configuration |
| `BACKGROUND_SERVICE` | Background Services | Daemon process launch flags |

Example contribution:

```python
@classmethod
def get_cli_contributions(cls) -> list[CLIContribution]:
    return [
        CLIContribution(
            category=CapabilityCategory.OUTPUT_DELIVERY,
            flags=("--sendmail",),
            kwargs=dict(
                metavar="RECIPIENTS",
                help="Send the final answer via email.",
            ),
        ),
    ]
```

`PluginManager.collect_cli_contributions()` light-imports enabled plugin classes and collects contributions without calling `activate()`. Import errors per plugin are logged and skipped.

Plugins can also declare static CLI guidance hints via `get_cli_hint_contributions(cls, context: CLIHintContext) -> list[CLIHint]`.

Internal process-spawning flags like `--xmpp-daemon`, `--edit-daemon`, and `--xmpp-menubar-child` stay registered in core because the CLI translation pipeline depends on them regardless of plugin state.

## Hook Ordering

Hook callbacks run in deterministic order:

1. `priority` ascending
2. `plugin_name` ascending
3. `registration_index` ascending

Hook callback exceptions are logged and isolated so remaining callbacks still run.

## v1 Hook Surface

- `TOOL_REGISTRY_BUILD`
- `SESSION_RESOLVED`
- `PRE_PRELOAD`
- `POST_PRELOAD`
- `SYSTEM_PROMPT_EXTEND`
- `PRE_LLM_CALL`
- `POST_LLM_RESPONSE`
- `PRE_TOOL_EXECUTE`
- `POST_TOOL_EXECUTE`
- `TURN_COMPLETED`
- `CLI_INLINE_HINTS_BUILD`
- `POST_TURN_RENDER`
- `DAEMON_SERVER_REGISTER`
- `DAEMON_TRANSPORT_REGISTER`
- `TRAY_MENU_REGISTER`
- `FETCH_URL_OVERRIDE`
- `PLUGIN_CAPABILITY_REGISTER`
- `LOCAL_SOURCE_HANDLER_REGISTER`
- `GUI_EXTENSION_REGISTER`

Deferred in v1:

- `CONFIG_LOADED`
- `SESSION_END`

## Built-in Plugins

- `manual_persona_creator/` for persona creation, ingestion, export, and persona-admin GUI flows
- `persona_manager/` for persona import, session binding, prompt and preload injection, and session-binding GUI flows
- `gui_server/` for the NiceGUI daemon sidecar and extension page registry
- `voice_transcriber/` for background audio transcription and `transcribe_audio_url`
- `image_transcriber/` for background image description and `transcribe_image_url`
- `xmpp_daemon/` for XMPP daemon transport
- `push_data/` for `push_data_*` tools and `--push-data`
- `email_sender/` for SMTP delivery via `--sendmail`

## Dependency Visibility

`PluginManager` records `DependencyIssue` entries during `load_roster()` for disabled or missing dependencies. `runtime.py` handles these between roster load and import:

- interactive CLI can prompt to enable disabled dependencies
- non-interactive daemon/app contexts surface startup warnings instead

`enable_plugin()` updates the in-memory manifest and atomically rewrites `plugins.toml` via `os.replace()`.

## xmpp_daemon Plugin

`xmpp_daemon/` provides the XMPP transport layer for `asky --daemon`. It registers itself via `DAEMON_TRANSPORT_REGISTER` and contributes tray menu entries via `TRAY_MENU_REGISTER`. The daemon core remains transport-agnostic.

Key modules:

| Module | Purpose |
| --- | --- |
| `plugin.py` | `XMPPDaemonPlugin` registration |
| `xmpp_service.py` | per-JID queue and XMPP client wiring |
| `xmpp_client.py` | Slixmpp transport wrapper |
| `router.py` | ingress policy and room binding |
| `command_executor.py` | command/query bridge and `AskyClient.run_turn` |
| `session_profile_manager.py` | room/session bindings and override files |
| `document_ingestion.py` | HTTPS document URL ingestion into session corpus |
| `transcript_manager.py` | transcript lifecycle and confirmations |
| `query_progress.py` | progress events and status publisher |
| `chunking.py` | outbound response chunking |
| `file_upload.py` | XEP-0363 HTTP file upload |

One-way dependency rule still applies: `xmpp_daemon` may import `asky.daemon.errors`; daemon core must not import `asky.plugins.xmpp_daemon`.

## User Entry Points

- runtime config entrypoint: `~/.config/asky/plugins.toml`
- GUI entrypoint, only when daemon is running: `http://127.0.0.1:8766/settings/general`
- persona entrypoints: `asky persona <command>` and `@mention` syntax in queries
  - no LLM tools are registered for persona operations

For user-facing usage and limitations, see `docs/plugins.md`.

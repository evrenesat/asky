# GUI Server Plugin (`plugins/gui_server/`)

`gui_server` is asky's only NiceGUI host. It runs as a daemon sidecar, owns authentication and shared browser chrome, and mounts extension pages contributed by other plugins.

## What This Plugin Owns

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint, daemon server registration, GUI extension bootstrap, tray actions |
| `server.py` | NiceGUI lifecycle, auth middleware, root/login/logout pages, storage path setup |
| `pages/layout.py` | Shared header and page shell used by all protected pages |
| `pages/plugin_registry.py` | `GUIPageSpec` normalization and safe extension-page mounting |
| `pages/general_settings.py` | Host-owned config editor for `general.toml` |
| `pages/jobs.py` | Host-owned queue visibility page |

## Host Contract

`gui_server` owns the browser host. Extension plugins do not own any of the following:

- `ui.run()` lifecycle
- `@ui.page(...)` registration for extension routes
- auth middleware
- NiceGUI persistence path
- shared layout shell
- daemon start/stop behavior
- queue bootstrap

Current boot flow:

1. `GUIServerPlugin.activate()` creates the `JobQueue`.
2. `DAEMON_SERVER_REGISTER` starts queue bootstrap and invokes `GUI_EXTENSION_REGISTER`.
3. Extension plugins register `GUIPageSpec` objects and optional job handlers.
4. `NiceGUIServer` mounts host pages plus registered extension pages.
5. `ui.run(...)` starts once, inside the host.

If you are building GUI features in another plugin, your job is to provide page specs, thin render functions, and domain job handlers. Do not create a second NiceGUI app.

## Auth And Storage Rules

The GUI is admin-only and must fail closed.

- A password is required from plugin config or `ASKY_GUI_PASSWORD`.
- If no password is available, the server raises and does not start insecurely.
- Protected-route auth is enforced in middleware.
- Middleware must return `RedirectResponse("/login")` for unauthenticated requests.
- Do not call `ui.navigate.to()` from middleware or other request-level code outside a NiceGUI page/event context.

Current auth/session state uses `app.storage.user`.

- `app.storage.user["authenticated"]` is the active auth flag.
- `app.storage.user["referrer"]` is used to return the user to the requested page after login.
- Because user/browser storage is signed, `ui.run(...)` must keep `storage_secret` configured.

Current NiceGUI persistence rules:

- `NICEGUI_STORAGE_PATH` is explicitly rooted under `context.data_dir / ".nicegui"`.
- Never rely on cwd-relative NiceGUI storage.
- Never hardcode root paths like `/.nicegui`.
- Any future persistence change must remain under asky-managed plugin data.

## Extension Page Contract

Extension plugins register through `GUI_EXTENSION_REGISTER` with this contract:

```python
from asky.plugins.hook_types import GUIPageSpec

def _on_gui_extension_register(payload) -> None:
    payload.register_page(
        GUIPageSpec(
            route="/example/{item_id}",
            title="Example: {item_id}",
            render=_render_example_page,
            nav_title="Example",
        )
    )
```

Important rules:

- Extension plugins provide `render(ui, **kwargs)` only.
- The host owns the actual `@ui.page(...)` decorator.
- Route parameters come from `GUIPageSpec.route`.
- `PluginPageRegistry` passes path parameters into the render function as keyword arguments.
- `title` may use route-format placeholders like `{name}`.
- `nav_title` is metadata today. Do not assume it automatically adds a header link.

Current route behavior matches the shared registry:

- static routes like `/sessions` render with `render(ui)`
- dynamic routes like `/personas/{name}` render with `render(ui, name=...)`
- mount failures are isolated per page so one broken extension route does not block the rest

## Execution Model

Page functions must stay thin and UI-focused.

Use immediate page handlers only for:

- local validation
- toggling page-local state
- simple service reads and small synchronous writes
- navigation and notifications

Use NiceGUI async helpers only for short-lived, non-durable work:

- `run.io_bound(...)` for brief blocking I/O that should not freeze the UI
- `run.cpu_bound(...)` for brief CPU work that would otherwise block the event loop

Use the daemon `JobQueue` for durable workflows:

- ingestion
- scraping / collection
- LLM-heavy extraction
- anything that must survive page reloads or be visible on `/jobs`
- anything with meaningful progress/error state

Do not do long-running work directly inside button handlers, dialog submit handlers, or page render functions.

## Development Flow For New GUI Features

Follow this order for new browser features:

1. Add or extend a UI-agnostic service adapter in the owning plugin.
2. Decide whether the action is immediate or queue-backed.
3. Register routes and job handlers from the owning plugin through `GUI_EXTENSION_REGISTER`.
4. Implement thin render functions under `plugins/gui_server/pages/`.
5. Reuse `page_layout` and existing host conventions.
6. Add or update tests for registration, auth, and page behavior.

Current plugin split is intentional:

- `gui_server` owns hosting, auth, queue plumbing, and shared shell
- `manual_persona_creator` owns persona admin/review flows and job handlers
- `persona_manager` owns session/persona binding pages

Do not move domain business logic into `gui_server` just because the page lives under `plugins/gui_server/pages/`.

## Job Handler Pattern

Register durable work from the owning plugin, not from page code:

```python
def _on_gui_extension_register(payload) -> None:
    payload.register_job_handler(
        "source_ingest",
        lambda job_id, **kw: run_source_job(
            data_dir=context.data_dir,
            persona_name=kw.get("persona_name"),
            job_id=job_id,
        ),
    )
```

Page code should gather validated input, enqueue the job, notify the user, and redirect to a stable detail or jobs page.

## Official NiceGUI References To Follow

- `https://nicegui.io/documentation/page`
  - use page/path parameter behavior, but keep all extension routing inside `GUIPageSpec`
- `https://nicegui.io/documentation/storage`
  - use NiceGUI storage intentionally; current auth uses `app.storage.user`
- `https://nicegui.io/documentation/refreshable`
  - prefer refreshable fragments over brute-force whole-page rebuilds
- `https://nicegui.io/documentation/input`
  - use built-in validation instead of ad hoc post-submit string checks where practical
- `https://nicegui.io/documentation/select`
  - update option lists through the component API instead of rebuilding random markup
- `https://nicegui.io/documentation/dialog`
  - dialogs are good for staged admin flows, but they should still submit into services or queue jobs
- `https://nicegui.io/documentation/tabs`
  - use tabs and tab panels for dense admin views like persona detail
- `https://nicegui.io/documentation/table`
  - prefer a real table component for structured data unless custom cell composition forces manual layout
- `https://nicegui.io/documentation/section_action_events`
  - keep the UI responsive and do not block the NiceGUI event loop

## Do Not Do This

- Do not call `ui.run()` from any plugin other than the host.
- Do not register extension routes with direct `@ui.page(...)`.
- Do not execute CLI command handlers from browser pages to reuse functionality.
- Do not run ingestion, crawling, or LLM-heavy work inline in page callbacks.
- Do not use middleware-time `ui.navigate.to(...)`.
- Do not assume `nav_title` updates the header automatically.
- Do not invent browser upload semantics for persona ingestion; current flows are server-local-path based.
- Do not describe or build a browser chat UI under this plugin unless the architecture is explicitly expanded first.

## Current User Entry Points

- Login: `/login`
- Dashboard: `/`
- General settings: `/settings/general`
- Jobs: `/jobs`
- Plugin extension index: `/plugins`
- Extension pages currently registered by persona plugins:
  - `/personas`
  - `/personas/{name}`
  - `/sessions`
  - `/web-review/{collection_id}`
  - `/web-review/{collection_id}/{page_id}`

# GUI / NiceGUI AGENTS Guidance Refresh

## Summary

### Define done

Done means the repo has one coherent, implementation-grade documentation set for browser UI work in asky, centered on the existing `GUIServerPlugin` and NiceGUI extension model.

An implementer reading only the updated `AGENTS.md` files should be able to:

- understand that asky's browser UI is a daemon-hosted, authenticated admin console, not a standalone chat app,
- add a new protected page through `GUI_EXTENSION_REGISTER` without bypassing the host contract,
- choose the right execution model for page actions:
  - direct synchronous UI update for trivial local work,
  - `run.io_bound` / `run.cpu_bound` only for short-lived page-local work,
  - durable `JobQueue` jobs for ingestion, LLM, crawler, or other long-running workflows,
- use the shared layout and page-mount pattern correctly,
- avoid current known failure modes:
  - direct `@ui.page` registration from extension plugins,
  - doing business logic in page functions,
  - blocking the UI thread with heavy work,
  - using `ui.navigate.to()` from middleware instead of an HTTP redirect,
  - relying on cwd-relative NiceGUI storage,
  - assuming `nav_title` auto-adds a header link,
  - building ad hoc page-local behavior that ignores the service-layer and queue contracts.

This is a docs-only change set. No runtime behavior, APIs, routes, or dependency versions should change.

## Files

### Files to modify

1. `src/asky/plugins/AGENTS.md`
2. `src/asky/plugins/gui_server/AGENTS.md`
3. `src/asky/plugins/gui_server/pages/AGENTS.md`
4. `src/asky/plugins/manual_persona_creator/AGENTS.md`
5. `src/asky/plugins/persona_manager/AGENTS.md`
6. `devlog/DEVLOG.md`

### Files explicitly not planned for modification

- `ARCHITECTURE.md`
- `docs/web_admin.md`
- `docs/plugins.md`
- any Python source or test files

Reason: the user asked specifically for `AGENTS.md` guidance. Keep the implementation focused unless a factual contradiction is discovered during editing. If a contradiction is discovered, make the smallest necessary documentation correction only after preserving the AGENTS-first scope.

## Source grounding for the docs update

Use these as the factual basis for the rewrite:

- Current repo implementation:
  - `src/asky/plugins/gui_server/plugin.py`
  - `src/asky/plugins/gui_server/server.py`
  - `src/asky/plugins/gui_server/pages/plugin_registry.py`
  - `src/asky/plugins/gui_server/pages/layout.py`
  - `src/asky/plugins/gui_server/pages/personas.py`
  - `src/asky/plugins/gui_server/pages/sessions.py`
  - `src/asky/plugins/gui_server/pages/web_review.py`
  - `src/asky/plugins/manual_persona_creator/plugin.py`
  - `src/asky/plugins/persona_manager/plugin.py`
  - `src/asky/plugins/hook_types.py`
  - `tests/asky/plugins/gui_server/test_gui_server_plugin.py`
  - `tests/asky/plugins/gui_server/test_gui_extension_registration.py`
  - `tests/asky/plugins/gui_server/test_gui_server_auth.py`
- Official NiceGUI docs:
  - `https://nicegui.io/documentation/page`
  - `https://nicegui.io/documentation/storage`
  - `https://nicegui.io/documentation/refreshable`
  - `https://nicegui.io/documentation/input`
  - `https://nicegui.io/documentation/select`
  - `https://nicegui.io/documentation/dialog`
  - `https://nicegui.io/documentation/tabs`
  - `https://nicegui.io/documentation/table`
  - `https://nicegui.io/documentation/section_action_events`

Reference the official docs inside the rewritten AGENTS where useful, but interpret them through asky's current architecture and the currently locked NiceGUI version behavior.

## Sequential implementation steps

### Step 1: Expand plugin-wide GUI contract in `src/asky/plugins/AGENTS.md`

#### Before

The plugin package doc mentions `gui_server` and shows a minimal `GUI_EXTENSION_REGISTER` example, but it does not define the actual browser-extension workflow or failure boundaries clearly enough for weaker implementers.

#### After

Add a dedicated "GUI extension contract" section that states, without ambiguity:

- `gui_server` is the only NiceGUI host.
- Extension plugins do not own `ui.run()` or server lifecycle.
- Extension plugins do not register `@ui.page` directly.
- Extension plugins register `GUIPageSpec` and optional job handlers through `GUI_EXTENSION_REGISTER`.
- Browser pages are admin/review tools only, not a second general chat surface.
- New GUI work must stay inside plugin boundaries:
  - `gui_server` owns hosting, auth, shared shell, mount safety, queue plumbing,
  - domain plugins own service adapters, route registration, and job handlers.

Add one short registration example using `GUIPageSpec` and one short job-handler example.

### Step 2: Rewrite `src/asky/plugins/gui_server/AGENTS.md` into the authoritative host guide

#### Before

This file is a short module overview with no implementer-safe guidance.

#### After

Turn it into the main source of truth for browser UI work in asky, covering:

- host responsibilities:
  - daemon-owned lifecycle,
  - auth guard,
  - shared shell/layout,
  - page registry,
  - job queue plumbing,
  - middleware and storage setup,
- actual route model:
  - host-owned pages use `@ui.page`,
  - extension pages provide `render(ui, **kwargs)` only,
  - route parameters come from `GUIPageSpec.route`,
  - path variables are passed into `render`,
- auth and storage rules:
  - GUI must fail closed without password,
  - protected-route auth is enforced by middleware returning `RedirectResponse("/login")`,
  - `app.storage.user` is the current auth/session mechanism,
  - `storage_secret` is required for signed user/browser storage,
  - NiceGUI storage must remain rooted under the plugin data dir, never cwd-dependent,
- execution model:
  - page handlers must stay thin,
  - durable workflows go through `JobQueue`,
  - short-lived background work may use NiceGUI async helpers only when persistence and reload resilience are not needed,
- development flow for new GUI features:
  1. create or extend a UI-agnostic service adapter,
  2. add or extend route registration in the owning plugin,
  3. implement a render function under the host page layer,
  4. enqueue long-running work instead of doing it inline,
  5. add registration/render/auth tests,
- explicit "do not do this" list:
  - no standalone `ui.run()` from plugins,
  - no direct CLI-command execution from pages,
  - no heavy LLM / crawler / ingestion work in click handlers,
  - no middleware navigation with `ui.navigate.to()`,
  - no page-local persistence assumptions outside documented NiceGUI storage.

Include a small "official NiceGUI reference map" subsection with the relevant doc URLs and a short asky-specific interpretation of each.

### Step 3: Rewrite `src/asky/plugins/gui_server/pages/AGENTS.md` as the page-authoring cookbook

#### Before

This file only says to preserve TOML sections and isolate mount failures.

#### After

Turn it into a practical, copy-paste-oriented authoring guide for rich pages:

- expected page shape:
  - `register_page(GUIPageSpec(...))`
  - `render(ui, **kwargs)` with no direct `@ui.page`,
  - shared wrapper comes from the host registry,
- layout rules:
  - always rely on `page_layout`,
  - keep page content inside cards/rows/columns/tabs rather than ad hoc HTML unless a native NiceGUI component cannot express it cleanly,
- forms and validation:
  - use `validation=` where appropriate,
  - use `.on('keydown.enter', ...)` or blur handlers only when confirmation semantics are intended,
  - normalize and validate before queueing or navigating,
- dialog flow:
  - prefer staged dialogs for multistep actions,
  - validate before close,
  - use `ui.notify` for user-visible failures,
- tables and lists:
  - prefer `ui.table` for structured tabular data unless custom nested cell content forces manual layout,
  - if manual table markup is needed, render nested labels/elements rather than relying on unsupported element text mutation patterns,
- refresh/update patterns:
  - prefer `@ui.refreshable` plus explicit refresh calls for list/detail fragments that must update after an action,
  - use `ui.state` for small reactive page-local state,
  - do not rebuild the whole page when only one region must change,
- navigation:
  - use route parameters for stable entity pages,
  - use `ui.navigate.to(...)` from normal event handlers only,
  - document that `nav_title` is metadata today and should not be assumed to auto-populate the top header,
- long-running work:
  - queue it, notify the user, then redirect to detail/jobs pages,
  - do not block the UI event loop with ingestion, crawling, or model calls.

Include concrete examples for:

1. a simple list page,
2. a dynamic detail page with path params,
3. a validated dialog that queues a job,
4. a refreshable list/detail fragment,
5. a tabs page using `ui.tabs` + `ui.tab_panels`.

### Step 4: Extend `src/asky/plugins/manual_persona_creator/AGENTS.md` with plugin-specific GUI rules

#### Before

The file documents persona storage and ingestion behavior, but it does not tell implementers how browser pages must interact with these services.

#### After

Add a GUI/admin subsection that makes these boundaries explicit:

- browser flows are service-first:
  - authored-book UI goes through `gui_service.py` / `book_service.py`,
  - source ingestion goes through `source_service.py`,
  - web review goes through `web_service.py`,
- GUI code must not call CLI command handlers or shell out to reuse persona commands,
- job names and responsibilities must stay explicit and documented:
  - `authored_book_ingest`
  - `source_ingest`
- browser intake remains server-local-path based today; do not invent upload semantics in page code,
- review boundaries must be preserved:
  - pending/review-ready content must not be projected by browsing code without explicit approval actions,
- page code should gather/validate browser input, then hand off to services or queue jobs.

Add at least one example flow description for:

- authored book preflight -> editable confirmation -> queue,
- source ingest dialog -> queue,
- web review approve/reject.

### Step 5: Extend `src/asky/plugins/persona_manager/AGENTS.md` with GUI scope and boundaries

#### Before

The file focuses on runtime answering and session binding, but not on the browser-admin surface.

#### After

Add a GUI subsection that defines:

- current browser scope is session/persona binding only,
- no browser-side persona chat/query surface is in scope,
- session page code must use the service helpers for listing/binding, not direct storage writes from random page code,
- binding changes are admin actions and should use small immediate handlers, not background jobs,
- page code must not bleed runtime answering logic into GUI modules.

Include one small example pattern for a binding page with a select input and notification.

### Step 6: Update `devlog/DEVLOG.md`

Add a new dated entry describing:

- the AGENTS guidance expansion,
- the goal of standardizing NiceGUI development flow for future implementers,
- the repo/runtime facts the docs were aligned to,
- the verification commands and runtime baseline.

### Step 7: Verify and self-review

Run the commands below and make sure the docs match shipped behavior:

1. `rg -n 'GUI_EXTENSION_REGISTER|GUIPageSpec|JobQueue|ui.refreshable|ui.state|run.io_bound|run.cpu_bound|storage_secret|app.storage.user|nav_title|ui.table' src/asky/plugins/AGENTS.md src/asky/plugins/gui_server/AGENTS.md src/asky/plugins/gui_server/pages/AGENTS.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md`
2. `uv run pytest -q`

Also do a manual doc sanity check against current code:

- `src/asky/plugins/gui_server/server.py`
- `src/asky/plugins/gui_server/pages/plugin_registry.py`
- `src/asky/plugins/manual_persona_creator/plugin.py`
- `src/asky/plugins/persona_manager/plugin.py`

## Constraints

- Docs only. Do not change Python behavior, routes, auth logic, or dependency versions.
- Do not add new packages.
- Do not describe planned architecture as if it already exists.
- Do not document features that contradict current code, such as:
  - automatic top-nav population from `nav_title`,
  - browser uploads for authored books/sources,
  - standalone GUI startup outside the daemon host contract,
  - a browser chat/query UI for personas.
- Prefer repo-specific rules over generic NiceGUI advice whenever they conflict.
- Use NiceGUI best practices only where they support the current asky architecture.

## Assumptions and defaults

- NiceGUI guidance should target the currently shipped behavior visible in the repo and current lockfile, not speculative future framework changes.
- The current lockfile shows NiceGUI `3.8.0`; the docs rewrite should treat the official NiceGUI documentation as current reference material while grounding guidance in actual repo behavior.
- No new tests are required because this is a documentation-only change, but the full existing suite must still be run after the edits.
- Full-suite baseline from this planning session:
  - `uv run pytest -q` -> `1607 passed in 17.93s`
  - shell timing: `real 18.16`, `user 44.93`, `sys 4.01`

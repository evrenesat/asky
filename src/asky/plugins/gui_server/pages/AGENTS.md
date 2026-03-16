# GUI Pages (`plugins/gui_server/pages/`)

This directory holds host-owned pages and shared page helpers for asky's browser admin console. Even when a page belongs to another plugin conceptually, it still has to obey the shared page contract enforced here.

## Page Authoring Contract

For extension pages, the expected shape is:

1. The owning plugin registers a `GUIPageSpec`.
2. The page module exposes a `render(ui, **kwargs)` function or a registration helper that creates one.
3. `PluginPageRegistry` mounts the route and wraps it in `page_layout(...)`.

Extension pages must not declare their own `@ui.page(...)` routes.

Use this pattern:

```python
def register_example_pages(register_page, data_dir) -> None:
    def _example_list_page(ui) -> None:
        ui.label("Example")

    register_page(
        GUIPageSpec(
            route="/example",
            title="Example",
            render=_example_list_page,
        )
    )
```

Dynamic routes receive path parameters as keyword arguments:

```python
def _detail_page(ui, item_id: str) -> None:
    ui.label(f"Item: {item_id}")
```

If the route is `/example/{item_id}`, the registry passes `item_id` to the render function.

## Layout Rules

- Rely on `page_layout(...)` for the outer shell.
- Build content from NiceGUI layout primitives like `ui.card`, `ui.row`, `ui.column`, `ui.tabs`, and `ui.tab_panels`.
- Prefer NiceGUI elements over raw HTML for normal admin UI.
- Use raw `ui.element(...)` only when a native NiceGUI component cannot express the needed markup cleanly.

`page_layout` already provides:

- consistent header and shell
- top-level title
- shared spacing and width

Do not recreate page chrome inside each page.

## Forms And Validation

Use NiceGUI validation features where possible.

- `ui.input(..., validation=...)`
- `ui.select(..., validation=...)`
- `.without_auto_validation()` only when per-keystroke validation would be noisy or wrong

NiceGUI behavior to remember:

- `ui.input(...).on_change(...)` updates on each keystroke
- use `.on('keydown.enter', ...)` or `.on('blur', ...)` only when confirmation semantics are intentional
- `ui.select` option changes should go through its documented update behavior, not manual DOM tricks

Always normalize before submit:

- trim strings
- collapse empty values to `None` where the service expects `None`
- coerce numeric fields explicitly
- reject invalid combinations before queueing work

## Dialog Pattern

Dialogs are good for staged admin flows, especially when preflight and confirmation are separate steps.

Current expectations:

- render the dialog with NiceGUI controls
- validate before close
- use `ui.notify(...)` for user-visible failures
- close only after the action has succeeded or been queued

Use dialogs for:

- authored-book preflight and confirmation
- source intake forms
- small admin mutation flows

Do not use dialogs as a hiding place for long-running work. Validate, hand off, notify, close.

Example shape:

```python
with ui.dialog() as dialog, ui.card():
    name_input = ui.input("Name", validation={"Required": lambda v: bool(str(v).strip())})

    def _submit() -> None:
        if not name_input.value or not str(name_input.value).strip():
            ui.notify("Name is required", color="negative")
            return
        queue.enqueue("example_job", "job-id", name=str(name_input.value).strip())
        ui.notify("Queued")
        dialog.close()

    ui.button("Submit", on_click=_submit)
```

## Tables, Lists, And Dense Data

Prefer `ui.table` for structured tabular data unless you need custom nested cell content that is awkward in the standard table API.

If you do use manual table markup:

- render nested labels and elements inside cells
- do not rely on unsupported or brittle element text mutation helpers
- keep row rendering simple and readable

Good fits for `ui.table`:

- job lists
- session/binding lists
- uniform review lists with mostly textual cells

Good fits for manual card/list layouts:

- persona summaries
- highly visual review cards
- rows with mixed buttons, badges, and multiline details

## Refresh And Reactive State

Prefer targeted refresh over whole-page rebuilds.

Use `@ui.refreshable` when:

- a list, details pane, or sub-section needs to rerender after an action
- the page contains stable surrounding chrome but mutable data sections

Use `ui.state` for small page-local state:

- selected tab defaults
- dialog stage flags
- local filters
- temporary UI-only counters or toggles

Do not rebuild the whole page if only one fragment changed.

Example fragment:

```python
@ui.refreshable
def render_books(ui, books) -> None:
    for book in books():
        ui.label(book["title"])

def _after_enqueue() -> None:
    ui.notify("Queued")
    render_books.refresh()
```

## Navigation Rules

- Use stable routes for real resources like personas, sessions, and review pages.
- Use path parameters for detail pages instead of query-string-only conventions.
- Call `ui.navigate.to(...)` from page events, button handlers, or dialog handlers.
- Do not call `ui.navigate.to(...)` from middleware or other request-level code.

Current registry behavior:

- page title placeholders can use route variables
- `nav_title` is descriptive metadata only

Do not assume new pages automatically appear in the top header. The current header links are hardcoded in `layout.py`.

## Long-Running Work

Queue long-running actions.

Use `JobQueue` for:

- authored-book ingestion
- source ingestion
- web collection / expansion / heavy review preparation
- any LLM-heavy extraction

Only use direct handlers for lightweight actions like:

- binding a persona to a session
- approving or rejecting a single reviewed page when the service call is immediate
- simple config writes

If an action might block the NiceGUI event loop or should survive refreshes, it belongs in the queue.

## Current Page Patterns In This Repo

### List page

- `/personas` uses card-based summaries and route navigation
- `/sessions` uses a structured table-like layout for bindings

### Dynamic detail page

- `/personas/{name}` renders a real entity detail view with route parameters
- `/web-review/{collection_id}/{page_id}` renders a page-specific review surface

### Staged dialog with queue handoff

- authored-book dialog:
  - collect path
  - run preflight
  - show editable metadata/targets
  - validate
  - enqueue ingestion

### Tabs page

- persona detail uses `ui.tabs` and `ui.tab_panels` to separate overview, books, sources, and web collections

## Anti-Patterns

- Do not put domain business logic directly into page rendering code.
- Do not shell out to CLI commands from browser pages.
- Do not perform heavy work during page render.
- Do not store authoritative workflow state in page-local variables when the service or queue already owns it.
- Do not invent unsupported browser uploads or hidden background workers.
- Do not assume users are in a chat-like interaction model; these pages are admin workflows.

## Host-Owned Page Constraints

Some files in this directory are host-owned rather than extension-owned:

- `general_settings.py`
- `jobs.py`
- `layout.py`
- `plugin_registry.py`

When editing those:

- preserve unrelated TOML sections while writing `general.toml`
- keep mount failures isolated per page
- keep auth/layout behavior centralized instead of duplicating it across pages

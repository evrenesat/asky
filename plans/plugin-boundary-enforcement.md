# Plan: Plugin Boundary Enforcement and Dynamic CLI Contribution System

## Overview

The plugin system currently has directional dependency violations: core modules
(`cli/main.py`, `cli/history.py`, `cli/sessions.py`) directly import and call
plugin business logic (`email_sender`, `push_data`, `playwright_browser`), and
core argparse definitions hard-code flags that belong entirely to plugins
(`--mail`, `--subject`, `--push-data`, `--push-param`, `--browser`, `--daemon`).

This plan enforces the one-way dependency rule: **plugin code lives in and is
imported only from its own plugin directory**. Anything the plugin exposes to the
outside world — CLI flags, capability metadata, dispatch entry points — is
declared through the plugin's public contract, not by reaching into it from core.

The second goal is improved CLI UX: related flags are grouped under named,
descriptively-labelled argparse groups so users see the semantic categories at a
glance in `--help` output.

**One-way rule (inviolable after this plan):**
Core code → `plugins.runtime` / `plugins.hooks` (the infrastructure) only.
Core code must NOT import from any individual plugin package directly.

---

## Phases

### Phase 1: `CLIContribution` Infrastructure

**Objective:** Give plugins a structured way to declare CLI flags without being activated first.

**Files to create:**
- None.

**Files to modify:**
- `src/asky/plugins/base.py`
- `src/asky/plugins/manager.py`

**Changes:**

**`base.py`** — add two new public types and a classmethod on `AskyPlugin`:

```python
# Category constants — each maps to a named argparse group
class CapabilityCategory:
    OUTPUT_DELIVERY   = "output_delivery"   # act on final answer
    SESSION_CONTROL   = "session_control"   # query/session behavior
    BROWSER_SETUP     = "browser_setup"     # browser auth/config
    BACKGROUND_SERVICE = "background_service"  # daemon processes

# Human-readable group titles and descriptions shown in --help
CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    CapabilityCategory.OUTPUT_DELIVERY: (
        "Output Delivery",
        "Actions applied to the final answer after a query completes"
        " (e.g., send by email, push to an endpoint, open in browser).",
    ),
    CapabilityCategory.SESSION_CONTROL: (
        "Session & Query",
        "Control how sessions and queries behave."
        " Settings that persist across turns in the current session.",
    ),
    CapabilityCategory.BROWSER_SETUP: (
        "Browser Setup",
        "Configure and authenticate the retrieval browser"
        " for sites that require login or anti-bot handling.",
    ),
    CapabilityCategory.BACKGROUND_SERVICE: (
        "Background Services",
        "Start and manage background daemon processes.",
    ),
}

@dataclass(frozen=True)
class CLIContribution:
    """Describes one argparse argument contributed by a plugin."""
    category: str                # one of CapabilityCategory.*
    flags: tuple[str, ...]       # e.g. ("--mail", "-m")
    kwargs: dict[str, Any]       # passed verbatim to ArgumentGroup.add_argument()
```

`AskyPlugin` gains a new classmethod:

```python
@classmethod
def get_cli_contributions(cls) -> list[CLIContribution]:
    """Return CLI flags this plugin wants to expose. Called before activation."""
    return []
```

**`manager.py`** — add `collect_cli_contributions()`:

```python
def collect_cli_contributions(self) -> list[tuple[str, CLIContribution]]:
    """
    Light-import each enabled plugin class (no activation) and collect
    its CLI contributions. Returns list of (plugin_name, contribution).
    """
```

This method iterates `self._roster` (enabled entries only), imports the module,
resolves the class, and calls `cls.get_cli_contributions()`. Import errors per
plugin are logged and skipped — never raise.

**Constraints:**
- This method must NOT call `activate()`.
- It must be callable before `activate_all()` runs.
- Disabled plugins in the roster must be skipped silently.

**Verification:**
```bash
uv run pytest tests/test_plugin_manager.py -k cli_contribution -v
```

**Expected outcome:** `PluginManager.collect_cli_contributions()` returns
contributions from any plugin whose class implements `get_cli_contributions()`;
plugins that don't implement it return `[]`.

---

### Phase 2: Refactor `parse_args()` to use argparse groups and plugin contributions

**Objective:** Remove all hardcoded plugin flag definitions from `parse_args()`.
Replace with a two-step bootstrap: (1) collect contributions from enabled plugins,
(2) build argparse with named groups.

**Files to modify:**
- `src/asky/cli/main.py`

**Current state in `parse_args()`:**
- Lines 706–730: `--mail`, `--subject`, `--push-data`, `--push-param`
- Lines 987–997: `--daemon`, `--browser`
- Line 1013–1018: `--playwright-login` (suppressed alias)
- Line 998–1002: `--xmpp-daemon` (suppressed alias)

**After:**
- Those lines are **deleted** from the flat argument list.
- `parse_args()` acquires a `plugin_manager: PluginManager | None` parameter
  (optional, defaults to `None` for callers that don't provide one).
- When a manager is available, `collect_cli_contributions()` is called and the
  results are added to named argparse `ArgumentGroup`s.
- When no manager is provided (e.g., tests) or contributions are empty, the
  parser behaves as if those flags don't exist — which is correct.

**Argparse group structure:**

The `--open` flag (core, stays in core) moves from the flat section into the
`OUTPUT_DELIVERY` group so it is visually adjacent to plugin-contributed mail/push
flags. The group is created unconditionally; plugins add to it.

```
Output Delivery
  Actions applied to the final answer after a query completes (...)
  -o / --open           [existing, stays core]
  --mail                [contributed by email_sender plugin]
  --subject             [contributed by email_sender plugin]
  --push-data           [contributed by push_data plugin]
  --push-param          [contributed by push_data plugin]

Browser Setup
  Configure and authenticate the retrieval browser (...)
  --browser             [contributed by playwright_browser plugin]

Background Services
  Start and manage background daemon processes.
  --daemon              [contributed by xmpp_daemon plugin]
```

**Bootstrap call site in `main()`:**

```python
# Early in main(), before parse_args():
plugin_manager = _bootstrap_plugin_manager_for_cli()
args = parse_args(sys.argv[1:], plugin_manager=plugin_manager)
```

`_bootstrap_plugin_manager_for_cli()` creates a `PluginManager`, calls
`load_roster()`, and returns it. It does NOT call `activate_all()` — that happens
later in the normal startup flow. On any error it returns `None` and logs.

**Suppressed aliases** (`--xmpp-daemon`, `--playwright-login`) are internal
dispatch aliases. After cleanup, the public `--daemon` and `--browser` flags exist
only if the relevant plugins are enabled. The `argparse.SUPPRESS` aliases are kept
as suppressed args added by the plugins themselves if they need them.

**Constraints:**
- `parse_args()` must produce identical behavior for all core flags when no plugin
  manager is passed (backwards compatible for tests).
- The `--open` flag is NOT contributed by a plugin; it is added directly to the
  `OUTPUT_DELIVERY` group by `parse_args()` unconditionally.
- `parse_args()` must not call `activate_all()`.

**Verification:**
```bash
uv run pytest tests/ -k "parse_args or cli" -v
uv run python -m asky --help   # confirm groups appear, plugin flags absent if disabled
```

---

### Phase 3: Move `email_sender.py` into the plugin and contribute its CLI flags

**Objective:** Eliminate the `from asky.email_sender import send_email` imports in
core code. The SMTP business logic must live entirely inside the plugin directory.

**Files to create:**
- `src/asky/plugins/email_sender/sender.py`  (contains the moved logic)

**Files to modify:**
- `src/asky/plugins/email_sender/plugin.py`
- `src/asky/cli/history.py`
- `src/asky/cli/sessions.py`

**Files to delete:**
- `src/asky/email_sender.py`

**Steps:**

1. Copy the full contents of `src/asky/email_sender.py` into
   `src/asky/plugins/email_sender/sender.py`.
   - Public API: `send_email(recipients, subject, markdown_body)` and
     `markdown_to_html(text)`.
   - No changes to logic.

2. In `src/asky/plugins/email_sender/plugin.py`:
   - Replace `from asky.email_sender import send_email` with
     `from asky.plugins.email_sender.sender import send_email`.
   - Add `get_cli_contributions()` classmethod:
     ```python
     @classmethod
     def get_cli_contributions(cls) -> list[CLIContribution]:
         return [
             CLIContribution(
                 category=CapabilityCategory.OUTPUT_DELIVERY,
                 flags=("--mail",),
                 kwargs=dict(
                     dest="mail_recipients",
                     metavar="RECIPIENTS",
                     help="Send the final answer via email to comma-separated addresses.",
                 ),
             ),
             CLIContribution(
                 category=CapabilityCategory.OUTPUT_DELIVERY,
                 flags=("--subject",),
                 kwargs=dict(
                     metavar="EMAIL_SUBJECT",
                     help="Subject line for the email (used with --mail).",
                 ),
             ),
         ]
     ```

3. In `src/asky/cli/history.py`:
   - Remove the `from asky.email_sender import send_email` import (line ~102).
   - Remove the block that calls `send_email(...)`.
   - The email delivery now happens only through the `POST_TURN_RENDER` hook in
     the plugin — it must not happen in `history.py` as well. If there is
     duplication (email sent from both places), trace the call chain and remove the
     one in `history.py`.

4. In `src/asky/cli/sessions.py`:
   - Same removal as `history.py` — line ~97.

5. In `src/asky/cli/main.py`:
   - Remove the top-level `from asky.email_sender import send_email` import (line 39).
   - Remove lines 706–716 (`--mail`, `--subject` argparse definitions).

6. Delete `src/asky/email_sender.py`.

**Constraints:**
- After this phase, `grep -r "from asky.email_sender" src/` must return zero matches.
- Email delivery must still work end-to-end via the `POST_TURN_RENDER` hook.
- No references to `email_sender` module outside `plugins/email_sender/`.

**Verification:**
```bash
grep -r "from asky.email_sender" src/   # must be empty
grep -r "asky.email_sender" src/        # must be empty
uv run pytest tests/ -k email -v
uv run pytest -x -q                     # full suite
```

---

### Phase 4: Move `push_data.py` into the plugin and contribute its CLI flags

**Objective:** Eliminate the `from asky.push_data import ...` import in core code
and in the plugin itself. Move the HTTP push logic entirely into the plugin directory.

**Files to create:**
- `src/asky/plugins/push_data/executor.py`  (contains moved logic)

**Files to modify:**
- `src/asky/plugins/push_data/plugin.py`

**Files to delete:**
- `src/asky/push_data.py`

**Steps:**

1. Move `execute_push_data()` and `get_enabled_endpoints()` from
   `src/asky/push_data.py` into `src/asky/plugins/push_data/executor.py`.
   - No changes to logic.

2. In `src/asky/plugins/push_data/plugin.py`:
   - Replace `from asky.push_data import execute_push_data, get_enabled_endpoints`
     with `from asky.plugins.push_data.executor import execute_push_data, get_enabled_endpoints`.
   - Add `get_cli_contributions()` classmethod:
     ```python
     @classmethod
     def get_cli_contributions(cls) -> list[CLIContribution]:
         return [
             CLIContribution(
                 category=CapabilityCategory.OUTPUT_DELIVERY,
                 flags=("--push-data",),
                 kwargs=dict(
                     dest="push_data_endpoint",
                     metavar="ENDPOINT",
                     help="Push query result to a configured endpoint after the query completes.",
                 ),
             ),
             CLIContribution(
                 category=CapabilityCategory.OUTPUT_DELIVERY,
                 flags=("--push-param",),
                 kwargs=dict(
                     dest="push_params",
                     action="append",
                     nargs=2,
                     metavar=("KEY", "VALUE"),
                     help="Dynamic parameter for --push-data. Repeatable. Example: --push-param title 'My Title'",
                 ),
             ),
         ]
     ```

3. In `src/asky/cli/main.py`:
   - Remove lines 717–730 (`--push-data`, `--push-param` argparse definitions).

4. Delete `src/asky/push_data.py`.

**Constraints:**
- After this phase, `grep -r "from asky.push_data" src/` must return zero matches.
- `grep -r "asky.push_data" src/` must return zero matches.
- Push-data tool registration via `TOOL_REGISTRY_BUILD` and `POST_TURN_RENDER`
  delivery must still work.

**Verification:**
```bash
grep -r "from asky.push_data" src/     # must be empty
grep -r "asky.push_data" src/          # must be empty
uv run pytest tests/ -k push -v
uv run pytest -x -q
```

---

### Phase 5: Clean up `playwright_browser` CLI integration

**Objective:** Remove the hardcoded `--browser` flag and `_run_browser_session()` dispatch from `main.py`. The plugin contributes its own flag and dispatch entry point.

**Files to modify:**
- `src/asky/plugins/playwright_browser/plugin.py`
- `src/asky/cli/main.py`

**Steps:**

1. In `src/asky/plugins/playwright_browser/plugin.py`:
   - Add `get_cli_contributions()` classmethod:
     ```python
     @classmethod
     def get_cli_contributions(cls) -> list[CLIContribution]:
         return [
             CLIContribution(
                 category=CapabilityCategory.BROWSER_SETUP,
                 flags=("--browser",),
                 kwargs=dict(
                     dest="playwright_login",
                     metavar="URL",
                     default=None,
                     help="Open an interactive browser session at URL for login or extension setup.",
                 ),
             ),
         ]
     ```
   - The existing `run_login_session()` method stays.

2. In `src/asky/cli/main.py`:
   - Delete the `--browser` argument definition (lines 992–997).
   - Delete the `--playwright-login` hidden alias (lines 1013–1018).
   - Delete `_run_browser_session()` function (lines 1312–1336). The dispatch is
     now done via a new hook `CLI_DISPATCH` (see note below) or kept inline but
     using the plugin runtime without the hardcoded plugin name.

   The dispatch call site currently does:
   ```python
   if getattr(args, "playwright_login", None) ...:
       _run_browser_session(args.playwright_login)
   ```
   Replace `_run_browser_session()` with a small inline call that uses
   `runtime.manager.get_plugin("playwright_browser")` if runtime is available.
   This still names the plugin by name, which is acceptable — it's a runtime
   lookup through the plugin infrastructure, not a direct module import.

   Alternatively, introduce a `CLI_DISPATCH_BROWSER_SETUP` hook where the plugin
   registers a handler. This is cleaner but adds complexity. **Decision: use
   inline runtime lookup for now** (it already exists in the codebase; removing
   `_run_browser_session()` is the primary goal). If the runtime doesn't have the
   plugin, print an actionable error and exit.

**Constraints:**
- After this phase, the `--browser` flag appears in help only when
  `playwright_browser` plugin is enabled.
- No `from asky.plugins.playwright_browser` import in `main.py`.

**Verification:**
```bash
grep -n "playwright" src/asky/cli/main.py     # only runtime lookup, no imports
uv run pytest tests/ -k playwright -v
uv run pytest -x -q
```

---

### Phase 6: Clean up `xmpp_daemon` CLI integration

**Objective:** Remove the hardcoded `--daemon` flag from `main.py`. The xmpp_daemon
plugin contributes it.

**Files to modify:**
- `src/asky/plugins/xmpp_daemon/plugin.py`
- `src/asky/cli/main.py`

**Steps:**

1. In `src/asky/plugins/xmpp_daemon/plugin.py`:
   - Add `get_cli_contributions()` classmethod:
     ```python
     @classmethod
     def get_cli_contributions(cls) -> list[CLIContribution]:
         return [
             CLIContribution(
                 category=CapabilityCategory.BACKGROUND_SERVICE,
                 flags=("--daemon",),
                 kwargs=dict(
                     action="store_true",
                     help="Run the XMPP daemon in the foreground.",
                 ),
             ),
         ]
     ```

2. In `src/asky/cli/main.py`:
   - Delete `--daemon` (lines 987–991) and `--xmpp-daemon` (lines 998–1002) and
     `--edit-daemon` (lines 1003–1007) and `--xmpp-menubar-child` (lines
     1008–1012) argument definitions.
   - `--xmpp-daemon`, `--edit-daemon`, `--xmpp-menubar-child` are internal
     suppressed aliases. They should be contributed as suppressed args by the
     xmpp_daemon plugin itself:
     ```python
     CLIContribution(
         category=CapabilityCategory.BACKGROUND_SERVICE,
         flags=("--xmpp-daemon",),
         kwargs=dict(action="store_true", help=argparse.SUPPRESS),
     ),
     CLIContribution(
         category=CapabilityCategory.BACKGROUND_SERVICE,
         flags=("--edit-daemon",),
         kwargs=dict(action="store_true", help=argparse.SUPPRESS),
     ),
     CLIContribution(
         category=CapabilityCategory.BACKGROUND_SERVICE,
         flags=("--xmpp-menubar-child",),
         kwargs=dict(action="store_true", help=argparse.SUPPRESS),
     ),
     ```

**Constraints:**
- `--daemon` appears in `--help` only when xmpp_daemon plugin is enabled.
- All daemon dispatch paths in `main()` must still work. Trace every `args.daemon`
  and `args.xmpp_daemon` reference and confirm they are guarded with `hasattr`/
  `getattr(..., None)` so they degrade gracefully when the plugin is disabled and
  the attribute is absent from the namespace.

**Verification:**
```bash
grep -n '"--daemon"' src/asky/cli/main.py     # must be gone from parse_args()
uv run pytest tests/ -k daemon -v
uv run pytest -x -q
```

---

### Phase 7: Tests, documentation, and final boundary audit

**Objective:** Confirm the boundary is clean, add regression tests, update docs.

**Files to modify:**
- `tests/test_plugin_manager.py` (add CLI contribution tests)
- `tests/test_cli_args.py` or `tests/test_cli_main.py` (add group/contribution tests)
- `ARCHITECTURE.md`
- `DEVLOG.md`
- `src/asky/plugins/AGENTS.md`
- `src/asky/daemon/AGENTS.md`

**Test additions:**

1. `PluginManager.collect_cli_contributions()` with a fake plugin class that
   returns known contributions — verify name/category/flags returned correctly.
2. Disabled plugin contributions are ex
cluded.
3. Import error during contribution collection does not propagate.
4. `parse_args()` with a mock manager that has known contributions — verify the
   contributed flags are parseable.
5. `parse_args()` with `plugin_manager=None` — verify existing core flags still
   parse correctly (regression).
6. End-to-end: verify `grep` checks pass (no cross-boundary imports).

**Boundary audit (final gate):**
```bash
# Must all return empty:
grep -r "from asky.email_sender" src/
grep -r "from asky.push_data" src/
grep -r "import email_sender" src/asky/cli/
grep -r "import push_data" src/asky/cli/
grep -r "from asky.plugins.email_sender" src/asky/cli/
grep -r "from asky.plugins.push_data" src/asky/cli/
grep -r "from asky.plugins.playwright_browser" src/asky/cli/
```

**Allowed cross-boundary calls (these are OK):**
- Core calls `runtime.manager.get_plugin("playwright_browser")` — runtime lookup.
- Core calls `runtime.hooks.invoke(...)` — hook infrastructure.
- Tests import plugin classes directly for unit tests.

**Documentation updates:**
- `ARCHITECTURE.md`: document `CLIContribution`, `CapabilityCategory`,
  `collect_cli_contributions()`, and the one-way dependency rule.
- `src/asky/plugins/AGENTS.md`: add section on CLI contribution API with example.

**Verification:**
```bash
uv run pytest -x -q   # full suite green
```

---

## Notes

### What stays in core (intentionally)
- `--open` flag: opens final answer in browser via a markdown template. This is a
  core rendering feature, not a plugin. It stays hardcoded in `parse_args()` but
  is placed inside the `OUTPUT_DELIVERY` argument group.
- `--session`, `--sticky-session`, `--resume-session`, `--tools`, etc.: all core
  session/query control flags. These are already correctly in core.
- Hook infrastructure imports in retrieval (`FETCH_URL_OVERRIDE`) and chat
  (`POST_TURN_RENDER`) are correct — they use the hook system, not plugin imports.

### Ordering risk
Phase 5 and Phase 6 touch runtime dispatch logic. These must be done after Phase 2
(groups infrastructure) so the contributed flags land in the right groups. Phases 3
and 4 are independent of 5 and 6.

### Argcomplete compatibility
`argcomplete` completers currently attached to specific arg actions
(`resume_session_action.completer = ...`) must be reviewed after Phase 2 to
confirm they still work when some args are created via the contribution path.

### `collect_cli_contributions()` call timing
This method is called early — before `activate_all()`. Any plugin that raises
during import-for-contributions will be skipped (with a log warning). This means
if a plugin's dependencies are broken, its flags simply won't appear in help. The
user will see a startup warning from the existing dependency-issue detection.

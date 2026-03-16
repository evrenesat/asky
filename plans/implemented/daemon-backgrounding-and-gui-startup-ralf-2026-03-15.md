# Daemon Backgrounding, Optional Tray, and GUI Startup Hardening

## Summary

Implement a single explicit daemon launch contract across platforms:

- `asky --daemon` becomes a backgrounding command on all platforms.
- If tray support is available and not bypassed, background launch may use the tray path.
- `asky --daemon --foreground` becomes the supported way to keep the daemon attached to the terminal and must start the full daemon stack, not just XMPP.
- `asky --daemon --no-tray` backgrounds the daemon without using tray/menubar UI even when tray support is available.
- Background launch must print a short startup summary before the parent exits: PID, log directory, and the web admin URL when the GUI plugin is enabled and password-configured. If the GUI plugin is enabled but password is missing, print a warning instead of a URL.
- NiceGUI persistence must never default to `/.nicegui`; store it under asky-managed writable plugin data.

Baseline before edits:

- Branch: `main`
- Base HEAD: `8d2275a1071f574531dd2e24921d6f492851b251`
- Full suite: `1602 passed in 31.73s`
- Wall clock from shell timing: `32.597s`

Important public surface changes in this handoff:

- Add public CLI flags: `--foreground`, `--no-tray`
- Change `--daemon` semantics from “foreground on non-macOS, menubar special-case on macOS” to “background by default everywhere”
- Keep `-vv --daemon` working as a compatibility foreground path for this handoff, but treat `--foreground` as the canonical public contract in help/docs/tests

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `8d2275a1071f574531dd2e24921d6f492851b251`
- Last Reviewed HEAD: `finalized after approved+squashed review on 2026-03-16`
- Review Log:
  - 2026-03-16 — reviewed accumulated handoff from `8d2275a1071f574531dd2e24921d6f492851b251..d4af48f`, including the WebGUI auth redirect fix and the follow-up plugin-page route/rendering fixes; outcome: `approved+squashed`.

## Done Means

- `asky --daemon` returns the shell prompt after printing a background startup summary with PID and log location.
- On macOS with tray support available and no `--no-tray`, `asky --daemon` still uses the tray child path.
- On Linux, Windows, and tray-bypassed runs, `asky --daemon` backgrounds a headless daemon child instead of blocking in the terminal.
- `asky --daemon --foreground` always stays attached to the terminal and starts the same daemon sidecars and transport that background mode would run.
- If `gui_server` is enabled and password-configured, daemon startup output includes the admin console URL.
- If `gui_server` is enabled but password is missing, daemon startup output warns that the GUI will not start securely and points the user to the config/env fix.
- NiceGUI persistence is written under the asky plugin data directory, not `/.nicegui`, and foreground daemon GUI usage no longer throws the read-only filesystem error from the user report.
- Startup-at-login commands and development helpers that rely on a long-lived foreground process are updated so they do not accidentally self-daemonize.
- Help text, README/docs, architecture notes, and devlog all describe the shipped behavior, not the pre-change behavior.

## Critical Invariants

- `--foreground` must win over every background/tray path. It is the explicit escape hatch for terminal-attached daemon runs.
- `--daemon` must no longer rely on `-vv` as the only way to stay in the foreground.
- Service-manager owned commands must run in foreground mode; do not register a self-daemonizing command with `systemd`, LaunchAgent, or similar managed startup paths.
- GUI availability must not depend on tray availability. Foreground daemon runs must start the GUI sidecar the same way background daemon runs do.
- NiceGUI local persistence must live under asky-owned writable storage, specifically the `gui_server` plugin data area, not the process cwd and not a hardcoded absolute path.
- Startup output must be deterministic and short: PID, log directory, plus GUI URL or GUI warning when relevant.
- Backgrounding logic must live in one shared launcher path, not as separate ad hoc spawn branches split between macOS and non-macOS code.

## Forbidden Implementations

- Do not keep the current “macOS tray spawn in `main.py`, everything else inline” split as the long-term structure.
- Do not document `-vv` as the preferred foreground switch after `--foreground` exists.
- Do not hardcode `/.nicegui`, `/.config`, or any other root-anchored writable runtime path.
- Do not make startup-at-login reuse `asky --daemon` if that command now self-backgrounds.
- Do not silently skip GUI startup preflight messaging when the plugin is enabled but password is missing.
- Do not add a second background launcher implementation inside the GUI plugin or XMPP plugin.
- Do not remove existing tray child behavior on macOS; this handoff is “tray optional,” not “tray deleted.”
- Do not update docs to promise Linux/Windows tray support. Keep wording generic about future tray-capable platforms, but describe only the behavior actually implemented now.

## Checkpoints

### [x] Checkpoint 1: Define the Launch Contract and Cross-Platform Background Spawn

**Goal:**

- Add explicit daemon launch modes so `--daemon` backgrounds everywhere by default, `--foreground` forces an attached run, and `--no-tray` bypasses tray usage when a tray implementation is available.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `bat --paging=never src/asky/cli/main.py --line-range 2150:2255`
- `bat --paging=never src/asky/daemon/startup.py`
- `bat --paging=never scripts/watch_daemon.sh`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/daemon/launcher.py`
- `src/asky/cli/main.py`
- `src/asky/daemon/startup.py`
- `scripts/watch_daemon.sh`
- `tests/asky/cli/test_cli.py`
- `tests/asky/daemon/test_startup_registration.py`
- `tests/asky/daemon/test_daemon_menubar.py`
- Must not touch:
- `src/asky/plugins/gui_server/server.py`
- user-facing docs
- plugin config schemas
- Constraints:
- `--foreground` precedence is: explicit `--foreground` first, then legacy `-vv --daemon` compatibility, then background default.
- `--no-tray` affects only background launch selection. It must not override `--foreground`.
- Non-tray background child must be started via a shared helper, using a foreground child command so the child does not recursively background itself.
- Background spawn must close stdin and redirect stdout/stderr away from the terminal. Use the existing asky log directory rather than inventing a new unrelated runtime location.
- Keep the existing macOS tray child path, but move the launch decision into the shared launcher abstraction instead of keeping the branch inline in `main.py`.

**Steps:**

- [x] Step 1: Add parser support for `--foreground` and `--no-tray`, and thread both flags through the parsed namespace without changing unrelated CLI routes.
- [x] Step 2: Create `src/asky/daemon/launcher.py` with one launch-mode resolver and one background-spawn helper. Use:
- [x] `asky --xmpp-daemon --foreground` for headless background children.
- [x] `asky --xmpp-daemon --xmpp-menubar-child` for tray-backed background children.
- [x] platform-appropriate detached child kwargs, including `start_new_session=True`, `stdin=subprocess.DEVNULL`, and Windows-specific detached creation flags when available.
- [x] Step 3: Refactor `src/asky/cli/main.py` so `--daemon` dispatch goes through the launcher abstraction instead of open-coded macOS-only spawn logic. Keep `--xmpp-menubar-child` behavior intact.
- [x] Step 4: Preserve `-vv --daemon` as a compatibility foreground alias in this handoff, but implement it through the same launch-mode resolver so the hidden coupling is no longer scattered through `main.py`.
- [x] Step 5: Update `src/asky/daemon/startup.py` so service-manager commands use a foreground-running command and do not self-background. Keep the macOS menubar-child registration explicit where the existing LaunchAgent path depends on it.
- [x] Step 6: Update `scripts/watch_daemon.sh` so development auto-reload continues to restart an attached daemon process by default, using `--foreground`.

**Dependencies:**

- None.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_cli.py tests/asky/daemon/test_startup_registration.py tests/asky/daemon/test_daemon_menubar.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- '--foreground|--no-tray|xmpp-menubar-child' src/asky/cli/main.py src/asky/daemon/startup.py scripts/watch_daemon.sh`

**Done When:**

- Verification commands pass cleanly.
- `asky --daemon` and `asky --daemon --foreground` now have separate, explicit code paths with shared launch-mode resolution.
- Startup registration no longer points a managed service at a self-daemonizing command.
- A git commit is created with message: `daemon: add explicit launch modes and background spawn`

**Stop and Escalate If:**

- Windows detached-process behavior cannot be implemented with confidence using the standard library APIs available in this repo.
- The current LaunchAgent path cannot keep tray behavior without a deeper startup registration redesign.

### [x] Checkpoint 2: Fix GUI Persistence and Unify Startup Notices

**Goal:**

- Make the GUI sidecar writable and predictable in both foreground and background daemon runs, and print one concise startup summary that includes GUI URL or GUI warning information.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never src/asky/plugins/gui_server/plugin.py`
- `bat --paging=never src/asky/plugins/gui_server/server.py`
- `bat --paging=never tests/asky/plugins/gui_server/test_gui_server_plugin.py --line-range 1:260`
- `bat --paging=never tests/asky/plugins/gui_server/test_gui_server_auth.py`
- `uv run python - <<'PY'
import inspect
import nicegui.storage as s
print(inspect.getsource(s))
PY`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/daemon/launcher.py`
- `src/asky/plugins/gui_server/plugin.py`
- `src/asky/plugins/gui_server/server.py`
- `tests/asky/plugins/gui_server/test_gui_server_plugin.py`
- `tests/asky/plugins/gui_server/test_gui_server_auth.py`
- `tests/asky/cli/test_cli.py`
- Must not touch:
- startup registration files
- user-facing docs in this checkpoint
- Constraints:
- NiceGUI storage must resolve to `context.data_dir / ".nicegui"` or an equivalently explicit path under the `gui_server` plugin data dir. Do not use cwd-relative fallback behavior.
- Startup notices must be generated from one formatter/helper used by both background and foreground daemon entrypoints.
- GUI URL printing is config/roster-aware: print URL only when `gui_server` is enabled and password is available from config or `ASKY_GUI_PASSWORD`.
- Missing GUI password must produce a warning line, not a hard crash in the parent CLI process.

**Steps:**

- [x] Step 1: Extend the shared daemon launcher helper with a `DaemonLaunchNotice` or equivalent structured summary that includes:
- [x] log directory path
- [x] spawned PID for background runs
- [x] whether tray was used
- [x] GUI URL when `gui_server` is enabled and password-configured
- [x] GUI warning when `gui_server` is enabled but password is missing
- [x] Step 2: Update foreground daemon startup to print the same notice format before entering the long-running loop.
- [x] Step 3: Pass an explicit NiceGUI storage path from `GUIServerPlugin` into `NiceGUIServer`, rooted under the plugin data dir.
- [x] Step 4: In `NiceGUIServer._run_thread` / `_default_runner`, set `NICEGUI_STORAGE_PATH` before importing or running NiceGUI so its persistence no longer resolves from cwd.
- [x] Step 5: Add tests that prove:
- [x] missing password still fails secure GUI startup, but startup notice warns clearly
- [x] configured password enables URL emission
- [x] storage path is rooted under the plugin data dir instead of `/.nicegui`
- [x] foreground daemon CLI path still exercises full daemon startup logic rather than a reduced XMPP-only path

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/gui_server/test_gui_server_plugin.py tests/asky/plugins/gui_server/test_gui_server_auth.py tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n 'NICEGUI_STORAGE_PATH|\.nicegui|admin console|password' src/asky/plugins/gui_server tests/asky/plugins/gui_server tests/asky/cli/test_cli.py`

**Done When:**

- Verification commands pass cleanly.
- The user-reported `Read-only file system: '/.nicegui'` path is no longer reachable from shipped code.
- Daemon startup output now includes PID/log info and GUI URL or GUI warning as appropriate.
- A git commit is created with message: `gui: fix daemon startup notices and writable NiceGUI storage`

**Stop and Escalate If:**

- NiceGUI requires a different persistence contract than `NICEGUI_STORAGE_PATH` in the pinned dependency version.
- GUI startup notice generation cannot reliably determine whether `gui_server` is enabled from the existing plugin roster/config loaders without broader plugin-runtime side effects.

### [x] Checkpoint 3: Sync Public Surface, Dev Tooling, and Documentation

**Goal:**

- Make the public CLI/help/docs/test surface match the new daemon contract and keep repository tooling aligned with the behavior that ships.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never README.md --line-range 20:115`
- `bat --paging=never docs/xmpp_daemon.md --line-range 1:160`
- `bat --paging=never docs/configuration.md --line-range 180:230`
- `bat --paging=never docs/web_admin.md`
- `bat --paging=never docs/development.md --line-range 1:80`
- `bat --paging=never src/asky/cli/help_catalog.py --line-range 1:220`
- `bat --paging=never tests/integration/cli_recorded/cli_surface.py --line-range 100:150`
- `bat --paging=never tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py --line-range 1:140`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/cli/help_catalog.py`
- `src/asky/plugins/xmpp_daemon/plugin.py`
- `tests/integration/cli_recorded/cli_surface.py`
- `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`
- `tests/integration/cli_recorded/test_cli_surface_manifest.py`
- `README.md`
- `docs/xmpp_daemon.md`
- `docs/configuration.md`
- `docs/web_admin.md`
- `docs/plugins.md`
- `docs/troubleshooting.md`
- `docs/development.md`
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/daemon/AGENTS.md`
- `src/asky/plugins/AGENTS.md`
- Must not touch:
- root `AGENTS.md`
- add new README sections where no relevant section already exists
- unrelated persona docs
- Constraints:
- Help/docs must promote `--foreground` as the supported attached-run switch and describe `--daemon` as a backgrounding command.
- Keep platform wording generic where appropriate, but do not claim Linux/Windows tray support exists today.
- Update only existing relevant README/doc sections; do not create marketing-style new README coverage.
- `docs/development.md` and `scripts/watch_daemon.sh` must stay aligned.
- `ARCHITECTURE.md` updates must cover only the lifecycle and component-boundary changes actually implemented.

**Steps:**

- [x] Step 1: Update CLI help surface and plugin flag help so `--daemon`, `--foreground`, and `--no-tray` describe the new contract plainly.
- [x] Step 2: Update recorded CLI surface manifests and integration tests so the new public flags have ownership and the `--daemon` dispatch assertions track the new launcher boundary.
- [x] Step 3: Update user-facing docs in existing relevant sections:
- [x] `README.md`
- [x] `docs/xmpp_daemon.md`
- [x] `docs/configuration.md`
- [x] `docs/web_admin.md`
- [x] `docs/plugins.md`
- [x] `docs/troubleshooting.md`
- [x] `docs/development.md`
- [x] Step 4: Update internal project docs that must reflect the shipped behavior:
- [x] `ARCHITECTURE.md`
- [x] `devlog/DEVLOG.md`
- [x] `src/asky/cli/AGENTS.md`
- [x] `src/asky/daemon/AGENTS.md`
- [x] `src/asky/plugins/AGENTS.md`
- [x] Step 5: Run the full suite and compare runtime against the baseline in this plan. If runtime increases materially, document why in `devlog/DEVLOG.md` and make sure no new slow test was introduced without justification.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'`
- `uv run pytest tests/asky/cli/test_cli.py tests/asky/plugins/gui_server/test_gui_server_plugin.py tests/asky/plugins/gui_server/test_gui_server_auth.py tests/asky/daemon/test_startup_registration.py tests/asky/daemon/test_daemon_menubar.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- '--foreground|--no-tray|background process|admin console|watch_daemon' README.md docs src/asky/cli/help_catalog.py src/asky/plugins/xmpp_daemon/plugin.py`
- `TIMEFORMAT='TEST_RUNTIME_SECONDS=%3R'; time uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- All updated docs describe the same daemon contract and GUI expectations.
- Full-suite runtime is compared against the 32.597s baseline and any material delta is explained.
- A git commit is created with message: `docs: sync daemon launch contract and gui guidance`

**Stop and Escalate If:**

- The recorded CLI surface or help discoverability contracts require broader manifest changes outside the daemon-related flags touched here.
- A doc currently recommends behavior that cannot be made accurate without changing additional code outside this handoff’s scope.

## Behavioral Acceptance Tests

- Running `asky --daemon` on Linux starts a detached child, prints PID and log directory, and returns the shell prompt without requiring `-vv`.
- Running `asky --daemon` on macOS with tray support available still launches the tray child by default, prints PID/log guidance, and does not require the user to discover `-vv` for normal operation.
- Running `asky --daemon --no-tray` on a tray-capable system backgrounds a non-tray daemon child instead of launching the tray UI.
- Running `asky --daemon --foreground` on any platform keeps the daemon attached to the terminal and starts the GUI sidecar when the GUI plugin is enabled and password-configured.
- When `gui_server` is enabled and password is configured, startup output includes `http://127.0.0.1:8766/` or the configured host/port equivalent.
- When `gui_server` is enabled but password is missing, startup output warns that the GUI will not start securely and tells the user to configure the password or `ASKY_GUI_PASSWORD`.
- Interacting with the foreground daemon GUI no longer attempts to write to `/.nicegui`.
- `scripts/watch_daemon.sh` still gives developers an attached, auto-restarting daemon process after the CLI contract change.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| `--daemon` backgrounds by default everywhere | `uv run pytest tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'` |
| `--foreground` is the supported attached-run path | `rg -n -- '--foreground' src/asky/cli/help_catalog.py README.md docs/xmpp_daemon.md docs/development.md` |
| `--no-tray` bypasses tray usage | `uv run pytest tests/asky/cli/test_cli.py tests/asky/daemon/test_daemon_menubar.py -q -o addopts='-n0 --record-mode=none'` |
| service-manager commands do not self-daemonize | `uv run pytest tests/asky/daemon/test_startup_registration.py -q -o addopts='-n0 --record-mode=none'` |
| GUI URL / GUI warning appears in startup output | `uv run pytest tests/asky/cli/test_cli.py tests/asky/plugins/gui_server/test_gui_server_auth.py -q -o addopts='-n0 --record-mode=none'` |
| NiceGUI storage no longer uses root cwd fallback | `rg -n 'NICEGUI_STORAGE_PATH|\\.nicegui' src/asky/plugins/gui_server/server.py tests/asky/plugins/gui_server` |
| Public CLI surface manifests know about new flags | `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Docs/help are consistent with shipped behavior | `rg -n -- '--daemon|--foreground|--no-tray|background process|menu bar|tray' README.md docs src/asky/cli/help_catalog.py src/asky/plugins/xmpp_daemon/plugin.py` |
| Full regression suite still passes and runtime stays near baseline | `TIMEFORMAT='TEST_RUNTIME_SECONDS=%3R'; time uv run pytest -q` |

## Assumptions And Defaults

- Public flag names for this handoff are `--foreground` and `--no-tray`.
- `--foreground` wins over `--no-tray` when both are passed.
- `-vv --daemon` remains a compatibility foreground path in this handoff so existing debugging workflows do not break immediately, but docs/help should point users to `--foreground`.
- The GUI storage path should be rooted under the `gui_server` plugin data directory as `.nicegui`.
- Startup notices should print the existing asky log directory, not invent a new log location.
- The GUI URL is derived from the configured `gui_server` host/port and printed only when the plugin is enabled and password-configured.
- No new dependency is added in this handoff.
- Only existing relevant README/doc sections are updated; no new README sections are introduced solely for this feature.

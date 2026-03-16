# Linux and Windows Tray Counterparts via `pystray` (RALF)

## Summary

- This handoff adds Linux and Windows counterparts to the existing macOS menu bar app by keeping the tray/menu surface plugin-driven and implementing a new `pystray` backend for non-macOS desktop platforms.
- This handoff is stacked on top of `plans/in-progress/daemon-backgrounding-and-gui-startup-ralf-2026-03-15.md`. Do not start implementation until that launch-contract work is merged or the equivalent changes are already present in the worktree.
- Public daemon ownership moves back into core:
  - `--daemon` is a core CLI flag and help surface.
  - XMPP remains a daemon transport plugin and tray-menu contributor only.
  - Internal spawn flags must stop leaking XMPP ownership.
- Startup behavior is intentionally split:
  - Linux and macOS keep a headless service-style startup path configured from the console side.
  - Tray/menu login startup is managed from the tray/menu app itself.
  - Windows only gets tray-login startup in this handoff.
- Runtime precedence is explicit:
  - Tray runtime and headless daemon runtime are mutually exclusive.
  - If a tray app starts and a headless daemon is already running, the tray app takes over and replaces the headless runtime.
  - If a headless daemon starts while a tray app is already running, the headless start prints a clear “already running” message and exits.
- Packaging adds one new Python optional extra: `tray = ["pystray>=0.19.5"]`.
  - Do not add Linux-specific Python GUI bindings as dependencies in this handoff.
  - Linux backend prerequisites stay OS-package/documentation territory.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `8d2275a1071f574531dd2e24921d6f492851b251`
- Last Reviewed HEAD: `none`
- Review Log:
  - None yet.

## Done Means

- `asky --daemon` is parsed and documented by core CLI code, not contributed by `xmpp_daemon`.
- macOS keeps the current menu bar runtime through `rumps`.
- Windows and Linux gain a tray implementation through `pystray` when a menu-capable backend is available.
- On Linux, public `--daemon` prefers tray only when `pystray` is installed, a desktop session is present, and the selected backend reports menu support. Otherwise it falls back to the existing headless background daemon path.
- On Windows, public `--daemon` prefers tray when `pystray` is installed; otherwise it falls back to the headless background daemon path.
- Explicit tray-child launches never silently fall back to headless mode. They fail fast with install/backend guidance.
- Tray/menu items remain fully driven by `TrayController` and plugin-contributed `TRAY_MENU_REGISTER` entries:
  - XMPP status/action items
  - GUI server items
  - tray-login toggle
  - quit item
- Linux and macOS still support headless auto-start without any tray/menu UI from the console/config path.
- Tray/menu auto-start is a separate path from headless service auto-start:
  - tray UI controls tray-login startup
  - console/config controls headless service startup on Linux/macOS
- Enabling one auto-start path on Linux/macOS best-effort disables the other path so users do not keep both configured by accident.
- If both are configured anyway and the tray runtime wins the race, the tray runtime disables the headless auto-start registration, stops the live headless runtime, and replaces it.
- Help text, manifests, tests, docs, `ARCHITECTURE.md`, and `devlog/DEVLOG.md` all reflect the shipped behavior.

## Critical Invariants

- `--daemon` is core-owned. No plugin may contribute or define the public daemon flag.
- XMPP remains transport-only:
  - it registers `DAEMON_TRANSPORT_REGISTER`
  - it contributes tray menu entries
  - it does not own public daemon CLI parsing or help copy
- Tray/menu UI stays generic and plugin-driven. Core tray code must not import `asky.plugins.xmpp_daemon`.
- `--daemon --foreground --no-tray` remains the explicit headless foreground daemon path from the prerequisite handoff.
- Tray availability on Linux requires all of:
  - `pystray` import succeeds
  - a desktop session indicator exists (`DISPLAY` or `WAYLAND_DISPLAY`)
  - `pystray.Icon.HAS_MENU` is `True`
- Linux `xorg` backend without menu support is not good enough for asky tray mode. Public `--daemon` must fall back to headless in that case.
- Explicit tray-child launches must not silently become headless launches.
- Tray/menu login startup and headless service startup are separate registrations on Linux/macOS and must not share the same label/file/path.
- On Linux/macOS, enabling tray-login startup must best-effort disable headless service startup, and enabling headless service startup from the console side must best-effort disable tray-login startup.
- At runtime there may be only one active daemon owner process:
  - tray runtime
  - or headless daemon runtime
  - never both
- Tray startup wins over headless runtime if both collide.
- If tray takes over from a headless runtime, the headless runtime must be stopped before the tray runtime begins owning daemon control.
- Windows only gets tray-login startup in this handoff. Console-configured headless auto-start remains unsupported on Windows.
- macOS keeps the existing tray-login LaunchAgent label/path in this handoff to avoid unnecessary migration risk.

## Forbidden Implementations

- Do not keep `--daemon` as a `CLIContribution` in `src/asky/plugins/xmpp_daemon/plugin.py`.
- Do not keep translating public `--daemon` to `--xmpp-daemon`.
- Do not keep the hidden tray-child flag named `--xmpp-menubar-child`.
- Do not add `PyGObject`, `gtk`, `ayatana`, or similar Linux backend bindings as Python dependencies in `pyproject.toml`.
- Do not treat Linux tray mode as “supported” when `pystray.Icon.HAS_MENU` is `False`.
- Do not let tray/menu implementations build XMPP-specific menu items directly in core tray code.
- Do not keep a single ambiguous “Run at login” meaning across tray UI and console config on Linux/macOS.
- Do not let tray-login startup and headless service startup stay simultaneously enabled on Linux/macOS when one path is newly enabled.
- Do not allow duplicate live runtimes. The new tray work must not rely only on the current macOS menubar singleton lock.
- Do not rename the existing macOS tray-login LaunchAgent label/path in this handoff.
- Do not promise universal Linux tray support in docs. Limit claims to menu-capable desktop backends with a headless fallback.

## Checkpoints

### [ ] Checkpoint 1: Normalize Core Daemon Ownership and Generic Internal Flags

**Goal:**

- Move public daemon ownership into core CLI code and remove XMPP-branded daemon ownership from both public and hidden launch surfaces.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `bat --paging=never plans/in-progress/daemon-backgrounding-and-gui-startup-ralf-2026-03-15.md`
- `bat --paging=never src/asky/cli/main.py --line-range 520:555`
- `bat --paging=never src/asky/cli/main.py --line-range 1040:1095`
- `bat --paging=never src/asky/cli/main.py --line-range 2120:2235`
- `bat --paging=never src/asky/cli/help_catalog.py --line-range 200:270`
- `bat --paging=never src/asky/cli/__init__.py --line-range 1:60`
- `bat --paging=never src/asky/plugins/xmpp_daemon/plugin.py --line-range 1:120`
- `bat --paging=never src/asky/plugins/xmpp_daemon/command_executor.py --line-range 60:90`
- `bat --paging=never src/asky/daemon/launcher.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/cli/main.py`
- `src/asky/cli/help_catalog.py`
- `src/asky/cli/__init__.py`
- `src/asky/daemon/launcher.py`
- `src/asky/daemon/launch_context.py`
- `src/asky/daemon/startup.py`
- `src/asky/daemon/app_bundle_macos.py`
- `src/asky/plugins/xmpp_daemon/plugin.py`
- `src/asky/plugins/xmpp_daemon/command_executor.py`
- `tests/asky/cli/test_cli.py`
- `tests/asky/daemon/test_app_bundle_macos.py`
- `tests/asky/daemon/test_startup_registration.py`
- `tests/asky/plugins/xmpp_daemon/test_xmpp_commands.py`
- `tests/asky/plugins/test_plugin_dependency_issues.py`
- `tests/integration/cli_recorded/cli_surface.py`
- `tests/integration/cli_recorded/test_cli_surface_manifest.py`
- `tests/integration/cli_recorded/test_cli_daemon_surface_recorded.py`
- `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`
- Must not touch:
- tray backend implementation files beyond flag-name propagation
- startup registration split files for tray vs headless
- user-facing docs in this checkpoint
- Constraints:
- Treat `plans/in-progress/daemon-backgrounding-and-gui-startup-ralf-2026-03-15.md` as a prerequisite. If its launch-mode refactor is not present, stop.
- Keep public flags from the prerequisite handoff unchanged: `--daemon`, `--foreground`, `--no-tray`.
- Remove public `--daemon` plugin ownership entirely.
- Keep `--edit-daemon` internal in this handoff; only genericize daemon launch ownership, not the daemon editor alias.
- Rename the hidden tray-child flag to `--tray-child`.
- Replace `LaunchContext.MACOS_APP` with `LaunchContext.TRAY_APP`.

**Steps:**

- [ ] Step 1: Remove `--daemon` from plugin-contributed CLI ownership.
- [ ] Step 2: Add core parser/help ownership for `--daemon` so plugin bootstrap is no longer needed just to parse that flag.
- [ ] Step 3: Delete the `--daemon -> --xmpp-daemon` translation and make daemon dispatch use a direct core `args.daemon` flag.
- [ ] Step 4: Replace `--xmpp-menubar-child` with hidden `--tray-child` everywhere:
- [ ] CLI parser
- [ ] launcher child commands
- [ ] macOS app bundle launcher
- [ ] startup command builders
- [ ] remote blocked-flag list
- [ ] manifests and tests
- [ ] Step 5: Rename the launch context enum from `MACOS_APP` to `TRAY_APP` and update all references/tests.
- [ ] Step 6: Move recorded CLI ownership for `--daemon` into a core daemon surface test file and remove it from plugin-surface ownership.

**Dependencies:**

- Depends on the backgrounding handoff already being landed or mirrored in the worktree.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/cli/test_cli.py tests/asky/plugins/xmpp_daemon/test_xmpp_commands.py tests/asky/plugins/test_plugin_dependency_issues.py tests/asky/daemon/test_app_bundle_macos.py tests/asky/daemon/test_startup_registration.py -q -o addopts='-n0 --record-mode=none'`
- `uv run pytest tests/integration/cli_recorded/test_cli_daemon_surface_recorded.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- '--xmpp-daemon|--xmpp-menubar-child' src tests`
- `rg -n -- '--daemon' src/asky/plugins/xmpp_daemon/plugin.py`

**Done When:**

- Verification commands pass cleanly.
- No public daemon ownership remains in `xmpp_daemon`.
- Internal daemon-child launch surfaces use generic naming.
- A git commit is created with message: `daemon: move public daemon ownership into core`

**Stop and Escalate If:**

- The prerequisite daemon-backgrounding refactor is not available yet.
- Removing plugin bootstrap from `--daemon` breaks unrelated CLI parser assumptions outside the daemon surface.

### [ ] Checkpoint 2: Add Shared Runtime Ownership and Cross-Platform Tray Backend Selection

**Goal:**

- Add a generic tray runtime layer that supports macOS via `rumps`, Linux/Windows via `pystray`, and a shared single-owner policy between tray and headless runtimes.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never src/asky/daemon/tray_protocol.py`
- `bat --paging=never src/asky/daemon/tray_controller.py`
- `bat --paging=never src/asky/daemon/tray_macos.py`
- `bat --paging=never src/asky/daemon/menubar.py`
- `bat --paging=never src/asky/daemon/service.py`
- `bat --paging=never src/asky/daemon/launcher.py`
- `bat --paging=never tests/asky/daemon/test_daemon_menubar.py`
- `python3 - <<'PY'
import json, urllib.request
print(json.load(urllib.request.urlopen("https://pypi.org/pypi/pystray/json"))["info"]["version"])
PY`

**Scope & Blast Radius:**

- May create/modify:
- `pyproject.toml`
- `src/asky/daemon/tray.py`
- `src/asky/daemon/tray_runtime.py`
- `src/asky/daemon/tray_pystray.py`
- `src/asky/daemon/tray_macos.py`
- `src/asky/daemon/menubar.py`
- `src/asky/daemon/tray_protocol.py`
- `src/asky/daemon/tray_controller.py`
- `src/asky/daemon/launcher.py`
- `src/asky/cli/main.py`
- `tests/asky/daemon/test_daemon_tray.py`
- `tests/asky/daemon/test_daemon_menubar.py`
- `tests/asky/cli/test_cli.py`
- Must not touch:
- startup registration split files yet
- docs in this checkpoint
- XMPP transport logic except as required by runtime-owner collision tests
- Constraints:
- Add one optional dependency extra only: `tray = ["pystray>=0.19.5"]`.
- Use the existing `src/asky/data/icons/asky_icon_mono.ico` asset for `pystray`; do not add new tray artwork in this handoff.
- Shared tray selection rules:
- macOS: use `rumps` when available
- Windows: use `pystray` when import succeeds and `Icon.HAS_MENU` is true
- Linux: use `pystray` only when import succeeds, desktop-session env exists, and `Icon.HAS_MENU` is true
- Public `--daemon` may fall back to headless mode when tray support is unavailable.
- Explicit hidden `--tray-child` must fail fast with a clear tray-backend error instead of falling back.
- Add a shared runtime-owner registry for daemon processes that records:
- owning PID
- owner mode (`tray` or `headless`)
- origin metadata needed to decide takeover messaging/logging
- Tray runtime must take over from headless runtime when it starts and finds a live headless owner.
- Headless runtime must exit immediately with a clear “already running” message if a live tray owner already exists.

**Steps:**

- [ ] Step 1: Add `tray = ["pystray>=0.19.5"]` to `pyproject.toml`.
- [ ] Step 2: Introduce a shared runtime-owner helper module for live daemon ownership and mutual exclusion between tray and headless modes.
- [ ] Step 3: Add a generic tray launcher module that chooses macOS `rumps` vs Linux/Windows `pystray`.
- [ ] Step 4: Implement `PystrayTrayApp` using `pystray.Menu` and the existing `TrayController` data model:
- [ ] plugin status rows render disabled menu items
- [ ] plugin action rows render clickable menu items
- [ ] tray-login item and quit item are appended by core
- [ ] warning rows are rendered as disabled menu items on pystray platforms and logged once
- [ ] Step 5: Update the launcher path so public `--daemon` uses generic tray availability checks instead of macOS-only `rumps` checks.
- [ ] Step 6: Wire runtime-owner rules:
- [ ] tray takeover stops a live headless owner before the tray runtime claims ownership
- [ ] headless launch exits when a tray owner already exists
- [ ] tray-vs-tray duplicate launch exits cleanly with the existing already-running behavior
- [ ] Step 7: Add unit tests for:
- [ ] Windows pystray menu-capable launch
- [ ] Linux fallback when `Icon.HAS_MENU` is false
- [ ] explicit `--tray-child` failure when tray backend is unavailable
- [ ] runtime-owner precedence and duplicate suppression

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/daemon/test_daemon_tray.py tests/asky/daemon/test_daemon_menubar.py tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- 'pystray|HAS_MENU|tray = \\[' pyproject.toml src/asky/daemon tests/asky/daemon`

**Done When:**

- Verification commands pass cleanly.
- A Linux or Windows desktop session with a menu-capable backend can launch a tray app through the generic core tray path.
- Public `--daemon` falls back headless when tray support is unavailable, while explicit tray-child launch does not.
- Live tray/headless ownership is mutually exclusive.
- A git commit is created with message: `daemon: add pystray tray backend and runtime ownership`

**Stop and Escalate If:**

- `pystray` cannot support dynamic menu rebuilding well enough to mirror the existing tray controller contract.
- The runtime-owner takeover logic cannot be made reliable without a new dependency.

### [ ] Checkpoint 3: Split Headless Service Startup from Tray-Login Startup

**Goal:**

- Keep headless auto-start on Linux/macOS from the console side, add tray-login startup on tray-supported platforms, and make each startup surface unambiguous.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never src/asky/daemon/startup.py`
- `bat --paging=never src/asky/daemon/startup_linux.py`
- `bat --paging=never src/asky/daemon/startup_macos.py`
- `bat --paging=never src/asky/daemon/startup_windows.py`
- `bat --paging=never src/asky/cli/daemon_config.py --line-range 130:235`
- `bat --paging=never src/asky/daemon/tray_controller.py --line-range 60:230`
- `bat --paging=never tests/asky/daemon/test_startup_registration.py`
- `bat --paging=never tests/asky/cli/test_daemon_config_cli.py`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/daemon/startup.py`
- `src/asky/daemon/startup_linux.py`
- `src/asky/daemon/startup_macos.py`
- `src/asky/daemon/startup_windows.py`
- `src/asky/daemon/startup_tray.py`
- `src/asky/daemon/startup_tray_linux.py`
- `src/asky/daemon/startup_tray_macos.py`
- `src/asky/daemon/startup_tray_windows.py`
- `src/asky/daemon/tray_protocol.py`
- `src/asky/daemon/tray_controller.py`
- `src/asky/cli/daemon_config.py`
- `tests/asky/daemon/test_startup_registration.py`
- `tests/asky/cli/test_daemon_config_cli.py`
- `tests/asky/daemon/test_daemon_tray.py`
- Must not touch:
- user-facing docs in this checkpoint
- Windows headless service registration UX
- Constraints:
- `src/asky/daemon/startup.py` remains the console-side headless startup dispatcher used by `daemon_config.py`.
- Add a separate tray-login dispatcher module for the tray/menu surface. Do not overload one status/toggle path with both meanings.
- Console-configured startup semantics:
- Linux: user systemd service
- macOS: LaunchAgent for headless daemon
- Windows: unsupported in this handoff
- Tray/menu startup semantics:
- macOS: tray/menu LaunchAgent
- Linux: `~/.config/autostart/asky-tray.desktop`
- Windows: Startup-folder script `asky-tray.cmd`
- On Linux/macOS, enabling one startup surface must best-effort disable the other startup surface.
- Rename tray/menu labels and prompts so they are explicit:
- tray UI: `Launch tray at login`
- console prompt: `Run headless daemon at login`
- Headless service startup commands must be explicit headless commands, not self-daemonizing tray-preferring commands.

**Steps:**

- [ ] Step 1: Keep `startup.py` as the headless-service dispatcher and make its Linux/macOS command builders explicit headless commands (`--daemon --foreground --no-tray`).
- [ ] Step 2: Add `startup_tray.py` plus per-platform tray-login registration modules:
- [ ] macOS tray-login LaunchAgent keeps the existing tray-login label/path
- [ ] Linux tray-login writes `~/.config/autostart/asky-tray.desktop`
- [ ] Windows tray-login writes `asky-tray.cmd`
- [ ] Step 3: Repurpose `startup_macos.py` into the headless LaunchAgent path for console-configured startup and give it a distinct daemon label/path from the tray-login LaunchAgent.
- [ ] Step 4: Rename the Linux headless service artifact to generic daemon naming (`asky-daemon.service`) instead of XMPP naming.
- [ ] Step 5: Update `daemon_config.py` to use headless startup status/toggles only and to best-effort disable tray-login startup on Linux/macOS when headless startup is enabled.
- [ ] Step 6: Update `TrayController` to use `startup_tray.py` and to best-effort disable headless startup on Linux/macOS when tray-login startup is enabled.
- [ ] Step 7: Add tests for:
- [ ] Linux/macOS startup-surface split
- [ ] Windows tray-only startup support
- [ ] mutual disabling when a startup surface is newly enabled
- [ ] explicit label wording in tray vs console

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/daemon/test_startup_registration.py tests/asky/cli/test_daemon_config_cli.py tests/asky/daemon/test_daemon_tray.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- 'asky-daemon.service|asky-tray.desktop|asky-tray.cmd|Launch tray at login|Run headless daemon at login' src tests`

**Done When:**

- Verification commands pass cleanly.
- Linux and macOS have separate headless-service and tray-login startup paths.
- Windows exposes only tray-login startup in this handoff.
- Tray/menu UI and console config no longer use the same ambiguous startup wording.
- A git commit is created with message: `daemon: split headless startup from tray login startup`

**Stop and Escalate If:**

- The macOS split between headless LaunchAgent and tray-login LaunchAgent needs broader migration work than this handoff can safely absorb.
- Linux desktop autostart cannot be made deterministic enough for the supported desktop sessions.

### [ ] Checkpoint 4: Enforce Runtime Precedence Between Tray and Headless Startup Paths

**Goal:**

- Make the tray runtime win cleanly over headless startup on Linux/macOS when users accidentally configure both startup paths.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never src/asky/daemon/tray_runtime.py`
- `bat --paging=never src/asky/daemon/tray.py`
- `bat --paging=never src/asky/daemon/startup.py`
- `bat --paging=never src/asky/daemon/startup_tray.py`
- `bat --paging=never src/asky/daemon/service.py`
- `bat --paging=never tests/asky/daemon/test_daemon_tray.py`
- `bat --paging=never tests/asky/cli/test_cli.py --line-range 960:1068`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/daemon/tray_runtime.py`
- `src/asky/daemon/tray.py`
- `src/asky/daemon/launcher.py`
- `src/asky/cli/main.py`
- `src/asky/daemon/startup.py`
- `src/asky/daemon/startup_tray.py`
- `tests/asky/daemon/test_daemon_tray.py`
- `tests/asky/cli/test_cli.py`
- Must not touch:
- docs in this checkpoint
- XMPP transport code unless required by already-running message assertions
- Constraints:
- On Linux/macOS, if tray runtime starts and a headless owner is live:
- disable headless startup registration best-effort
- stop or terminate the live headless owner
- then continue tray ownership
- If headless runtime starts while tray is already live:
- print a clear already-running message
- exit without replacing the tray owner
- If tray runtime starts and another tray owner is already live:
- keep the current duplicate-tray rejection behavior
- Runtime precedence work must not require adding a new dependency.

**Steps:**

- [ ] Step 1: Extend the runtime-owner helper to persist enough metadata to distinguish tray vs headless ownership.
- [ ] Step 2: When tray runtime starts on Linux/macOS, add takeover flow:
- [ ] disable headless startup registration best-effort
- [ ] stop the live headless runtime if possible
- [ ] claim tray ownership after the headless runtime is gone
- [ ] Step 3: Make headless runtime launch print and exit when tray ownership is already active.
- [ ] Step 4: Keep tray-vs-tray duplicate launch detection intact.
- [ ] Step 5: Add tests that simulate:
- [ ] tray takeover from headless on Linux/macOS
- [ ] headless refusal when tray is already running
- [ ] duplicate tray launch rejection

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/daemon/test_daemon_tray.py tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks:
- `rg -n -- 'tray|headless|already running|takeover' src/asky/daemon tests/asky/daemon tests/asky/cli/test_cli.py`

**Done When:**

- Verification commands pass cleanly.
- Tray startup wins over headless runtime on Linux/macOS when both collide.
- Headless runtime exits when a tray runtime already owns the daemon.
- A git commit is created with message: `daemon: enforce tray precedence over headless runtime`

**Stop and Escalate If:**

- Clean tray takeover from a live headless runtime cannot be done reliably without platform-specific service-manager coordination beyond this handoff.

### [ ] Checkpoint 5: Sync Docs, Architecture, Agent Notes, and Full Regression

**Goal:**

- Make the public docs and internal project docs match the shipped daemon/tray split and verify the final implementation on a clean branch.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `bat --paging=never README.md --line-range 20:40`
- `bat --paging=never docs/xmpp_daemon.md --line-range 1:145`
- `bat --paging=never docs/configuration.md --line-range 180:225`
- `bat --paging=never docs/plugins.md`
- `bat --paging=never docs/troubleshooting.md --line-range 160:230`
- `bat --paging=never docs/library_usage.md --line-range 340:360`
- `bat --paging=never ARCHITECTURE.md --line-range 560:690`
- `bat --paging=never src/asky/daemon/AGENTS.md`
- `bat --paging=never src/asky/cli/AGENTS.md`
- `bat --paging=never src/asky/plugins/AGENTS.md`
- `bat --paging=never src/asky/plugins/xmpp_daemon/AGENTS.md`
- `bat --paging=never devlog/DEVLOG.md`

**Scope & Blast Radius:**

- May create/modify:
- `README.md`
- `docs/xmpp_daemon.md`
- `docs/configuration.md`
- `docs/plugins.md`
- `docs/troubleshooting.md`
- `docs/library_usage.md`
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `src/asky/daemon/AGENTS.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/plugins/AGENTS.md`
- `src/asky/plugins/xmpp_daemon/AGENTS.md`
- Must not touch:
- root `AGENTS.md`
- unrelated persona docs
- add new README sections solely for this feature
- Constraints:
- README changes must stay inside existing daemon/tray-related coverage.
- Docs must describe:
- core-owned `--daemon`
- XMPP as one transport plugin
- tray extra `asky-cli[tray]`
- Linux tray support only on menu-capable desktop backends
- Linux/macOS headless service startup from console/config
- tray-login startup from tray/menu UI
- Windows tray-login-only startup
- tray takeover precedence over headless when both are configured
- `ARCHITECTURE.md` must reflect the actual split between:
- daemon runtime ownership
- tray runtime ownership
- headless startup registration
- tray-login startup registration
- current in-memory single-process daemon design
- Update only existing relevant README/doc sections.

**Steps:**

- [ ] Step 1: Update user-facing docs to reflect the new daemon/tray model and platform split.
- [ ] Step 2: Update internal architecture and agent docs so future edits do not regress daemon ownership or startup-surface semantics.
- [ ] Step 3: Add a `devlog/DEVLOG.md` entry covering:
- [ ] core daemon ownership move
- [ ] pystray tray support
- [ ] startup-surface split
- [ ] tray-over-headless precedence rule
- [ ] Step 4: Run final targeted tests for daemon/tray surfaces plus recorded CLI manifests.
- [ ] Step 5: Run the full suite on the implementation branch and compare runtime against the clean-base reference from the prerequisite daemon-backgrounding plan (`1602 passed in 31.73s`, shell wall clock `32.597s` at base `8d2275a1071f574531dd2e24921d6f492851b251`).

**Dependencies:**

- Depends on Checkpoint 4.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/cli/test_cli.py tests/asky/cli/test_daemon_config_cli.py tests/asky/daemon/test_daemon_tray.py tests/asky/daemon/test_daemon_menubar.py tests/asky/daemon/test_startup_registration.py tests/asky/plugins/xmpp_daemon/test_xmpp_commands.py tests/integration/cli_recorded/test_cli_daemon_surface_recorded.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'`
- Run full regression:
- `TIMEFORMAT='TEST_RUNTIME_SECONDS=%3R'; time uv run pytest -q`
- Run doc/help checks:
- `rg -n -- '--daemon|--foreground|--no-tray|--tray-child|asky-cli\\[tray\\]|Launch tray at login|Run headless daemon at login' README.md docs ARCHITECTURE.md src/asky/daemon/AGENTS.md src/asky/cli/AGENTS.md src/asky/plugins/AGENTS.md src/asky/plugins/xmpp_daemon/AGENTS.md`

**Done When:**

- Verification commands pass cleanly.
- Docs and internal notes match the shipped behavior.
- Full-suite runtime is measured and compared against the clean-base reference.
- A git commit is created with message: `docs: sync daemon tray and startup split`

**Stop and Escalate If:**

- The full suite cannot be evaluated on a clean implementation branch because the prerequisite daemon-backgrounding work is still in flight.
- Any doc would need to describe behavior that is not actually implemented in the same handoff.

## Behavioral Acceptance Tests

- Running `asky --daemon` on macOS with `rumps` installed starts the existing menu bar app path and no longer depends on XMPP owning the public flag.
- Running `asky --daemon` on Windows with `asky-cli[tray]` installed starts a `pystray` tray app whose menu shows the same plugin-driven status/action items as macOS.
- Running `asky --daemon` on Linux with `asky-cli[tray]` installed but a backend where `pystray.Icon.HAS_MENU` is `False` falls back to the headless background daemon path instead of opening a broken icon-only tray shell.
- Running explicit hidden tray-child launch without a usable tray backend exits with a clear tray-backend/install error and does not start a headless daemon.
- `asky --daemon --foreground --no-tray` still starts the headless daemon in the terminal on all platforms.
- With incomplete XMPP config, tray launch still starts the tray shell; XMPP errors surface only when the tray tries to autostart or the user chooses `Start XMPP`.
- On Linux/macOS, `asky --config daemon edit` controls headless startup only and uses wording that makes that explicit.
- On Linux/macOS, the tray/menu `Launch tray at login` control affects only tray-login startup and never toggles the headless service path.
- On Linux/macOS, if a tray runtime starts while a headless daemon is already running, the tray runtime disables headless startup best-effort, stops the headless runtime, and takes over daemon ownership.
- On Linux/macOS, if a headless daemon starts while a tray runtime already owns the daemon, the headless start prints an already-running message and exits.
- On Windows, tray-login startup can be enabled from the tray UI, but console-side headless startup remains unsupported.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Public `--daemon` is core-owned | `rg -n -- '--daemon' src/asky/plugins/xmpp_daemon/plugin.py` |
| Hidden XMPP-branded daemon-child flags are gone | `rg -n -- '--xmpp-daemon|--xmpp-menubar-child' src tests` |
| Linux/Windows tray backend uses `pystray` | `rg -n -- 'pystray|HAS_MENU' pyproject.toml src/asky/daemon tests/asky/daemon` |
| Public `--daemon` falls back headless when Linux tray backend lacks menus | `uv run pytest tests/asky/daemon/test_daemon_tray.py -q -o addopts='-n0 --record-mode=none'` |
| Explicit tray-child launch fails fast when tray backend is unavailable | `uv run pytest tests/asky/daemon/test_daemon_tray.py tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'` |
| Tray/menu UI stays plugin-driven | `uv run pytest tests/asky/daemon/test_daemon_tray.py tests/asky/daemon/test_daemon_menubar.py -q -o addopts='-n0 --record-mode=none'` |
| Linux/macOS keep headless auto-start from console/config | `uv run pytest tests/asky/daemon/test_startup_registration.py tests/asky/cli/test_daemon_config_cli.py -q -o addopts='-n0 --record-mode=none'` |
| Tray-login startup is separate from headless startup | `rg -n -- 'startup_tray|Launch tray at login|Run headless daemon at login' src tests` |
| Windows exposes tray-login-only startup in this handoff | `uv run pytest tests/asky/daemon/test_startup_registration.py -q -o addopts='-n0 --record-mode=none'` |
| Tray runtime wins over headless runtime | `uv run pytest tests/asky/daemon/test_daemon_tray.py tests/asky/cli/test_cli.py -q -o addopts='-n0 --record-mode=none'` |
| Recorded CLI ownership moved from plugin to core | `uv run pytest tests/integration/cli_recorded/test_cli_daemon_surface_recorded.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'` |
| Docs and architecture match shipped behavior | `rg -n -- '--daemon|asky-cli\\[tray\\]|Launch tray at login|Run headless daemon at login' README.md docs ARCHITECTURE.md src/asky/daemon/AGENTS.md src/asky/cli/AGENTS.md src/asky/plugins/AGENTS.md src/asky/plugins/xmpp_daemon/AGENTS.md` |
| Final implementation still passes the full suite | `TIMEFORMAT='TEST_RUNTIME_SECONDS=%3R'; time uv run pytest -q` |

## Assumptions And Defaults

- The backgrounding handoff in `plans/in-progress/daemon-backgrounding-and-gui-startup-ralf-2026-03-15.md` lands first or is already mirrored locally before this work starts.
- The generic hidden tray-child flag name is `--tray-child`.
- `LaunchContext.TRAY_APP` replaces the current mac-only tray context name.
- The new tray Python extra is `asky-cli[tray]`.
- Linux tray support in this handoff targets menu-capable desktop backends only. If the backend cannot render menus, public `--daemon` falls back headless.
- Linux desktop-session detection uses `DISPLAY` or `WAYLAND_DISPLAY` as the minimum gating check for tray preference.
- Console/config startup continues to mean headless service startup on Linux/macOS.
- Tray/menu startup continues to mean tray-login startup on platforms where the tray UI exists.
- Enabling one startup surface on Linux/macOS should best-effort disable the other surface immediately to reduce accidental conflicts.
- Tray takeover from a live headless runtime is part of this handoff because the daemon model is still single-process and the tray app must be able to own daemon control when present.
- Windows does not gain a console-configured headless auto-start path in this handoff.
- macOS keeps its existing tray-login LaunchAgent label/path in this handoff; headless auto-start gets a separate LaunchAgent identity.
- No root `AGENTS.md` edits are needed.

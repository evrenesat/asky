# Plan: Convert XMPP Daemon to Built-in Plugin + System Tray Abstraction

## Overview

The XMPP daemon (`daemon/`) currently lives in core and is hard-wired into the CLI entry point and
macOS menubar. The goal is to:

1. Move the XMPP transport layer to a new built-in plugin (`plugins/xmpp_daemon/`).
2. Keep daemon lifecycle infrastructure (the `--xmpp-daemon` flag, macOS menubar, singleton lock,
   startup management) in core `daemon/`.
3. Add a `DAEMON_TRANSPORT_REGISTER` hook so the daemon runner can discover its transport from a
   plugin rather than from a hard import.
4. Introduce a `TrayApp` protocol in `daemon/` so the macOS-specific `rumps` menubar is an
   interchangeable implementation, and future Windows / Linux tray apps can follow the same
   interface without changing the business logic.

**Boundary rule:** `daemon/` = lifecycle, menubar, platform startup, lock files.
`plugins/xmpp_daemon/` = everything XMPP.

---

## Phases

### Phase 1: New hook — `DAEMON_TRANSPORT_REGISTER`

**Files changed:** `src/asky/plugins/hook_types.py`

Add to `hook_types.py`:

```python
DAEMON_TRANSPORT_REGISTER = "DAEMON_TRANSPORT_REGISTER"
```

Add to `SUPPORTED_HOOK_NAMES`.

Add two new dataclasses:

```python
@dataclass
class DaemonTransportSpec:
    """Transport contract for the primary daemon communication channel."""
    name: str
    run: Callable[[], None]    # blocking foreground loop
    stop: Callable[[], None]

@dataclass
class DaemonTransportRegisterContext:
    """Mutable payload for daemon transport registration."""
    transports: List[DaemonTransportSpec] = field(default_factory=list)
```

Semantics: exactly one transport is expected. If no plugin registers one, the daemon runner must
raise `DaemonUserError`. If more than one is registered, it is a configuration error (raise).

**Expected outcome:** New hook constant and payload types are importable. Existing hooks are
unchanged.

---

### Phase 2: Refactor `daemon/service.py` → transport-agnostic `DaemonService`

**Files changed:** `src/asky/daemon/service.py`

Replace `XMPPDaemonService` with `DaemonService`. All XMPP-specific imports are removed from this
module.

`DaemonService.__init__(plugin_runtime)`:
- Calls `init_db()`.
- Stores `plugin_runtime`.
- Fires `DAEMON_SERVER_REGISTER` (sidecar plugins register here, same as before).
- Fires `DAEMON_TRANSPORT_REGISTER` and stores the registered `DaemonTransportSpec`.
- Raises `DaemonUserError` if zero or >1 transports were registered.

`DaemonService.run_foreground()`:
- Starts sidecar plugin servers (from `DAEMON_SERVER_REGISTER`).
- Calls `self._transport.run()` (blocks).
- On exit (normal or exception): stops sidecar servers, shuts down plugin runtime.

`DaemonService.stop()`:
- Calls `self._transport.stop()`.

`run_daemon_foreground(double_verbose, plugin_runtime)` entry point remains, now constructs
`DaemonService` instead of `XMPPDaemonService`.

**Constraint:** The `XMPP_ENABLED` guard moves out of `service.py` and into the plugin (Phase 3).
`service.py` only cares that exactly one transport was registered.

**Expected outcome:** `daemon/service.py` has no XMPP imports. `daemon/menubar.py` and `cli/main.py`
still import from `daemon.service`, but now use `DaemonService`. Update those imports.

---

### Phase 3: Create `plugins/xmpp_daemon/` built-in plugin

**Files created/moved:**

Move these files from `daemon/` to `plugins/xmpp_daemon/`, updating all internal imports
(`from asky.daemon.X import Y` → `from asky.plugins.xmpp_daemon.X import Y`):

| Source (daemon/) | Destination (plugins/xmpp_daemon/) |
|---|---|
| `xmpp_client.py` | `xmpp_client.py` |
| `router.py` | `router.py` |
| `command_executor.py` | `command_executor.py` |
| `session_profile_manager.py` | `session_profile_manager.py` |
| `interface_planner.py` | `interface_planner.py` |
| `voice_transcriber.py` | `voice_transcriber.py` |
| `image_transcriber.py` | `image_transcriber.py` |
| `transcript_manager.py` | `transcript_manager.py` |
| `chunking.py` | `chunking.py` |

Create `plugins/xmpp_daemon/xmpp_service.py`:
- Contains `XMPPService` class: the run/stop logic previously embedded in `XMPPDaemonService`.
- `XMPPService.__init__(double_verbose)`: reads XMPP config constants, constructs
  `TranscriptManager`, `CommandExecutor`, `InterfacePlanner`, `VoiceTranscriber`,
  `ImageTranscriber`, `DaemonRouter`, `AskyXMPPClient` (same wiring as before).
- `XMPPService.run()`: calls `self._client.start_foreground()` — blocking.
- `XMPPService.stop()`: calls `self._client.stop()`.
- All queue/worker/send-chunked logic comes here from the old `XMPPDaemonService`.

Create `plugins/xmpp_daemon/plugin.py`:
- `XMPPDaemonPlugin(AskyPlugin)`.
- `activate(context)`:
  - Registers `DAEMON_TRANSPORT_REGISTER` callback.
- `_on_daemon_transport_register(payload: DaemonTransportRegisterContext)`:
  - Checks `XMPP_ENABLED`; if false, returns without registering (daemon will then raise
    `DaemonUserError` because zero transports are registered).
  - Creates `XMPPService(double_verbose=...)`.
  - Appends `DaemonTransportSpec(name="xmpp", run=service.run, stop=service.stop)` to
    `payload.transports`.

Create `plugins/xmpp_daemon/__init__.py` (empty).

**Update `plugins/manager.py` `MANIFEST_TEMPLATE`:**

Add:

```toml
[plugin.xmpp_daemon]
enabled = true
module = "asky.plugins.xmpp_daemon.plugin"
class = "XMPPDaemonPlugin"
capabilities = ["daemon_transport"]
```

**Constraint:** After this phase, `daemon/` must have zero imports from `asky.plugins.xmpp_daemon`.
The coupling is one-way: plugin → daemon types (errors, hook types). Not daemon → plugin.

**Edge case — `double_verbose`:** The `XMPPService` needs to know whether double-verbose was
requested. This flag originates in CLI args and currently flows into `XMPPDaemonService`. Carry it
via plugin config (the plugin reads it from `context.config`) or inject it into the transport spec.
Simpler: store it in the plugin context config, read from `general.toml` `debug_verbose = true`, OR
pass it as `context.config.get("double_verbose", False)` set before plugin runtime init. Document
the chosen approach.

**Expected outcome:** `asky --xmpp-daemon` still works end-to-end. Voice, image, group chat, all
router logic behave identically. Tests that import from moved modules must update their import
paths.

---

### Phase 4: System tray abstraction for future cross-platform support

**Goal:** Decouple the macOS `rumps` specifics from the daemon control business logic so that a
future Windows (`pystray`) or Linux tray app implementation can be dropped in.

**Files created/changed:**

Create `daemon/tray_protocol.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class TrayStatus:
    running: bool
    jid: str
    voice_enabled: bool
    startup_supported: bool
    startup_enabled: bool
    error: str

class TrayApp(ABC):
    """Abstract system tray application interface."""

    @abstractmethod
    def run(self) -> None:
        """Start the event loop. Blocking."""

    @abstractmethod
    def update_status(self, status: TrayStatus) -> None:
        """Push updated status into the tray UI."""
```

Create `daemon/tray_macos.py`:
- Extract `AskyMenubarApp` from `menubar.py` into `MacosTrayApp(TrayApp)`.
- `MacosTrayApp.run()`: creates the `rumps.App` and starts its event loop.
- `MacosTrayApp.update_status(status)`: updates rumps `MenuItem` titles.
- Daemon start/stop callbacks stay here, but call `DaemonService` (not `XMPPDaemonService`).
- `has_rumps()` function stays in `menubar.py` (it's a capability probe, not an app).

Refactor `daemon/menubar.py`:
- `run_menubar_app()` selects and instantiates the platform tray implementation:
  - macOS + rumps available → `MacosTrayApp(singleton_lock).run()`
  - other platforms or rumps unavailable → raise `RuntimeError` (same as before)
- Singleton lock management stays in `menubar.py`.
- `is_menubar_instance_running()`, `has_rumps()`, lock constants stay in `menubar.py`.

**Constraint:** `tray_macos.py` may import `rumps` — it is the macOS implementation. It must not be
imported unless on macOS with rumps available. The import is guarded inside `run_menubar_app()`.

**Expected outcome:** `menubar.py` API surface is unchanged (same functions, same call sites in
`cli/main.py`). `AskyMenubarApp` class no longer lives inside `menubar.py`. Adding a Linux/Windows
tray in the future means creating `tray_linux.py` / `tray_windows.py` implementing `TrayApp` and
routing to them in `run_menubar_app()`.

---

### Phase 5: Documentation, tests, and cleanup

**Files changed:**

`daemon/AGENTS.md`:
- Remove moved modules from the module table.
- Add `tray_protocol.py`, `tray_macos.py`.
- Update "Dependencies" and plugin integration sections.
- Remove XMPP-specific details that now belong to the plugin docs.

`plugins/AGENTS.md`:
- Add `xmpp_daemon/` to Built-in Plugins list with a brief description.

`ARCHITECTURE.md`:
- Update the Daemon layer diagram to show `DaemonService`, `tray_macos`.
- Move `xmpp_client`, `router`, `command_executor`, etc. into the Plugins diagram.
- Update XMPP Daemon Flow section.
- Update Decision 19 or add Decision 20 for the pluggable transport pattern.

`DEVLOG.md`:
- Record the refactor, moved modules, new hooks, and tray abstraction.

**Tests:**

- Any test importing `asky.daemon.router`, `asky.daemon.command_executor`, etc. must update its
  import path to `asky.plugins.xmpp_daemon.*`.
- `test_daemon_menubar.py`: update any direct reference to `XMPPDaemonService`; the menubar now
  uses `DaemonService`. Mock `DaemonService` instead.
- Add a unit test for `DaemonService` transport registration: verify `DaemonUserError` is raised
  when no transport is registered, and verify correct transport spec is called.
- Add a minimal test for `XMPPDaemonPlugin.activate` and
  `_on_daemon_transport_register`: verify that with `XMPP_ENABLED=True` a transport is appended,
  and with `XMPP_ENABLED=False` none is appended.
- Add tests for `TrayApp` protocol conformance: verify `MacosTrayApp` implements all abstract
  methods.

**Verification commands:**

```bash
# Full test suite — must pass with no regressions
uv run pytest tests/ -x -q

# Confirm moved modules are not imported from daemon namespace
grep -r "from asky.daemon.router" src/ tests/
grep -r "from asky.daemon.command_executor" src/ tests/
grep -r "from asky.daemon.xmpp_client" src/ tests/
grep -r "XMPPDaemonService" src/ tests/

# Confirm no daemon → plugin import
grep -r "from asky.plugins.xmpp_daemon" src/asky/daemon/

# Confirm daemon transport hook is in supported set
python -c "from asky.plugins.hook_types import SUPPORTED_HOOK_NAMES, DAEMON_TRANSPORT_REGISTER; assert DAEMON_TRANSPORT_REGISTER in SUPPORTED_HOOK_NAMES"
```

---

## Final Checklist

- [ ] `DAEMON_TRANSPORT_REGISTER` hook constant, `DaemonTransportSpec`, and
      `DaemonTransportRegisterContext` in `hook_types.py`
- [ ] `DaemonService` replaces `XMPPDaemonService` in `daemon/service.py`; no XMPP imports remain
- [ ] `XMPPDaemonPlugin` is registered in the built-in manifest template
- [ ] All moved modules update their `asky.daemon.*` imports to `asky.plugins.xmpp_daemon.*`
- [ ] `XMPP_ENABLED` check is in the plugin, not in `daemon/service.py`
- [ ] `TrayApp` ABC and `TrayStatus` defined in `daemon/tray_protocol.py`
- [ ] `MacosTrayApp` in `daemon/tray_macos.py` implements `TrayApp`
- [ ] `menubar.py` public API unchanged; `AskyMenubarApp` class removed from it
- [ ] `daemon/menubar.py` has zero rumps imports at module level (guarded in `run_menubar_app()`)
- [ ] Full test suite passes with no regressions
- [ ] `AGENTS.md` files updated in `daemon/` and `plugins/`
- [ ] `ARCHITECTURE.md` updated
- [ ] `DEVLOG.md` updated
- [ ] No debug/scratch files outside `temp/`
- [ ] No temporary "# TODO" or "# WIP" comments in code

## Notes

- `double_verbose` propagation to the XMPP plugin: since `DaemonService` no longer knows about the
  flag directly, the simplest approach is to pass it via a well-known plugin config key
  (`xmpp_daemon.double_verbose`) that `cli/main.py` injects into the plugin runtime config before
  activation. Document this injection point.
- The `--edit-daemon` command and `cli/daemon_config.py` are XMPP-focused settings UI; they stay in
  the CLI layer (not in the plugin) because they run without the plugin runtime. This is acceptable
  for v1 — a future improvement could have the plugin register its own settings editor.
- Backward compatibility: any external code importing `asky.daemon.XMPPDaemonService` will break.
  This is an internal refactor and no public API guarantee exists, so no shim is needed.

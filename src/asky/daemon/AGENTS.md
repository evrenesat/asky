# Daemon Package (`asky/daemon/`)

Core daemon lifecycle infrastructure. This package owns the foreground daemon entry point, macOS menubar app, startup-at-login support, and the transport-agnostic `DaemonService` coordinator. XMPP transport logic lives in `plugins/xmpp_daemon/` as a built-in plugin.

## Module Overview

| Module                      | Purpose                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| `service.py`                | `DaemonService` — transport-agnostic lifecycle: fires hooks, runs transport |
| `menubar.py`                | macOS singleton lock and thin `run_menubar_app()` launcher                  |
| `launch_context.py`         | `LaunchContext` enum + get/set/is_interactive helpers                       |
| `tray_protocol.py`          | `TrayApp` ABC, `TrayStatus`, `TrayPluginEntry` data contracts               |
| `tray_controller.py`        | `TrayController` — generic daemon service lifecycle + startup toggle        |
| `tray_macos.py`             | `MacosTrayApp(TrayApp)` — dynamic plugin-driven rumps menu                  |
| `app_bundle_macos.py`       | macOS `.app` bundle creation/update for Spotlight integration               |
| `startup.py`                | Cross-platform startup-at-login dispatcher                                  |
| `startup_macos.py`          | LaunchAgent plist management                                                |
| `startup_linux.py`          | systemd user service management                                             |
| `startup_windows.py`        | Windows Startup folder launcher script                                      |
| `errors.py`                 | Daemon-specific exception types                                             |

---

## Architecture: Core vs. Plugin Boundary

```
daemon/service.py (DaemonService)      — core, transport-agnostic lifecycle
    fires DAEMON_SERVER_REGISTER       — plugins add sidecar servers
    fires DAEMON_TRANSPORT_REGISTER    — exactly one plugin registers the transport
    runs transport.run()               — blocks until daemon stops

plugins/xmpp_daemon/plugin.py          — built-in plugin, registers XMPP transport
    creates XMPPService                — XMPP-specific service
    appends DaemonTransportSpec        — to the DAEMON_TRANSPORT_REGISTER context
```

**One-way dependency rule**: plugin code may import from `asky.daemon.errors`. Daemon core code must not import from plugin packages.

---

## DaemonService Lifecycle

1. `__init__`: calls `init_db()`, fires `DAEMON_SERVER_REGISTER` (collect sidecars), fires `DAEMON_TRANSPORT_REGISTER` (collect exactly one transport). Raises `DaemonUserError` if zero or multiple transports are registered.
2. `run_foreground()`: starts sidecar servers, calls `transport.run()` (blocking), stops sidecar servers and shuts down plugin runtime in `finally`.
3. `stop()`: delegates to `transport.stop()`.

---

## TrayApp Abstraction

`tray_protocol.py` defines the `TrayApp` ABC and shared state types:

- `TrayPluginEntry` — one contributed menu item (status row or action row); `get_label` is called each refresh, `on_action` is `None` for non-clickable rows, `autostart_fn` (optional) is invoked once at tray init
- `TrayStatus` — view-model: startup-at-login state + pre-computed labels + lists of plugin-contributed entries + startup warnings
- `TrayApp` — ABC with `run()` and `update_status(status)` methods

`tray_controller.py` provides `TrayController`, holding all platform-agnostic business logic: daemon service lifecycle (start/stop/toggle threading), startup-at-login toggle, and autostart delegation. It accepts `hook_registry` to fire `TRAY_MENU_REGISTER` at construction so plugins can contribute their own menu entries. XMPP/voice/GUI specifics live entirely in their respective plugins.

`tray_macos.py` provides `MacosTrayApp(TrayApp)`, a thin rumps wrapper. It gets the hook registry from the plugin runtime, creates a `TrayController`, and dynamically builds the menu from `plugin_status_entries` and `plugin_action_entries`. The only fixed core items are `status_startup`, `action_startup`, and `action_quit`.

`menubar.py` is a thin launcher: it acquires the singleton lock then delegates to `MacosTrayApp().run()`. It retains `MenubarSingletonLock`, `acquire_menubar_singleton_lock`, and `is_menubar_instance_running` helpers.

`launch_context.py` provides `LaunchContext` enum (`INTERACTIVE_CLI`, `DAEMON_FOREGROUND`, `MACOS_APP`) and module-level `get/set_launch_context()` / `is_interactive()` helpers. `main.py` sets the context before entering each daemon code path.

---

## Plugin Integration

- `DaemonService` fires `DAEMON_SERVER_REGISTER` at construction to collect sidecar specs.
- `DaemonService` fires `DAEMON_TRANSPORT_REGISTER` at construction to collect the transport. Exactly one transport must be registered.
- `gui_server` plugin registers a sidecar server via `DAEMON_SERVER_REGISTER`.
- `xmpp_daemon` plugin registers the XMPP transport via `DAEMON_TRANSPORT_REGISTER`.

---

## Authorization Model

Authorization is handled by `plugins/xmpp_daemon/router.py`.

### Direct messages (`chat` stanzas)

- Sender's full JID is checked against `allowlist` (configured in `xmpp.toml`).
- Allowlist entries support:
  - bare JID (`user@domain`) — allows any resource.
  - full JID (`user@domain/resource`) — pins one exact resource.
- Unauthorized senders are silently ignored (no response).

### Group chat (`groupchat` stanzas)

- The room's bare JID must be pre-bound in `room_session_bindings` (via a trusted-room invite or explicit bind command).
- Individual sender identity is not checked for authorization — any occupant of a bound room can send commands.

---

## Command Routing Order

Handled by `plugins/xmpp_daemon/router.py`. For each incoming message:

1. **Authorization / room guard** — drop if not authorized.
2. **Inline TOML upload** — validate and persist as session override.
3. **`/session` command surface** — `/session`, `/session new`, `/session child`, `/session <id|name>`, `/session clear`.
4. **Transcript confirmation shortcuts** — `yes` / `no` if a transcript is pending.
5. **Interface planner** — when configured and message is not command-prefixed.
6. **Command prefix gate** — messages starting with `command_prefix` (default `/asky`).
7. **Command vs. query heuristic** — remaining text.
8. **Remote policy gate** — blocked flags are rejected.
9. **`AskyClient.run_turn()`** — final execution.

Remote policy blocks config/bootstrap mutations (for example `--config ...`,
daemon startup flags, delete flags, and output side-effect flags).

---

## Per-JID Queue and Worker Lifecycle

`plugins/xmpp_daemon/xmpp_service.py` serializes all processing per conversation through a per-key queue:

- **Queue key**: room JID for groupchat, sender bare JID for direct messages.
- **Worker thread**: daemon thread per queue key, started on first message (or restarted if dead). Thread restart is guarded by `_jid_workers_lock`.
- **Ordering guarantee**: messages from the same conversation are processed in arrival order.
- **Shutdown**: worker threads are daemon threads; no graceful drain on abrupt termination.

---

## Ad-Hoc Commands (XEP-0050)

Implemented in `plugins/xmpp_daemon/adhoc_commands.py`. Registered at XMPP session start via
`XMPPService._on_xmpp_session_start()`.

`AdHocCommandHandler` requires `xep_0050` and `xep_0004` slixmpp plugins to be registered. If either
is absent, ad-hoc commands are silently disabled (text command surface still works normally).

### Registered Nodes

| Node                      | Type         | Description                                      |
|---------------------------|--------------|--------------------------------------------------|
| `asky#status`             | single-step  | Connected JID, voice/image feature flags         |
| `asky#list-sessions`      | single-step  | Recent sessions list                             |
| `asky#list-history`       | single-step  | Recent history summaries                         |
| `asky#list-transcripts`   | single-step  | Recent audio/image transcripts                   |
| `asky#list-tools`         | single-step  | All available LLM tool names                     |
| `asky#list-memories`      | single-step  | All saved user memories                          |
| `asky#list-prompts`       | two-step     | Run prompt alias (form: alias + optional text)  |
| `asky#list-presets`       | two-step     | Run preset (form: preset + optional args)        |
| `asky#query`              | two-step     | Run query (form: text, model, research, turns…)  |
| `asky#new-session`        | single-step  | Create and switch to a new session               |
| `asky#switch-session`     | two-step     | Switch to existing session (form: ID/name)       |
| `asky#clear-session`      | two-step     | Clear session messages (confirmation form)       |
| `asky#use-transcript`     | two-step     | Run transcript as query (form: transcript list)  |

### Authorization

Every handler (including multi-step second steps) checks IQ sender identity against the daemon
allowlist via `router.is_authorized()` using:
- full JID first (`user@domain/resource`) for strict allowlist entries,
- bare JID fallback (`user@domain`) for resource-agnostic allowlist entries.

For multi-step form submissions, the first authorized sender is cached in the ad-hoc `session` dict
and reused if the follow-up IQ stanza lacks a usable `from` field.

### Blocking Calls

All executor calls (`run_turn`, DB operations) run in `loop.run_in_executor(None, fn)` so the asyncio
event loop is never blocked.

### Ad-Hoc Query Delivery

- Query-style ad-hoc nodes (`asky#query`, `asky#list-prompts`, `asky#use-transcript`, and query-resolving `asky#list-presets`) return a confirmation note in the IQ response.
- The actual model result is delivered afterward as a regular chat/groupchat message through the existing per-conversation queue.
- During execution, a compact progress status message is updated approximately every 2 seconds. Message correction (`xep_0308`) is used when supported; otherwise updates are appended as new messages.

---

## Known Limitations

- **Single pending transcript per conversation**: only the most recent audio/image upload awaits confirmation.
- **No replay protection**: a replayed XMPP stanza would be processed again.
- **Group chat authorization is room-level**: any occupant of a bound room can send commands.
- **JID worker threads are daemon threads**: in-flight tasks may be lost on unclean shutdown.
- **Ad-hoc commands target direct JID only**: form commands use the sender's bare JID for session resolution, not room JID.

---

## Dependencies

```
daemon/
├── service.py → plugins/hook_types.py (fires hooks), storage/sqlite.py (init_db)
├── menubar.py → tray_macos.py (creates MacosTrayApp)
├── tray_macos.py → tray_controller.py, tray_protocol.py
├── tray_controller.py → cli/daemon_config.py, daemon/startup.py, daemon/service.py
└── tray_protocol.py (no daemon deps)

plugins/xmpp_daemon/
├── xmpp_service.py → xmpp_client.py, router.py, chunking.py
├── router.py → command_executor.py, session_profile_manager.py,
│               voice_transcriber.py, image_transcriber.py, transcript_manager.py
├── command_executor.py → api/client.py, session_profile_manager.py
└── session_profile_manager.py → storage/sqlite.py
```

# Daemon Package (`asky/daemon/`)

Core daemon lifecycle infrastructure. This package owns the foreground daemon entry point, macOS menubar app, startup-at-login support, and the transport-agnostic `DaemonService` coordinator. XMPP transport logic lives in `plugins/xmpp_daemon/` as a built-in plugin.

## Module Overview

| Module                      | Purpose                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| `service.py`                | `DaemonService` — transport-agnostic lifecycle: fires hooks, runs transport |
| `menubar.py`                | macOS singleton lock and thin `run_menubar_app()` launcher                  |
| `tray_protocol.py`          | `TrayApp` ABC and `TrayStatus` / `TrayDaemonState` data contracts           |
| `tray_macos.py`             | `MacosTrayApp(TrayApp)` — rumps-based menu bar implementation               |
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

- `TrayDaemonState` — `STOPPED`, `RUNNING`, `ERROR`
- `TrayStatus` — snapshot of daemon state, jid, voice_enabled, startup flags
- `TrayApp` — ABC with `run()` and `update_status(status)` methods

`tray_macos.py` provides `MacosTrayApp(TrayApp)`, the rumps-based macOS implementation.

`menubar.py` is a thin launcher: it acquires the singleton lock then delegates to `MacosTrayApp().run()`. It retains `MenubarSingletonLock`, `acquire_menubar_singleton_lock`, and `is_menubar_instance_running` helpers.

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

---

## Per-JID Queue and Worker Lifecycle

`plugins/xmpp_daemon/xmpp_service.py` serializes all processing per conversation through a per-key queue:

- **Queue key**: room JID for groupchat, sender bare JID for direct messages.
- **Worker thread**: daemon thread per queue key, started on first message (or restarted if dead). Thread restart is guarded by `_jid_workers_lock`.
- **Ordering guarantee**: messages from the same conversation are processed in arrival order.
- **Shutdown**: worker threads are daemon threads; no graceful drain on abrupt termination.

---

## Known Limitations

- **Single pending transcript per conversation**: only the most recent audio/image upload awaits confirmation.
- **No replay protection**: a replayed XMPP stanza would be processed again.
- **Group chat authorization is room-level**: any occupant of a bound room can send commands.
- **JID worker threads are daemon threads**: in-flight tasks may be lost on unclean shutdown.

---

## Dependencies

```
daemon/
├── service.py → plugins/hook_types.py (fires hooks), storage/sqlite.py (init_db)
├── menubar.py → tray_macos.py (creates MacosTrayApp)
├── tray_macos.py → daemon/tray_protocol.py, cli/daemon_config.py, daemon/startup.py
└── tray_protocol.py (no daemon deps)

plugins/xmpp_daemon/
├── xmpp_service.py → xmpp_client.py, router.py, chunking.py
├── router.py → command_executor.py, session_profile_manager.py,
│               voice_transcriber.py, image_transcriber.py, transcript_manager.py
├── command_executor.py → api/client.py, session_profile_manager.py
└── session_profile_manager.py → storage/sqlite.py
```

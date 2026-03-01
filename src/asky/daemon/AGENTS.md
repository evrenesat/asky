# Daemon Package (`asky/daemon/`)

Core daemon lifecycle infrastructure. This package owns the foreground daemon entry point, macOS menubar app, startup-at-login support, and the transport-agnostic `DaemonService` coordinator. XMPP transport logic lives in `plugins/xmpp_daemon/` as a built-in plugin.

## Module Overview

| Module                | Purpose                                                                     |
| --------------------- | --------------------------------------------------------------------------- |
| `service.py`          | `DaemonService` — transport-agnostic lifecycle: fires hooks, runs transport |
| `menubar.py`          | macOS singleton lock and thin `run_menubar_app()` launcher                  |
| `launch_context.py`   | `LaunchContext` enum + get/set/is_interactive helpers                       |
| `tray_protocol.py`    | `TrayApp` ABC, `TrayStatus`, `TrayPluginEntry` data contracts               |
| `tray_controller.py`  | `TrayController` — generic daemon service lifecycle + startup toggle        |
| `tray_macos.py`       | `MacosTrayApp(TrayApp)` — dynamic plugin-driven rumps menu                  |
| `app_bundle_macos.py` | macOS `.app` bundle creation/update for Spotlight integration               |
| `startup.py`          | Cross-platform startup-at-login dispatcher                                  |
| `startup_macos.py`    | LaunchAgent plist management                                                |
| `startup_linux.py`    | systemd user service management                                             |
| `startup_windows.py`  | Windows Startup folder launcher script                                      |
| `errors.py`           | Daemon-specific exception types                                             |

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

1. `__init__`: calls `init_db()`, fires `DAEMON_SERVER_REGISTER` (collect sidecars), fires `DAEMON_TRANSPORT_REGISTER` (collect at most one transport). Raises `DaemonUserError` if multiple transports are registered. Zero transports is allowed (sidecar-only mode).
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

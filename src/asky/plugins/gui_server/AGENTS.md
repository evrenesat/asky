# GUI Server Plugin (`plugins/gui_server/`)

Registers a NiceGUI sidecar server for daemon mode and exposes configuration/plugin pages.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint + daemon server registration hook |
| `server.py` | Background NiceGUI lifecycle manager |
| `pages/general_settings.py` | `general.toml` load/validate/save page helpers |
| `pages/plugin_registry.py` | Plugin UI extension page registry |

## Runtime Contract

- Plugin registers `DAEMON_SERVER_REGISTER` and appends one `DaemonServerSpec`.
- Server starts non-blocking in a daemon thread.
- Shutdown is explicit and isolated; server failures do not crash daemon startup.
- Health check returns `running`, `host`, `port`, and last startup error.

## User Entry Points (Current)

- Requires daemon runtime to be active (`asky --daemon` path).
- Default pages:
  - `/settings/general`
  - `/plugins`
- Default bind: `127.0.0.1:8766` (configurable via plugin config file).

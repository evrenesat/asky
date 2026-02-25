# GUI Pages (`plugins/gui_server/pages/`)

Page-level helpers used by the GUI sidecar plugin.

## Module Overview

| Module | Purpose |
| --- | --- |
| `general_settings.py` | Validate and persist `[general]` config updates |
| `plugin_registry.py` | Register and mount extension pages safely |

## Constraints

- Preserve unrelated TOML sections when writing `general.toml`.
- Return user-facing validation errors for malformed edits.
- Page mount failures must be isolated per page (one bad page cannot prevent others).

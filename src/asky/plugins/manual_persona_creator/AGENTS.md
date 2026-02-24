# Manual Persona Creator Plugin (`plugins/manual_persona_creator/`)

Creates and maintains local persona packages from manually provided prompts and sources.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint and hook registration |
| `tools.py` | Tool handlers and schema registration |
| `storage.py` | Persona file layout, metadata, atomic writes |
| `ingestion.py` | Source expansion + chunk normalization |
| `exporter.py` | ZIP export with metadata/prompt/chunks |

## Storage Contract

Persona root: `<plugin_data>/personas/<persona_name>/`

Required files:

- `metadata.toml`
- `behavior_prompt.md`
- `chunks.json`

`metadata.toml` must include `[persona]` with `schema_version`.

## Behavior Notes

- Persona names are validated with strict slug-style constraints.
- Writes are atomic (`.tmp` + replace) for metadata/prompt/chunks updates.
- Ingestion tolerates partial failures and returns warnings instead of failing whole operation.
- Export payload excludes absolute path leakage from source metadata.

## User Entry Points (Current)

This plugin currently has tool-call entry points only:

- `manual_persona_create`
- `manual_persona_add_sources`
- `manual_persona_list`
- `manual_persona_export`

It does not currently expose a dedicated GUI page or dedicated direct CLI flag.

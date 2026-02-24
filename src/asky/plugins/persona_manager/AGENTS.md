# Persona Manager Plugin (`plugins/persona_manager/`)

Imports persona packages, binds personas to sessions, and injects persona behavior/context at runtime.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint + hook handlers |
| `tools.py` | Persona manager tool registration |
| `importer.py` | Persona ZIP import + validation |
| `knowledge.py` | Embedding rebuild + similarity retrieval |
| `session_binding.py` | Session-to-persona persistent bindings |

## Hook Usage

- `SESSION_RESOLVED`: resolve active session and load persisted binding.
- `TOOL_REGISTRY_BUILD`: register persona manager tool surface.
- `SYSTEM_PROMPT_EXTEND`: append loaded persona behavior prompt.
- `PRE_PRELOAD`: inject top persona knowledge chunks into additional context.
- `TURN_COMPLETED`: clear turn-scoped session context.

## Invariants

- Persona import rejects path traversal and unsupported schema versions.
- Embeddings are rebuilt from normalized chunks during import.
- Session bindings are persisted by session id and restored on resume.

## User Entry Points (Current)

This plugin currently has tool-call entry points only:

- `persona_import_package`
- `persona_load`
- `persona_unload`
- `persona_current`
- `persona_list`

Operational note:

- `persona_load` requires an active session context.
- No dedicated persona GUI page or dedicated direct CLI flag exists yet.

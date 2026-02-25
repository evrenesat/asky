# Persona Manager Plugin (`plugins/persona_manager/`)

Imports persona packages, binds personas to sessions, and injects persona behavior/context at runtime.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint + hook handlers |
| `importer.py` | Persona ZIP import + validation |
| `knowledge.py` | Embedding rebuild + similarity retrieval |
| `session_binding.py` | Session-to-persona persistent bindings |
| `resolver.py` | Persona name/alias resolution |
| `errors.py` | Custom exception types for persona operations |

## Hook Usage

- `SESSION_RESOLVED`: resolve active session and load persisted binding.
- `TOOL_REGISTRY_BUILD`: intentionally empty - tools no longer registered (CLI-only).
- `SYSTEM_PROMPT_EXTEND`: append loaded persona behavior prompt.
- `PRE_PRELOAD`: inject top persona knowledge chunks into additional context.
- `TURN_COMPLETED`: clear turn-scoped session context.

## Invariants

- Persona import rejects path traversal and unsupported schema versions.
- Embeddings are rebuilt from normalized chunks during import.
- Session bindings are persisted by session id and restored on resume.

## User Entry Points

Persona management is now **CLI-first** and **deterministic**:

### CLI Commands

- `asky persona load <name>` - Load persona into current session
- `asky persona unload` - Unload current persona
- `asky persona current` - Show currently loaded persona
- `asky persona list` - List all available personas
- `asky persona import <path>` - Import persona from ZIP file
- `asky persona alias <alias> <persona>` - Create persona alias
- `asky persona unalias <alias>` - Remove persona alias
- `asky persona aliases [persona]` - List all aliases

### Mention Syntax

- `@persona_name` in query - Deterministically load persona before model invocation
- `@alias` in query - Load persona via alias

### Design Rationale

Persona selection is a **preprocessing operation** that occurs before model invocation, not during model execution. This ensures:

1. **Deterministic behavior** - User explicitly controls persona selection
2. **Session persistence** - Persona binding persists across queries
3. **No tool discovery** - Model doesn't need to discover persona tools
4. **Alias support** - Short aliases for frequently-used personas

### Operational Notes

- Persona load requires an active session context
- @mention syntax removes the mention token from query text
- Only one persona can be active per session
- Aliases are stored in plugin KVStore and persist across sessions

# Manual Persona Creator Plugin (`plugins/manual_persona_creator/`)

Creates and maintains local persona packages from manually provided prompts and sources.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint and hook registration |
| `storage.py`   | Persona file layout, metadata, atomic writes, book identity guards |
| `book_service.py`| UI-agnostic orchestration layer for authored-book preflight, ingestion, and inspection |
| `book_ingestion.py`| Multi-pass extraction pipeline and resumable job management |
| `book_lookup.py`| Metadata candidate lookup and preflight analysis |
| `ingestion.py` | (Legacy) General source expansion + chunk normalization |
| `exporter.py`  | ZIP export with metadata/prompt/chunks/authored-books |

## Authored Books Contract

The plugin manages a structured ingestion pipeline for long-form content.

### Invariants
- **Service-Driven**: All authored-book operations must go through `book_service.py`. The CLI and future UI surfaces must not open-code storage traversal or identity checks.
- **Identity Guard**: Canonical `book_key` (title+year or ISBN) is the source of truth for replacement/duplicate checks.
- **Fidelity**: Extraction must include structured viewpoints with evidence. Malformed LLM payloads must be rejected via strict validation, with errors accumulated as warnings in the report.
- **Durability**: Timings, warnings, and targets must be persisted in `report.json`.

### Inspection & Reports
- **Books**: Lists all completed books with metadata and viewpoint counts.
- **Reports**: Renders full ingestion lifecycle details (targets, actuals, warnings, timings).
- **Viewpoints**: Provides filtered/limited access to structured claims across persona content.

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

## User Entry Points

Persona creation is now **CLI-first** and **deterministic**:

### CLI Commands

- `asky persona create <name> --prompt <file>` - Create new persona from prompt file
- `asky persona add-sources <name> <sources...>` - Add knowledge sources to persona
- `asky persona export <name> [--output <path>]` - Export persona to ZIP file
- `asky persona list` - List all available personas

### Design Rationale

Persona creation operations are **user-driven** and occur outside of model execution. This ensures:

1. **Explicit control** - User creates personas intentionally, not via model discovery
2. **No tool surface** - Model cannot autonomously create or modify personas
3. **CLI-first workflow** - Direct commands for persona management
4. **File-based prompts** - Behavior prompts come from files, not inline strings

### Operational Notes

- Persona names must follow slug-style constraints (alphanumeric, underscore, hyphen)
- Writes are atomic (`.tmp` + replace) for metadata/prompt/chunks updates
- Ingestion tolerates partial failures and returns warnings
- Export excludes absolute path leakage from source metadata

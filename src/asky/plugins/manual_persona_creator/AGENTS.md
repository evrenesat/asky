# Manual Persona Creator Plugin (`plugins/manual_persona_creator/`)

Creates and maintains local persona packages using **Schema v3** foundation.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint and hook registration |
| `storage.py`   | Persona file layout, metadata, atomic writes, versioning (v3) |
| `knowledge_types.py`| Canonical catalog data structures and locked enums |
| `knowledge_catalog.py`| Persistence and rebuild logic for v3 knowledge catalog |
| `source_service.py`| Orchestration for manual source ingestion and deduplication |
| `book_service.py`| Orchestration layer for authored-book ingestion |
| `exporter.py`  | ZIP export with full v3 catalog and artifacts |

## Schema v3 Foundation

This version introduces a canonical knowledge catalog:
- `persona_knowledge/sources.json`: Track original sources with content fingerprints.
- `persona_knowledge/entries.json`: Maps knowledge entries (chunks, viewpoints) to sources.

### Ingestion and Deduplication
- `add-sources` uses deterministic content fingerprints.
- Duplicate content is skipped automatically at the source level.
- Re-ingesting existing sources returns a skipped count instead of appending duplicates.

## Authored Books Contract

Managed via `book_service.py`:
- **Identity Guard**: Canonical `book_key` is the source of truth.
- **Fidelity**: Viewpoints and evidence are projected into the canonical v3 catalog.
- **Reports**: Detailed ingestion metrics and warnings.

## Storage Contract

Persona root: `<plugin_data>/personas/<persona_name>/`

Required files:
- `metadata.toml` (schema_version = 3)
- `behavior_prompt.md`
- `chunks.json` (compatibility)
- `persona_knowledge/` (v3 catalog)

## Behavior Notes
- Writes are atomic (`.tmp` + replace).
- Export payload excludes absolute path leakage.
- Automatic catalog rebuild from v1/v2 artifacts on read/import.

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
| `runtime_index.py`| Rebuildable runtime index with embeddings and structured metadata |
| `exporter.py`  | ZIP export with full v3 catalog and artifacts |
| `source_job.py` | Resumable job orchestration for milestone-3 structured extraction |
| `source_prompts.py`| Kind-aware extraction prompts and validation logic |

## Schema v3 Foundation

This version introduces a canonical knowledge catalog:
- `persona_knowledge/sources.json`: Track original sources with content fingerprints.
- `persona_knowledge/entries.json`: Maps knowledge entries (chunks, viewpoints, facts, timeline) to sources.
- `persona_knowledge/conflict_groups.json`: Preserved contradictions between sources.

## Milestone 3: Source-Aware Ingestion and Review

Introduces a review boundary for third-party or mixed-attribution sources:
- **Durable Bundles**: Ingested sources are stored under `ingested_sources/<source_id>/` before approval.
- **Auto-Approval**: Authored primary short-form (articles, posts) projects immediately.
- **Review Boundary**: Biographies and interviews remain `pending` until explicit approval.
- **Structured Extraction**: Kind-aware strategies for viewpoints, facts, and timeline events.

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
- Export payload excludes absolute path leakage and derived `runtime_index.json`.
- Automatic catalog and runtime-index rebuild from v1/v2 artifacts on read/import.

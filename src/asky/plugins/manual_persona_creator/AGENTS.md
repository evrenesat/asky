# Manual Persona Creator Plugin (`plugins/manual_persona_creator/`)

Creates and maintains local persona packages using Schema v3.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint and hook registration |
| `storage.py` | Persona file layout, metadata, atomic writes, versioning |
| `knowledge_types.py` | Canonical catalog data structures and enums |
| `knowledge_catalog.py` | Persistence and rebuild logic for the v3 knowledge catalog |
| `source_service.py` | Orchestration for manual source ingestion and deduplication |
| `book_service.py` | Orchestration layer for authored-book ingestion |
| `gui_service.py` | Browser-facing adapters for persona/admin pages |
| `runtime_index.py` | Rebuildable runtime index with embeddings and structured metadata |
| `exporter.py` | ZIP export with full v3 catalog and artifacts |
| `source_job.py` | Resumable structured-extraction job orchestration |
| `source_prompts.py` | Kind-aware extraction prompts and validation logic |
| `web_service.py` | Orchestration for web collection and review |
| `web_job.py` | Background collection job logic |
| `web_types.py` | Typed models for web collection and review state |
| `web_prompts.py` | Web page classification and preview extraction prompts |

## Schema v3 Foundation

Canonical knowledge state lives under `persona_knowledge/`:

- `sources.json`
- `entries.json`
- `conflict_groups.json`

Persona root remains:

- `<plugin_data>/personas/<persona_name>/`

Required files:

- `metadata.toml`
- `behavior_prompt.md`
- `chunks.json` for compatibility
- `persona_knowledge/`

## Ingestion And Review Contracts

### Source-aware ingestion

- durable source bundles live under `ingested_sources/<source_id>/`
- biographies and interviews stay `pending` until approval
- authored primary short-form content can auto-project immediately
- duplicate content is skipped deterministically

### Guided web review

- scraped pages stage under `web_collections/<collection_id>/pages/<page_id>/`
- previews are extracted before approval
- approved pages materialize real source bundles
- retraction moves knowledge back behind the review boundary

### Authored books

- `book_service.py` owns the business rules
- canonical identity is the `book_key`
- ingestion reports carry warnings and stage timings

## GUI/Admin Boundaries

Browser flows for this plugin are service-first.

Use these layers:

- `gui_service.py` for browser-facing DTOs and page helpers
- `book_service.py` for authored-book business rules
- `source_service.py` for manual-source business rules and jobs
- `web_service.py` for intake, review, approval, rejection, and collection inspection

Do not:

- call CLI command handlers from browser pages
- shell out to `asky persona ...` commands to reuse logic
- bypass the review boundary in page code
- perform heavy ingestion or extraction directly inside page callbacks

Page code should:

1. collect browser input
2. validate and normalize it
3. call a service helper or create a job
4. enqueue durable work when needed
5. notify and navigate

## Current GUI Flows

### Authored book flow

Current browser flow is queue-backed:

1. collect a server-local source path
2. run authored-book preflight
3. convert preflight results into editable browser DTO state
4. let the user confirm or edit metadata and extraction targets
5. validate
6. submit through the service layer
7. enqueue `authored_book_ingest`

Rules to preserve:

- browser intake uses server-local paths today
- do not invent upload support in page code
- resumable jobs must stay explicit and reuse the existing service contract
- duplicate and identity-guard decisions belong in services, not in page heuristics

### Source ingest flow

Current browser flow:

1. collect server-local file or directory path
2. collect source kind
3. create a source ingestion job through `source_service.py`
4. enqueue `source_ingest`

Rules to preserve:

- browser code should not write bundles directly
- kind semantics stay owned by `PersonaSourceKind` and the service layer

### Web intake and review flow

Current browser flow:

1. intake a URL through `web_service.py`
2. navigate to collection review
3. inspect staged pages and previews
4. approve or reject explicitly

Rules to preserve:

- staged content must not affect runtime knowledge until approval
- page approval and rejection should call `web_service.py`
- browser pages must not project pending content implicitly

## Queue Contracts

Current registered GUI job names:

- `authored_book_ingest`
- `source_ingest`

Keep these explicit and documented when extending the plugin. Register new job names only when a workflow is meaningfully durable and should appear on `/jobs`.

## Behavior Notes

- writes are atomic via temp-file plus replace
- export payload excludes absolute-path leakage
- derived `runtime_index.json` is rebuildable and not the durable source of truth
- automatic catalog and runtime-index rebuild from older schema artifacts remains supported

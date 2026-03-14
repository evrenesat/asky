# RALF Handoff Plan: Persona Milestone 3, Source-Aware Ingestion, Review, And Conflict Preservation

## Summary

Implement roadmap milestone 3 as a new **source-aware ingestion and review layer** that expands personas beyond authored books while preserving trust boundaries. This milestone must ship:

- a new `source-*` persona CLI family,
- source-kind-specific extraction for `biography`, `autobiography`, `interview`, `article`, `essay`, `speech`, `notes`, and `posts`,
- rich structured extraction outputs for viewpoints, facts, timeline events, and linked conflict groups,
- explicit CLI review and promotion for mixed-attribution sources,
- approved-only projection into canonical persona knowledge and runtime artifacts,
- query surfaces for approved `facts`, `timeline`, and `conflicts`,
- no regression to existing `ingest-book`, `books`, `book-report`, `viewpoints --book`, or `add-sources` behavior.

This handoff is **not** allowed to collapse milestone 3 into generic chunk ingestion. The milestone must keep source-kind-aware extraction and must not let pending biography/interview material affect persona answering until approval.

Implementation and verification commands for this handoff must run inside the Linux VM checkout at `/home/evren/code/asky`. Current baseline before any implementation work:

- branch: `main`
- base HEAD: `a98eadcdc5a41812090f79450b315e97cc91d66e`
- full suite: `1535 passed in 15.53s`
- shell timing: `real 15.760 user 36.911 sys 4.880`

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `a98eadcdc5a41812090f79450b315e97cc91d66e`
- Last Reviewed HEAD: `approved+squashed; finalized plan intentionally omits the post-squash SHA`
- Review Log:
  - `2026-03-14`: reviewed `a98eadcdc5a41812090f79450b315e97cc91d66e..4c6b406092436401c406ae350baf867b184da642`, outcome `changes-requested`; follow-up plan `persona-milestone3-source-aware-ingestion-review-fixes-ralf-2026-03-14.md`
  - `2026-03-14`: reviewed `4c6b406092436401c406ae350baf867b184da642..38941a96f1828020a5ebe64aed0f2b1bf0a80365`, outcome `approved+squashed`; finalized the accumulated milestone-3 handoff from `a98eadcdc5a41812090f79450b315e97cc91d66e`

## Done Means

- New persona CLI commands exist with these exact public entrypoints:
  - `asky persona ingest-source <persona> <kind> <path>`
  - `asky persona sources <persona> [--status STATUS] [--kind KIND] [--limit N]`
  - `asky persona source-report <persona> <source_id>`
  - `asky persona approve-source <persona> <source_id>`
  - `asky persona reject-source <persona> <source_id>`
  - `asky persona facts <persona> [--source SOURCE_ID] [--topic QUERY] [--limit N]`
  - `asky persona timeline <persona> [--source SOURCE_ID] [--topic QUERY] [--year YEAR] [--limit N]`
  - `asky persona conflicts <persona> [--source SOURCE_ID] [--topic QUERY] [--limit N]`
- Existing `asky persona viewpoints <persona>` remains, and is extended to query approved viewpoints across authored books plus approved milestone-3 source bundles. Existing `--book` behavior remains valid, and a new `--source SOURCE_ID` filter is added without removing `--book`.
- Existing authored-book commands remain intact:
  - `ingest-book`
  - `reingest-book`
  - `books`
  - `book-report`
- Existing `add-sources` remains a legacy chunk-only path and is not silently redefined as the milestone-3 structured ingestion surface.
- Source kinds map exactly as follows:
  - `biography` -> `source_class=biography_or_autobiography`, `trust_class=third_party_secondary`, initial review status `pending`
  - `autobiography` -> `source_class=biography_or_autobiography`, `trust_class=authored_primary`, initial review status `approved`
  - `interview` -> `source_class=direct_interview`, `trust_class=mixed_attribution`, initial review status `pending`
  - `article`, `essay`, `speech`, `notes`, `posts` -> `source_class=manual_source`, `trust_class=authored_primary`, initial review status `approved`
- New durable source-bundle artifacts exist under the persona root:
  - `ingested_sources/<source_id>/source.toml`
  - `ingested_sources/<source_id>/report.json`
  - `ingested_sources/<source_id>/viewpoints.json`
  - `ingested_sources/<source_id>/facts.json`
  - `ingested_sources/<source_id>/timeline.json`
  - `ingested_sources/<source_id>/conflicts.json`
- New resumable source-ingestion jobs exist under:
  - `source_ingestion_jobs/<job_id>/job.toml`
  - stage scratch artifacts under the same job directory, excluded from export
- Approved or auto-approved milestone-3 sources project into canonical persona artifacts:
  - `persona_knowledge/sources.json`
  - `persona_knowledge/entries.json`
  - `persona_knowledge/conflict_groups.json`
  - compatibility `chunks.json`
  - derived `embeddings.json`
  - derived `persona_knowledge/runtime_index.json`
- Pending or rejected milestone-3 sources do **not** project into canonical knowledge, compatibility chunks, embeddings, or runtime index until explicitly approved.
- Approved milestone-3 viewpoint entries can participate in persona runtime retrieval after projection. Facts and timeline events are queryable from CLI, but are not injected as primary persona voice packets in this milestone.
- Export/import preserves `ingested_sources/**`, `persona_knowledge/conflict_groups.json`, and review status while still excluding all `source_ingestion_jobs/**` scratch state and `runtime_index.json`.
- Docs and affected `AGENTS.md` files are updated only for shipped milestone-3 behavior.
- Final regression passes with `uv run pytest -q`, and any runtime increase beyond `max(3.0s, 20%)` over `real 15.760` is investigated and explained before closing.

## Critical Invariants

- `add-sources` stays available as the existing chunk-only legacy ingestion path. Do not silently route it through milestone-3 source-aware extraction.
- Pending and rejected source bundles must remain fully inspectable through CLI reports, but they must never influence `persona_knowledge/**`, `chunks.json`, `embeddings.json`, `runtime_index.json`, or persona answer packets.
- Existing authored-book artifacts and commands remain the canonical authored-book path. Milestone 3 must not rename, merge, or reinterpret `authored_books/**`.
- Milestone-3 source bundles must use deterministic public `source_id` values. Use the same `source_id` across listing, report, approve, reject, export, and import.
- Source-kind-aware extraction must vary by kind. One generic prompt or one generic JSON schema for every source kind is not acceptable.
- Contradictions must be preserved as linked conflict groups. Do not deduplicate opposing claims into one “best” entry.
- Review approval is the only promotion boundary for pending sources. Do not allow `source-report` or query commands to promote by side effect.
- Auto-approved kinds must still produce the same per-source artifacts and reports as pending kinds. The difference is promotion timing, not artifact fidelity.
- The milestone stays additive to current persona storage. If implementation can stay within schema v3, keep schema v3; do not bump schema version unless implementation proves that additive support is impossible.
- No new third-party package dependency may be added. Reuse existing adapters, embeddings, local readers, and Rich CLI stack.
- Root `AGENTS.md` must not be modified.
- README must only be updated if an already relevant persona section exists. If no such section exists at implementation time, README stays untouched.

## Forbidden Implementations

- Do not overload `ingest-book` to handle biographies, interviews, or short-form source bundles.
- Do not overload `add-sources` with hidden `--kind` behavior or silently change its semantics.
- Do not auto-promote biographies or interviews into canonical persona knowledge on first ingest.
- Do not let pending biography or interview entries affect `viewpoints`, `facts`, `timeline`, `conflicts`, or persona runtime results.
- Do not flatten timeline events into unlabeled generic facts without explicit timeline structure.
- Do not store contradiction handling only as prose inside reports. There must be explicit conflict-group data.
- Do not export job scratch artifacts, temporary section vectors, or raw full-source bodies that are only needed during extraction.
- Do not mix review state into runtime planner logic by “filtering at read time” only. Pending/rejected entries must be excluded before canonical projection.
- Do not describe GUI review flows, web scraping, browser acquisition, or audio/diarization behavior in milestone-3 docs.

## Checkpoints

### [x] Checkpoint 1: Source Bundle Storage And Canonical Contract

**Goal:**

- Add the durable source-bundle, review-status, and conflict-group storage contract before any new CLI or extraction behavior is implemented.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/storage.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/knowledge_types.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/exporter.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/importer.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/source_types.py`
- `tests/asky/plugins/manual_persona_creator/test_source_storage.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/storage.py`
- `src/asky/plugins/manual_persona_creator/knowledge_types.py`
- `src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `src/asky/plugins/manual_persona_creator/exporter.py`
- `src/asky/plugins/persona_manager/importer.py`
- `tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py`
- `tests/asky/plugins/persona_manager/test_authored_book_import.py`
- Must not touch:
- `src/asky/cli/**`
- `src/asky/core/**`
- `src/asky/api/**`
- `tests/integration/**`
- Constraints:
- keep current authored-book storage untouched
- keep archive portability backward compatible
- keep milestone-3 source bundles separate from authored-book directories and separate from canonical approved knowledge

**Steps:**

- [x] Step 1: Add typed milestone-3 source models in `source_types.py` for:
  - source kind enum with exact public kinds `biography`, `autobiography`, `interview`, `article`, `essay`, `speech`, `notes`, `posts`
  - review status enum with exact states `approved`, `pending`, `rejected`
  - per-source metadata record
  - fact record
  - timeline-event record
  - conflict-group record
  - per-source report record
  - source-ingestion job manifest
- [x] Step 2: Extend storage helpers with exact canonical directories and files:
  - final source bundles under `ingested_sources/<source_id>/`
  - job artifacts under `source_ingestion_jobs/<job_id>/`
  - global approved conflict groups under `persona_knowledge/conflict_groups.json`
- [x] Step 3: Keep existing source and trust enums stable, and store milestone-3 kind detail in structured metadata instead of inventing new `source_class` values.
- [x] Step 4: Extend `PersonaEntryKind` additively with `timeline_event`. Keep `viewpoint`, `persona_fact`, and `evidence_excerpt` intact.
- [x] Step 5: Lock the exact deterministic milestone-3 `source_id` format to:
  - `source:<kind>:<sha256(normalized_bundle_text)[:16]>`
- [x] Step 6: Extend exporter/importer so persona packages include:
  - `ingested_sources/**`
  - `persona_knowledge/conflict_groups.json`
  and still exclude:
  - `source_ingestion_jobs/**`
  - `persona_knowledge/runtime_index.json`
- [x] Step 7: Keep authored-book and older schema portability intact. Existing v1/v2/v3 personas must still import and rebuild successfully.
- [x] Step 8: Add storage/import/export tests for:
  - deterministic source-id generation
  - source bundle round-trip
  - `conflict_groups.json` portability
  - job scratch exclusion
  - authored-book artifacts still round-trip unchanged

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_storage.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_knowledge_catalog.py tests/asky/plugins/manual_persona_creator/test_runtime_index.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A persona package can carry approved or pending milestone-3 source bundles without exporting job scratch.
- Existing authored-book import/export behavior still works.
- A git commit is created with message: `persona: add source bundle storage contract`

**Stop and Escalate If:**

- The milestone-3 storage contract cannot fit additively into the current persona package layout without a schema-version bump.
- Import/export compatibility would require dropping existing authored-book portability.

### [x] Checkpoint 2: Source-Aware Extraction, Review State, And Promotion Service

**Goal:**

- Implement the reusable milestone-3 backend that ingests new source kinds, writes reviewable source bundles, and promotes only approved knowledge into canonical persona artifacts.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/source_service.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/book_service.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/book_lookup.py`
- `sed -n '1,560p' src/asky/plugins/manual_persona_creator/book_ingestion.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/runtime_index.py`
- `sed -n '1,320p' src/asky/plugins/manual_persona_creator/ingestion.py`
- `find tests/asky/plugins/manual_persona_creator -maxdepth 1 -type f | sort`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/source_prompts.py`
- `src/asky/plugins/manual_persona_creator/source_job.py`
- `tests/asky/plugins/manual_persona_creator/test_source_job.py`
- `tests/asky/plugins/manual_persona_creator/test_source_review.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/source_service.py`
- `src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `src/asky/plugins/manual_persona_creator/runtime_index.py`
- `src/asky/plugins/manual_persona_creator/storage.py`
- `tests/asky/plugins/manual_persona_creator/test_source_service.py`
- `tests/asky/plugins/manual_persona_creator/test_runtime_index.py`
- Must not touch:
- `src/asky/cli/**`
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/plugins/persona_manager/plugin.py`
- Constraints:
- keep `add_manual_sources()` intact and backward compatible
- approved-only projection must happen in service/backend code, not by hiding pending items in CLI output only
- do not project pending/rejected source entries into canonical artifacts

**Steps:**

- [x] Step 1: Broaden `source_service.py` into the shared milestone-3 backend while preserving the existing `add_manual_sources()` entrypoint.
- [x] Step 2: Add exact reusable service entrypoints for:
  - `prepare_source_preflight(...)`
  - `create_source_ingestion_job(...)`
  - `update_source_job_inputs(...)`
  - `run_source_job(...)`
  - `list_source_bundles(...)`
  - `get_source_report(...)`
  - `approve_source_bundle(...)`
  - `reject_source_bundle(...)`
  - approved-query helpers for `viewpoints`, `facts`, `timeline`, and `conflicts`
- [x] Step 3: Support milestone-3 inputs exactly as follows:
  - single local file for every source kind
  - directory input only for `notes` and `posts`
  - manifest input only for `notes` and `posts`, where the manifest is UTF-8 text with one local path per line and optional `#` comments
- [x] Step 4: Add source-kind-aware extraction prompts and JSON validation:
  - `biography` and `autobiography` extract viewpoints, persona facts, timeline events, and conflict candidates
  - `interview` extracts persona-attributed viewpoints and facts with explicit attribution metadata and speaker-role metadata
  - `article`, `essay`, `speech`, `notes`, and `posts` extract authored viewpoints plus facts, and timeline events only when the source contains explicit time anchors
- [x] Step 5: Materialize the per-source bundle files for every run, regardless of review status.
- [x] Step 6: Apply exact auto-approval policy:
  - `autobiography`, `article`, `essay`, `speech`, `notes`, `posts` -> immediate approval and projection
  - `biography`, `interview` -> pending review only, no projection
- [x] Step 7: Project approved knowledge into canonical artifacts with these exact rules:
  - `viewpoint` entries are written to `persona_knowledge/entries.json`
  - fact records are written as `persona_fact`
  - timeline-event records are written as `timeline_event`
  - linked conflict groups are merged into `persona_knowledge/conflict_groups.json`
  - compatibility chunks are rebuilt from approved authored-book viewpoints, approved milestone-3 viewpoints/facts/timeline summaries, and legacy manual raw chunks
  - `embeddings.json` and `runtime_index.json` are rebuilt from approved knowledge only
- [x] Step 8: Keep pending and rejected source bundles outside canonical projection while still preserving their extracted artifact files and reports.
- [x] Step 9: Add tests for:
  - source-kind mapping and review-status defaults
  - directory/manifest bundle support for `notes` and `posts`
  - biography and interview pending-state materialization
  - auto-approved authored short-form projection
  - approve/reject transitions
  - conflict-group linking against already-approved entries
  - legacy `add_manual_sources()` non-regression

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_job.py tests/asky/plugins/manual_persona_creator/test_source_review.py tests/asky/plugins/manual_persona_creator/test_source_service.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/plugins/manual_persona_creator/test_book_service.py tests/asky/plugins/manual_persona_creator/test_runtime_index.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Biography and interview ingests stop at pending review with durable source bundles and no canonical projection.
- Auto-approved authored short-form and autobiography sources project approved knowledge and rebuild runtime artifacts.
- A git commit is created with message: `persona: add source-aware ingestion and review backend`

**Stop and Escalate If:**

- The existing source and trust taxonomy cannot express the approved mappings without changing the agreed public source kinds.
- Bundle extraction requires storing raw full-source bodies inside exported persona packages.

### [x] Checkpoint 3: Source CLI Family And Approved-Knowledge Query Surfaces

**Goal:**

- Expose the new milestone-3 backend through explicit `source-*` commands and approved-knowledge query commands, while preserving the existing authored-book and add-sources surfaces.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1600,1710p' src/asky/cli/main.py`
- `sed -n '1,860p' src/asky/cli/persona_commands.py`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,240p' tests/asky/cli/test_persona_ingestion_commands.py`
- `sed -n '1,320p' tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `sed -n '1,260p' tests/integration/cli_recorded/cli_surface.py`

**Scope & Blast Radius:**

- May create:
- `tests/asky/cli/test_persona_source_commands.py`
- May modify:
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- `tests/asky/cli/test_persona_ingestion_commands.py`
- `tests/asky/cli/test_persona_source_commands.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `tests/integration/cli_recorded/cli_surface.py`
- backend modules only as needed to expose clean service entrypoints
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- root parser flow outside the persona subcommand block
- Constraints:
- keep CLI a thin wrapper over service modules
- preserve existing persona book commands and `add-sources`
- keep recorded CLI coverage deterministic and provider-free

**Steps:**

- [x] Step 1: Add exact new persona subcommands:
  - `ingest-source`
  - `sources`
  - `source-report`
  - `approve-source`
  - `reject-source`
  - `facts`
  - `timeline`
  - `conflicts`
- [x] Step 2: Add exact `ingest-source` positional arguments:
  - `name`
  - `kind`
  - `path`
  with `kind` restricted to the milestone-3 kinds from Checkpoint 1.
- [x] Step 3: Implement a thin Rich-based preflight loop for `ingest-source`:
  - show detected kind, trust mapping, and resulting review status
  - show bundle stats for single-file vs directory/manifest input
  - for pending kinds, state explicitly that runtime and approved query commands will not use the source until approval
  - require explicit confirmation before starting the job
- [x] Step 4: Implement `sources` to list source bundles with:
  - `source_id`
  - label
  - kind
  - `source_class`
  - `trust_class`
  - review status
  - extracted viewpoints/facts/timeline/conflict counts
  - updated timestamp
- [x] Step 5: Implement `source-report` to render a stable summary with:
  - source metadata
  - input stats and bundle member count
  - warnings
  - stage timings
  - extracted counts
  - conflict-group summary
  - review state and approval/rejection timestamp
- [x] Step 6: Implement `approve-source` and `reject-source` with confirmation prompts. These commands must be idempotent and must print whether canonical projection changed.
- [x] Step 7: Add approved-query commands:
  - `facts` queries approved fact entries only
  - `timeline` queries approved timeline-event entries only
  - `conflicts` queries approved conflict groups only
  Each command supports `--source`, `--topic`, and `--limit`; `timeline` also supports `--year`.
- [x] Step 8: Extend `viewpoints` to accept `--source SOURCE_ID` and include approved milestone-3 viewpoint entries without breaking `--book`.
- [x] Step 9: Add deterministic unit and recorded CLI tests for:
  - parser surface coverage
  - pending review messaging
  - approve/reject flow
  - approved `facts`, `timeline`, `conflicts` output
  - `viewpoints --source`
  - non-regression of authored-book commands and `add-sources`

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_persona_source_commands.py tests/asky/cli/test_persona_ingestion_commands.py -q -n0`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli`

**Done When:**

- Verification commands pass cleanly.
- The new `source-*` family is discoverable, deterministic, and separate from authored-book commands.
- Approved query commands only surface approved canonical knowledge.
- A git commit is created with message: `persona: add source review and query cli`

**Stop and Escalate If:**

- The persona subcommand parser cannot add the new command family without breaking existing book-command dispatch.
- Deterministic CLI coverage would require live provider calls or live outbound network access.

### [x] Checkpoint 4: Approved-Only Runtime Boundary And Regression Coverage

**Goal:**

- Enforce the milestone-3 runtime boundary so approved source knowledge can participate after projection, while pending/rejected source bundles remain completely outside persona runtime behavior.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/runtime_index.py`
- `sed -n '1,360p' src/asky/plugins/persona_manager/runtime_planner.py`
- `sed -n '1,220p' src/asky/plugins/persona_manager/runtime_types.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_runtime_planner.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_persona_manager.py`
- `sed -n '1,320p' tests/asky/evals/persona_pipeline/test_persona_eval_gate.py`

**Scope & Blast Radius:**

- May create:
- additional persona-manager runtime tests under `tests/asky/plugins/persona_manager/`
- May modify:
- `src/asky/plugins/manual_persona_creator/runtime_index.py`
- `src/asky/plugins/persona_manager/runtime_planner.py`
- `src/asky/plugins/persona_manager/runtime_types.py`
- `tests/asky/plugins/persona_manager/test_runtime_planner.py`
- `tests/asky/plugins/persona_manager/test_persona_manager.py`
- `tests/asky/evals/persona_pipeline/test_persona_eval_gate.py`
- Must not touch:
- `src/asky/cli/main.py`
- `src/asky/core/**`
- `src/asky/api/**`
- Constraints:
- keep milestone-3 runtime use approved-only
- keep runtime packet injection viewpoint-centric in this milestone
- do not let facts or timeline events become unlabeled persona packets by accident

**Steps:**

- [x] Step 1: Ensure approved milestone-3 viewpoint entries are included in the runtime index after projection, with metadata that preserves `source_kind` and attribution context for formatting/debugging.
- [x] Step 2: Keep pending and rejected source bundles completely absent from runtime index rebuilds.
- [x] Step 3: Keep runtime planner primary packets limited to approved `viewpoint` entries plus existing fallback raw chunks. Do not inject `persona_fact` or `timeline_event` as primary persona packets in this milestone.
- [x] Step 4: Extend runtime-planner and eval tests so they prove:
  - approved autobiography/article/essay/speech/notes/posts viewpoints become retrievable after projection
  - pending biography/interview viewpoints are not retrievable before approval
  - approving a pending source makes its approved viewpoint entries appear in runtime retrieval
  - rejecting a source keeps runtime retrieval unchanged
- [x] Step 5: Preserve existing authored-book-first preference when scores are comparable. Approved milestone-3 viewpoints may participate, but they must not demote authored-book evidence below the current authored-book-first priority.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/persona_manager/test_runtime_planner.py tests/asky/plugins/persona_manager/test_persona_manager.py tests/asky/evals/persona_pipeline/test_persona_eval_gate.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_grounding.py tests/asky/plugins/persona_manager/test_runtime_current_context.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Approved milestone-3 viewpoints can influence runtime only after canonical projection.
- Pending and rejected source bundles do not affect persona answers or approved CLI queries.
- A git commit is created with message: `persona: enforce approved-only runtime boundary`

**Stop and Escalate If:**

- Approved-only runtime use would require breaking the authored-book-first priority contract from milestone 2.
- Keeping facts and timeline queryable but out of primary persona packets proves impossible without widening the user-visible persona reply contract.

### [x] Checkpoint 5: Documentation Parity And Final Regression

**Goal:**

- Update architecture, operator docs, and local agent guidance for milestone-3 behavior, then run final regression and compare runtime against the captured baseline.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,320p' ARCHITECTURE.md`
- `sed -n '1,320p' devlog/DEVLOG.md`
- `sed -n '1,220p' docs/plugins.md`
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,260p' tests/AGENTS.md`
- `grep -n "persona" README.md`

**Scope & Blast Radius:**

- May modify:
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `docs/plugins.md`
- `src/asky/plugins/AGENTS.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/plugins/persona_manager/AGENTS.md`
- `src/asky/cli/AGENTS.md`
- `README.md` only if an already relevant persona section exists
- Must not touch:
- root `AGENTS.md`
- docs for GUI review flows, web scraping, browser acquisition, or audio milestones
- `tests/AGENTS.md` unless lane behavior actually changes
- Constraints:
- docs must describe only the shipped milestone-3 behavior
- if `tests/AGENTS.md` does not need an update because lane mechanics are unchanged, leave it untouched and note why in the doc pass

**Steps:**

- [x] Step 1: Update `ARCHITECTURE.md` for:
  - `ingested_sources/**`
  - `source_ingestion_jobs/**`
  - `persona_knowledge/conflict_groups.json`
  - source-aware review and promotion flow
  - approved-only runtime boundary
- [x] Step 2: Update `docs/plugins.md` so the persona section documents:
  - the new `source-*` command family
  - approved vs pending review behavior
  - approved query commands
  - the fact that `add-sources` remains a legacy chunk-ingestion path
- [x] Step 3: Update affected `AGENTS.md` files:
  - `src/asky/plugins/manual_persona_creator/AGENTS.md` for source-bundle storage and module ownership
  - `src/asky/plugins/persona_manager/AGENTS.md` for approved-only runtime boundary
  - `src/asky/cli/AGENTS.md` for the new persona command surface
  - `src/asky/plugins/AGENTS.md` only if the user entrypoint section needs the new persona command family
- [x] Step 4: Update `devlog/DEVLOG.md` with the milestone summary, review boundary, new artifacts, test results, and runtime comparison.
- [x] Step 5: Search README for an already relevant persona section. If none exists, leave README untouched and state that decision in the doc pass.
- [x] Step 6: Run final regression:
  - `TIMEFORMAT='real %3R user %3U sys %3S'; time uv run pytest -q`
- [x] Step 7: Compare final timing against baseline `real 15.760`. If the increase exceeds `max(3.0s, 20%)`, investigate with:
  - `uv run pytest -q --durations=20`
  and optimize or mark newly expensive tests `slow` before closing.

**Dependencies:**

- Depends on Checkpoints 1-4.

**Verification:**

- Run scoped doc checks: `grep -RIn "ingest-source\\|approve-source\\|reject-source\\|facts\\|timeline\\|conflicts\\|conflict_groups.json" ARCHITECTURE.md docs/plugins.md src/asky/plugins/AGENTS.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md src/asky/cli/AGENTS.md`
- Run final regression: `TIMEFORMAT='real %3R user %3U sys %3S'; time uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs describe only shipped milestone-3 behavior.
- Full-suite runtime is compared against the captured baseline and any material increase is explained.
- A git commit is created with message: `docs: document persona milestone3 source ingestion`

**Stop and Escalate If:**

- Documentation parity would require describing unimplemented GUI, scraping, or audio behavior.
- Final suite runtime regresses materially and the cause cannot be tied to the added coverage.

## Behavioral Acceptance Tests

- Given `asky persona ingest-source arendt article ./notes/labor-essay.md`, the run auto-approves, writes a durable `ingested_sources/<source_id>/` bundle, projects approved viewpoints/facts into canonical knowledge, and makes approved viewpoints available to persona runtime without touching authored-book commands.
- Given `asky persona ingest-source arendt biography ./bios/arendt.epub`, the run writes a durable source bundle and report, marks the source `pending`, lists it in `asky persona sources arendt --status pending`, and does not change `persona_knowledge/**`, `chunks.json`, `embeddings.json`, or runtime retrieval until approval.
- Given a pending biography source, `asky persona source-report arendt <source_id>` shows extracted viewpoints, facts, timeline events, conflict candidates, warnings, and review status without implicitly approving anything.
- Given a pending biography source, `asky persona approve-source arendt <source_id>` projects its approved entries into canonical knowledge, rebuilds derived artifacts, and makes approved viewpoints and queryable facts visible through `viewpoints`, `facts`, `timeline`, and `conflicts`.
- Given a pending interview source, `asky persona reject-source arendt <source_id>` leaves the source bundle inspectable but keeps it out of approved queries and persona runtime.
- Given an autobiography source and a biography source that disagree on the same topic, the system keeps both claims as separate entries and exposes an explicit linked conflict group through `asky persona conflicts`.
- Given `asky persona ingest-source arendt posts ./posts/` or a newline-delimited manifest, the run treats the directory or manifest as one short-form source bundle with deterministic `source_id`, per-member stats, and one review decision.
- Existing `asky persona ingest-book`, `books`, `book-report`, `viewpoints --book`, and `add-sources` behavior still works after milestone 3 without renamed commands or changed semantics.
- Exporting and importing a persona after milestone-3 work preserves `ingested_sources/**`, approved conflict groups, and review status, while still excluding job scratch and rebuilding derived runtime artifacts on import.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Source bundles and conflict groups have durable portable storage | `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_storage.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py -q -n0` |
| Source-aware extraction varies by kind and preserves pending vs approved state | `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_job.py tests/asky/plugins/manual_persona_creator/test_source_review.py -q -n0` |
| `add-sources` remains legacy chunk-only and non-regressed | `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_service.py -q -n0` |
| New `source-*` CLI family is discoverable and deterministic | `uv run pytest tests/asky/cli/test_persona_source_commands.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli` |
| Approved query commands surface only approved canonical knowledge | `uv run pytest tests/asky/cli/test_persona_source_commands.py -q -n0` |
| Pending and rejected sources do not influence runtime | `uv run pytest tests/asky/plugins/persona_manager/test_runtime_planner.py tests/asky/evals/persona_pipeline/test_persona_eval_gate.py -q -n0` |
| Approved milestone-3 viewpoints can participate in runtime after projection | `uv run pytest tests/asky/plugins/persona_manager/test_runtime_planner.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0` |
| Linked conflict groups are preserved instead of flattened | `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_review.py tests/asky/cli/test_persona_source_commands.py -q -n0` |
| Docs and AGENTS files describe only shipped milestone-3 behavior | `grep -RIn "ingest-source\\|approve-source\\|reject-source\\|facts\\|timeline\\|conflicts\\|conflict_groups.json" ARCHITECTURE.md docs/plugins.md src/asky/plugins/AGENTS.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md src/asky/cli/AGENTS.md` |
| Final regression remains green and runtime increase is understood | `TIMEFORMAT='real %3R user %3U sys %3S'; time uv run pytest -q` |

## Assumptions And Defaults

- Milestone 3 is planned as one checkpointed handoff, not split into a smaller 3A/3B milestone.
- The new public CLI family uses `source-*` naming and keeps current authored-book commands unchanged.
- Approved-only runtime use means:
  - approved milestone-3 `viewpoint` entries can influence runtime after projection
  - `persona_fact` and `timeline_event` entries are approved-query data in this milestone, not primary persona voice packets
  - pending and rejected bundles never affect runtime
- Auto-approval is limited to `autobiography`, `article`, `essay`, `speech`, `notes`, and `posts`.
- `biography` and `interview` are always review-gated in milestone 3.
- Directory and manifest input are supported only for `notes` and `posts`. The manifest format is UTF-8 text with one local path per line; blank lines and `#` comments are ignored.
- Existing schema-v3 personas remain the additive foundation. If the implementation can stay additive, do not bump schema version.
- `tests/AGENTS.md` should remain unchanged unless the test-lane mechanics themselves change, which this milestone does not require.
- README should remain unchanged unless implementation finds an already relevant persona section that truly needs milestone-3 updates.

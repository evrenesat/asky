# RALF Handoff Plan: Persona Milestone 1, Authored-Book Ingestion

## Summary

Implement the first persona roadmap milestone as a backend-first, reusable authored-book ingestion system for existing personas. The milestone must add a new `persona ingest-book` flow that:

- targets an existing persona only,
- ingests one local authored book per run,
- performs deterministic metadata lookup with user confirmation and manual fallback,
- persists a resumable ingestion job that is not coupled to CLI rendering,
- extracts structured viewpoint entries with evidence and confirmed book metadata,
- preserves multiple books per persona without flattening time differences,
- blocks duplicate completed books unless the user explicitly runs `reingest-book`,
- provides deterministic inspection commands before milestone 2 runtime work exists,
- keeps current persona runtime compatibility by regenerating `chunks.json` and `embeddings.json`,
- updates export/import so authored-book knowledge is portable with the persona package.

This handoff must not implement any web UI. All new services and data contracts must be reusable later by the GUI server without moving logic out of CLI code after the fact.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `6387e1a9fb8edc0951fcd32a3418dbde71f587a3`
- Last Reviewed HEAD: `none`
- Review Log:
  - None yet.

## Done Means

- `asky persona ingest-book PERSONA BOOK_PATH` exists and only accepts an existing persona plus one local book file.
- `asky persona reingest-book PERSONA BOOK_KEY BOOK_PATH` exists and is the only allowed replacement path for an already ingested completed book.
- `asky persona books PERSONA`, `asky persona book-report PERSONA BOOK_KEY`, and `asky persona viewpoints PERSONA` exist and work deterministically without the later persona runtime milestone.
- The preflight step is mandatory and editable. It shows confirmed or manually entered book metadata and system-proposed extraction targets before any expensive extraction starts.
- Metadata lookup uses deterministic provider calls plus manual fallback. Ambiguity is never auto-accepted.
- The backend persists authored-book artifacts under the persona directory and persists resumable job artifacts separately from final exportable artifacts.
- Structured authored-book output contains viewpoint entries with book identity metadata, publication-time metadata, confidence, and evidence excerpts with section references.
- Multiple authored books may exist under one persona. Their viewpoints remain attributable to the specific book and publication date.
- Duplicate completed books are blocked by `ingest-book`. Replacement requires `reingest-book`.
- Exported personas include authored-book knowledge artifacts. Importing those packages preserves the authored-book data and rebuilds compatibility embeddings.
- Existing persona load behavior still works after book ingestion because compatibility `chunks.json` and `embeddings.json` are regenerated.
- Existing schema-v1 personas and schema-v1 persona archives remain readable/importable.
- Documentation and affected subdirectory `AGENTS.md` files are updated only for behavior actually implemented in this handoff.
- `uv run pytest -q` passes at the end, and the runtime increase is investigated if it is disproportionate relative to the added coverage. Current baseline for comparison: `1459 passed in 13.76s`, `real 14.29s`.

## Critical Invariants

- All authored-book ingestion logic must live in reusable service modules under `src/asky/plugins/manual_persona_creator/`. `src/asky/cli/persona_commands.py` may only render prompts, collect user input, and call service APIs.
- Final authored-book data is canonical inside the persona package directory, not in global SQLite tables.
- Resumable job state must be stored separately from final authored-book artifacts so export can include the latter without leaking in-progress scratch artifacts.
- Each completed authored book must have exactly one canonical book identity per persona. No silent merges, no implicit overwrite.
- Viewpoint entries must always include confirmed book identity metadata and evidence excerpts with section references.
- `chunks.json` and `embeddings.json` must remain present and must be rebuilt from the compatibility projection after authored-book changes so current persona runtime behavior does not regress.
- Schema migration must be backward compatible. Existing v1 personas and archives must continue to load.
- The milestone must not introduce any new third-party package dependency. Reuse existing `requests`, existing PyMuPDF support, current embedding helpers, and existing summarization utilities.
- Metadata lookup must never silently accept a low-confidence candidate. User confirmation or manual entry is required before job execution begins.
- No code in the new backend modules may import CLI-only concerns such as `argparse`, `rich`, `Console`, or prompt widgets.

## Forbidden Implementations

- Do not overload `persona add-sources` for authored-book ingestion.
- Do not place extraction logic, metadata lookup logic, or storage mutations directly inside `src/asky/cli/persona_commands.py` or `src/asky/cli/main.py`.
- Do not auto-create personas from `ingest-book`.
- Do not silently replace or merge a duplicate completed book when `ingest-book` is called.
- Do not store only a free-form summary or only raw embeddings. Structured viewpoint entries are required.
- Do not make global SQLite the canonical store for authored-book knowledge.
- Do not export in-progress job artifacts, raw full-book text, or temporary section-vector artifacts in persona packages.
- Do not break schema-v1 reads by changing strict metadata validation without a compatibility path.
- Do not update the root `AGENTS.md`.
- Do not update docs to describe GUI behavior, milestone 2 runtime behavior, or graph-storage behavior that this handoff does not implement.

## Checkpoints

- [x] Checkpoint 1: Canonical Storage And Portability Foundation

**Goal:**

Establish the authored-book storage contract, schema compatibility rules, and portable archive format before any CLI or extraction work begins.

**Context Bootstrapping:**

Run these commands before editing:
- `pwd`
- `git branch --show-current`
- `git rev-parse HEAD`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/storage.py`
- `sed -n '1,220p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/exporter.py`
- `sed -n '1,220p' /Users/evren/code/asky/src/asky/plugins/persona_manager/importer.py`

If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create: `src/asky/plugins/manual_persona_creator/book_types.py`
- May modify: `src/asky/plugins/manual_persona_creator/storage.py`, `src/asky/plugins/manual_persona_creator/exporter.py`, `src/asky/plugins/persona_manager/importer.py`, `tests/asky/plugins/manual_persona_creator/test_manual_persona_creator.py`, `tests/asky/plugins/persona_manager/test_e2e_persona_workflow.py`, `tests/asky/plugins/persona_manager/test_persona_errors.py`
- Must not touch: `src/asky/cli/**`, `src/asky/core/**`, `src/asky/api/**`, `src/asky/plugins/persona_manager/plugin.py`
- Constraints: keep current persona package members valid, keep import backward compatible, and do not add new runtime behavior yet

**Steps:**

- [x] Add `book_types.py` with dataclasses or typed structures for confirmed book metadata, extraction targets, ingestion job manifest, authored-book report, and viewpoint entry.
- [x] Extend persona storage helpers with exact canonical directories:
  - final artifacts under `authored_books/<book_key>/`
  - resumable job artifacts under `ingestion_jobs/<job_id>/`
- [x] Define exact durable final files:
  - `authored_books/index.json`
  - `authored_books/<book_key>/book.toml`
  - `authored_books/<book_key>/viewpoints.json`
  - `authored_books/<book_key>/report.json`
- [x] Define exact job files:
  - `ingestion_jobs/<job_id>/job.toml`
  - optional stage artifacts such as section summaries or topic candidates, excluded from export
- [x] Implement book identity rules:
  - canonical identity prefers confirmed ISBN
  - fallback identity uses normalized confirmed title plus publication year
  - `book_key` is path-safe and deterministic from the canonical identity
- [x] Replace strict single-version metadata validation with compatibility constants so schema v1 and schema v2 personas both read successfully
- [x] Keep export portable by including authored-book final artifacts and excluding `embeddings.json`, `ingestion_jobs/**`, and raw full-book text
- [x] Keep importer backward compatible by accepting v1 and v2 archives, writing authored-book artifacts when present, and rebuilding `embeddings.json` from imported `chunks.json`
- [x] Add or extend tests for:
  - v1 metadata still loads
  - v2 metadata with authored books loads
  - export contains authored-book artifacts but excludes job artifacts
  - import round-trips authored-book artifacts
  - absolute-path leakage is still prevented

**Dependencies:**

Depends on no prior checkpoint.

**Verification:**

Run scoped tests:
- `uv run pytest tests/asky/plugins/manual_persona_creator/test_manual_persona_creator.py tests/asky/plugins/persona_manager/test_e2e_persona_workflow.py tests/asky/plugins/persona_manager/test_persona_errors.py -q -n0`

Run non-regression tests:
- `uv run pytest tests/asky/plugins/persona_manager/test_persona_manager.py tests/asky/plugins/persona_manager/test_persona_resolver.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A v2 persona archive can carry authored-book artifacts without exporting in-progress job state.
- A schema-v1 persona still reads and imports cleanly.
- A git commit is created with message: `persona: add authored-book storage and portability foundation`

**Stop and Escalate If:**

- Backward compatibility requires breaking v1 persona reads.
- Export/import changes would require touching core plugin runtime or session hook code.

- [x] Checkpoint 2: Metadata Lookup And Reusable Preflight Service

**Goal:**

Add a UI-agnostic preflight service that reads one local book, looks up metadata deterministically, computes proposed extraction targets, and returns editable DTOs without performing CLI I/O.

**Context Bootstrapping:**

Run these commands before editing:
- `sed -n '260,520p' /Users/evren/code/asky/src/asky/research/adapters.py`
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/summarization.py`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_types.py`
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/storage.py`

**Scope & Blast Radius:**

- May create: `src/asky/plugins/manual_persona_creator/book_lookup.py`
- May modify: `src/asky/plugins/manual_persona_creator/book_types.py`, `src/asky/plugins/manual_persona_creator/storage.py`
- May create tests: `tests/asky/plugins/manual_persona_creator/test_book_lookup.py`
- Must not touch: `src/asky/cli/**`, `src/asky/core/**`, `docs/**`
- Constraints: no direct `input()`, no Rich prompts, no CLI rendering imports

**Steps:**

- [x] Implement deterministic ISBN extraction from filename and book text front matter.
- [x] Use OpenLibrary HTTP endpoints through existing `requests` as the only metadata provider in this milestone:
  - ISBN lookup first when an ISBN candidate exists
  - title-based search fallback using normalized filename/title and persona name
- [x] Return the top candidate list in a typed preflight result; do not auto-select a low-confidence result
- [x] Implement manual fallback payload when lookup finds no confident match
- [x] Read the local book through the existing local-source adapter path so PDF, EPUB, and current supported text-like single-file inputs reuse the existing reader stack
- [x] Compute deterministic book stats for preflight:
  - character count
  - approximate word count
  - section count using existing section utilities where possible
- [x] Implement system target proposal formulas:
  - `topic_target = max(8, min(24, ceil(word_count / 7500)))`
  - `viewpoint_target = topic_target * 3`
- [x] Implement duplicate and unfinished-job checks in the preflight result:
  - completed duplicate book identity blocks `ingest-book`
  - same persona plus same source fingerprint plus non-terminal job yields resumable job info
- [x] Add unit tests for ISBN extraction, candidate ranking, manual fallback, target formulas, duplicate detection, and unfinished-job detection

**Dependencies:**

Depends on Checkpoint 1.

**Verification:**

Run scoped tests:
- `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_lookup.py -q -n0`

Run non-regression tests:
- `uv run pytest tests/asky/plugins/manual_persona_creator/test_manual_persona_creator.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The preflight service can produce a full editable plan without importing any CLI-only modules.
- Duplicate completed books and resumable unfinished jobs are distinguishable before extraction starts.
- A git commit is created with message: `persona: add authored-book metadata lookup and preflight service`

**Stop and Escalate If:**

- OpenLibrary lookup proves unusable without adding a new package dependency.
- Local book reading for supported single-file inputs requires changes outside the existing adapter boundary.

- [x] Checkpoint 3: Resumable Job Engine And Multi-Pass Extraction Backend

**Goal:**

Implement the reusable authored-book ingestion backend that runs the multi-pass extraction pipeline, writes resumable job state, materializes final authored-book artifacts, and regenerates compatibility chunks.

**Context Bootstrapping:**

Run these commands before editing:
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_types.py`
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_lookup.py`
- `sed -n '1,260p' /Users/evren/code/asky/src/asky/summarization.py`
- `rg -n "build_section_index|slice_section_content|chunk_text|cosine_similarity" /Users/evren/code/asky/src/asky`

**Scope & Blast Radius:**

- May create: `src/asky/plugins/manual_persona_creator/book_prompts.py`, `src/asky/plugins/manual_persona_creator/book_ingestion.py`
- May modify: `src/asky/plugins/manual_persona_creator/book_types.py`, `src/asky/plugins/manual_persona_creator/storage.py`, `src/asky/plugins/manual_persona_creator/exporter.py`
- May create tests: `tests/asky/plugins/manual_persona_creator/test_book_ingestion.py`
- Must not touch: `src/asky/cli/**`, `src/asky/core/engine.py`, `src/asky/plugins/persona_manager/plugin.py`
- Constraints: use reusable services only, use existing model utilities, and keep current persona runtime compatibility projection explicit

**Steps:**

- [x] Implement job lifecycle with persisted states `planned`, `running`, `failed`, `completed`, and `cancelled`
- [x] Implement exact pipeline stages in persisted order:
  - `read_source`
  - `summarize_sections`
  - `discover_topics`
  - `extract_viewpoints`
  - `materialize_book`
  - `project_compat_chunks`
- [x] Use existing section utilities to slice the book into sections where possible, and fall back to semantic chunking when section detection is weak
- [x] Use `SUMMARIZATION_MODEL` for section-summary map/reduce work and persist section summaries in the job artifact area
- [x] Build a per-job local vector retrieval index from section summaries or section content using the existing embedding client and file-backed vectors; do not write these vectors into global SQLite or Chroma
- [x] Use `DEFAULT_MODEL` for:
  - topic discovery from the persisted summaries
  - per-topic viewpoint extraction against the top-ranked sections
- [x] Validate every extraction call against a strict JSON schema before accepting the output
- [x] Materialize exact viewpoint fields:
  - `entry_id`
  - `topic`
  - `claim`
  - `stance_label` from `{supports, opposes, mixed, descriptive, unclear}`
  - `confidence`
  - `book_key`
  - `book_title`
  - `publication_year`
  - `isbn`
  - `evidence` with 1-3 items, each carrying `excerpt` and `section_ref`
- [x] Deduplicate normalized viewpoint entries by topic plus normalized claim and keep at most the confirmed `viewpoint_target`
- [x] Write final durable artifacts under `authored_books/<book_key>/`
- [x] Regenerate persona-level compatibility `chunks.json` from:
  - existing manual source chunks
  - synthesized authored-book chunks built from viewpoint entries plus short evidence previews
- [x] Rebuild `embeddings.json` from the compatibility chunks so current persona load behavior keeps working
- [x] Implement replacement backend semantics for `reingest-book`:
  - write the replacement into a fresh job area
  - only replace the target book directory after successful completion
  - if edited metadata resolves to a different canonical identity, abort instead of renaming the old book
- [x] Clean completed job artifacts so they retain job manifest history but do not retain raw full-book text or section-vector scratch files
- [x] Add backend tests for resume behavior, failed-stage restart, duplicate blocking, replacement flow, viewpoint schema validation, compatibility chunk projection, and embedding rebuild calls

**Dependencies:**

Depends on Checkpoint 2.

**Verification:**

Run scoped tests:
- `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0`

Run non-regression tests:
- `uv run pytest tests/asky/plugins/manual_persona_creator/test_manual_persona_creator.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A completed authored-book ingest leaves durable authored-book artifacts, updated compatibility chunks, and rebuilt embeddings.
- Rerunning against an unfinished job resumes instead of starting a parallel duplicate.
- A git commit is created with message: `persona: add authored-book extraction job backend`

**Stop and Escalate If:**

- Model outputs cannot be constrained to valid structured JSON without silent repair logic.
- Compatibility chunk projection cannot preserve current persona runtime behavior without touching core runtime hooks.

- [x] Checkpoint 4: CLI Surface, Confirmation Loop, And Inspection Commands

**Goal:**

Expose the authored-book backend through a thin CLI layer with mandatory confirmation, editable preflight values, explicit reingestion, and deterministic inspection commands.

**Context Bootstrapping:**

Run these commands before editing:
- `sed -n '1681,1810p' /Users/evren/code/asky/src/asky/cli/main.py`
- `sed -n '1,320p' /Users/evren/code/asky/src/asky/cli/persona_commands.py`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/cli/AGENTS.md`
- `sed -n '1,320p' /Users/evren/code/asky/tests/asky/plugins/persona_manager/test_persona_commands.py`
- `sed -n '1,220p' /Users/evren/code/asky/tests/integration/cli_recorded/test_cli_persona_recorded.py`

**Scope & Blast Radius:**

- May modify: `src/asky/cli/main.py`, `src/asky/cli/persona_commands.py`, `tests/asky/plugins/persona_manager/test_persona_commands.py`, `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- May modify backend modules only as needed to expose clean service entrypoints
- Must not touch: `src/asky/core/**`, `src/asky/api/**`, root parser flow outside persona subcommand block
- Constraints: CLI remains a wrapper only; recorded CLI tests must not hit real HTTP metadata lookup or real extraction LLM calls

**Steps:**

- [x] Add exact subcommands:
  - `asky persona ingest-book PERSONA BOOK_PATH`
  - `asky persona reingest-book PERSONA BOOK_KEY BOOK_PATH`
  - `asky persona books PERSONA`
  - `asky persona book-report PERSONA BOOK_KEY`
  - `asky persona viewpoints PERSONA [--book BOOK_KEY] [--topic TOPIC] [--limit N]`
- [x] Keep `persona create` as the only persona-creation surface. If the persona does not exist, `ingest-book` and `reingest-book` must fail with a clear message.
- [x] Implement the mandatory preflight interaction in `persona_commands.py` only:
  - show lookup candidates or manual fallback
  - allow editing `title`, `publication_year`, and `isbn`
  - allow editing `topic_target` and `viewpoint_target`
  - require explicit confirm or cancel
- [x] Do not add a `--yes` or other non-interactive bypass in this milestone
- [x] `ingest-book` behavior:
  - if a non-terminal job exists for the same persona and source fingerprint, resume it after confirmation
  - if a completed book with the same canonical identity exists, stop and instruct the user to run `reingest-book`
- [x] `reingest-book` behavior:
  - require an existing `BOOK_KEY`
  - preload the existing book metadata into the editable preflight fields
  - abort if the user edits the metadata into a different canonical identity
- [x] `books` output must list at least:
  - `book_key`
  - `title`
  - `publication_year`
  - `isbn`
  - `viewpoint_count`
  - `last_ingested_at`
- [x] `book-report` must read the persisted report artifact and render a stable summary with metadata, targets, actual counts, warnings, and stage timings
- [x] `viewpoints` must default to `--limit 20`, allow optional `--book` and `--topic` filters, and sort by topic then descending confidence
- [x] Extend unit tests for handler behavior and recorded CLI integration tests with backend stubs so the CLI surface is verified without real network or long LLM extraction

**Dependencies:**

Depends on Checkpoint 3.

**Verification:**

Run scoped tests:
- `uv run pytest tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0`
- `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`

Run non-regression tests:
- `uv run pytest tests/asky/cli/test_local_ingestion_flow.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The CLI persona path exposes the new commands and nothing in the backend depends on CLI rendering types.
- Duplicate and replacement behavior is user-visible and deterministic.
- A git commit is created with message: `persona: add authored-book CLI and inspection commands`

**Stop and Escalate If:**

- The early persona parser path in `main.py` cannot support the confirmation loop cleanly without leaking business logic into the parser layer.
- Recorded CLI coverage would require live HTTP or live LLM calls to validate the new commands.

- [ ] Checkpoint 5: Documentation Parity, AGENTS Updates, And Final Regression

**Goal:**

Bring architecture, operator docs, and subdirectory agent guidance up to parity with the implemented milestone, then run final regression and runtime comparison.

**Context Bootstrapping:**

Run these commands before editing:
- `sed -n '1,260p' /Users/evren/code/asky/ARCHITECTURE.md`
- `sed -n '1,260p' /Users/evren/code/asky/devlog/DEVLOG.md`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/cli/AGENTS.md`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,240p' /Users/evren/code/asky/src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,240p' /Users/evren/code/asky/docs/plugins.md`
- `rg -n "persona" /Users/evren/code/asky/README.md /Users/evren/code/asky/src/**/README.md`

**Scope & Blast Radius:**

- May modify: `ARCHITECTURE.md`, `devlog/DEVLOG.md`, `src/asky/cli/AGENTS.md`, `src/asky/plugins/manual_persona_creator/AGENTS.md`, `src/asky/plugins/persona_manager/AGENTS.md`, `docs/plugins.md`
- May modify `README.md` or an affected subdirectory `README.md` only if an already relevant persona section exists
- Must not touch: root `AGENTS.md`, docs for unimplemented GUI/runtime future state, config docs unless code actually added config
- Constraints: docs must describe only shipped checkpointed behavior

**Steps:**

- [ ] Update `ARCHITECTURE.md` for:
  - authored-book storage layout
  - ingestion job flow
  - compatibility chunk projection
  - new persona CLI surfaces
- [ ] Update `devlog/DEVLOG.md` with date, summary, changed behavior, portability note, and any runtime/test gotchas
- [ ] Update affected subdirectory `AGENTS.md` files:
  - `src/asky/cli/AGENTS.md` for new persona command surface
  - `src/asky/plugins/manual_persona_creator/AGENTS.md` for new storage and module responsibilities
  - `src/asky/plugins/persona_manager/AGENTS.md` for import/export contract changes
- [ ] Rewrite the stale persona section in `docs/plugins.md` so it reflects CLI-first persona commands and authored-book ingestion instead of tool-driven behavior
- [ ] Search `README.md` and affected subdirectory `README.md` files for an already relevant persona section. Update only if such a section exists. If not, leave README untouched and note that no relevant existing section existed.
- [ ] Run final regression and compare against the current baseline runtime

**Dependencies:**

Depends on Checkpoint 4.

**Verification:**

Run scoped checks:
- `rg -n "ingest-book|reingest-book|books|book-report|viewpoints" /Users/evren/code/asky/src/asky/cli/main.py /Users/evren/code/asky/docs/plugins.md /Users/evren/code/asky/ARCHITECTURE.md`
- `rg -n "argparse|rich|Console|Prompt" /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_lookup.py /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py`

Run final regression:
- `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs describe only the implemented milestone behavior.
- Full test suite is green and runtime increase is understood if it exceeds the current baseline materially.
- A git commit is created with message: `docs: document authored-book persona ingestion milestone`

**Stop and Escalate If:**

- Documentation parity would require describing behavior not actually implemented in earlier checkpoints.
- Full-suite runtime regresses materially and the cause is not explained by the added tests.

## Behavioral Acceptance Tests

- A user who already created persona `arendt` can run `asky persona ingest-book arendt /path/to/book.epub`, see metadata candidates, edit title/year/ISBN plus extraction targets, confirm, and receive a completed authored-book record plus a stored report.
- If metadata lookup finds no confident match, the CLI still allows the run to proceed through manual metadata entry in the preflight step.
- If the same confirmed book is already completed for persona `arendt`, `ingest-book` refuses to proceed and explicitly instructs the user to run `reingest-book`.
- If the same source file has an unfinished non-terminal job for persona `arendt`, rerunning `ingest-book` resumes that job instead of creating a parallel duplicate.
- After two different authored books are ingested for the same persona, `asky persona books arendt` lists both with distinct `book_key` values and preserved publication years.
- `asky persona viewpoints arendt --book <book_key>` shows viewpoint entries that include topic, claim, confidence, and evidence excerpts attributable to that book.
- `asky persona reingest-book arendt <book_key> /path/to/revised.epub` replaces only that book’s authored-book artifacts after successful completion and does not silently rename it into a different book identity.
- Exporting and importing the persona after book ingestion preserves the authored-book artifacts and still results in a rebuildable compatibility `embeddings.json`.
- Existing prompt-plus-chunk persona loading still works after authored-book ingestion because compatibility chunks are regenerated.
- The new backend modules remain reusable from a future GUI because they do not import CLI-only rendering or prompt libraries.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Existing persona required for authored-book ingest | `uv run pytest tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0` |
| Structured authored-book artifacts stored under persona dir | `uv run pytest tests/asky/plugins/manual_persona_creator/test_manual_persona_creator.py -q -n0` |
| Export/import carries authored-book artifacts without job scratch | `uv run pytest tests/asky/plugins/persona_manager/test_e2e_persona_workflow.py tests/asky/plugins/persona_manager/test_persona_errors.py -q -n0` |
| Deterministic metadata lookup with manual fallback | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_lookup.py -q -n0` |
| Mandatory editable preflight | `uv run pytest tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0` |
| Resumable job behavior | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0` |
| Duplicate completed books blocked | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0` |
| Explicit replacement via `reingest-book` only | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Viewpoint entries carry evidence and book metadata | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0` |
| Current persona runtime compatibility preserved through `chunks.json` and `embeddings.json` rebuild | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0` |
| Backend remains reusable and not CLI-coupled | `rg -n "argparse|rich|Console|Prompt" /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_lookup.py /Users/evren/code/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py` |
| Docs updated only for shipped behavior | `rg -n "ingest-book|reingest-book|books|book-report|viewpoints" /Users/evren/code/asky/docs/plugins.md /Users/evren/code/asky/ARCHITECTURE.md` |
| Final regression remains green | `uv run pytest -q` |

## Assumptions And Defaults

- Milestone 1 covers authored books only. Biography, autobiography, short-form article ingestion, web scraping, browser-assisted acquisition, GUI work, and runtime persona answering remain out of scope.
- `persona ingest-book` accepts one local single-file source per run and reuses current supported local-source readers. Directory ingestion is not part of this milestone.
- Existing persona only. The user must create the persona separately before calling `ingest-book`.
- One run ingests one book. Multiple books per persona are supported by repeated runs, not multi-book batch ingest.
- `ingest-book` is safe-by-default and blocks completed duplicates. `reingest-book` is the only replacement surface.
- OpenLibrary is the only metadata provider for this milestone. Manual fallback is required when lookup does not confidently resolve.
- No non-interactive confirmation bypass is included in this milestone.
- Proposed extraction targets are editable in preflight. The default formulas are:
  - `topic_target = max(8, min(24, ceil(word_count / 7500)))`
  - `viewpoint_target = topic_target * 3`
- Viewpoints are the only first-class structured entry type in this milestone. Separate fact, timeline, and contradiction entry types remain for later milestones.
- `viewpoints` defaults to `--limit 20`.
- README changes are optional only if an already relevant persona section exists. If not, README stays untouched.

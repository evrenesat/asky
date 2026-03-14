# RALF Handoff Plan: Persona Milestone 0, Baseline Hardening And Data Foundation

## Summary

This handoff targets **Roadmap Milestone 0** from `plans/persona-roadmap.md` dated **2026-03-13**. It intentionally comes **before** any further persona runtime milestone work, because this checkout still has the roadmap's milestone-0 gaps:

- `persona add-sources` is broken and still imports a non-existent module.
- persona data has no canonical knowledge catalog or source/trust taxonomy.
- persona docs are stale and still describe tool-driven behavior that no longer exists.
- there is no persona-specific deterministic evaluation gate.
- the current runtime is still prompt extension plus raw top-k chunk preload, not a grounded persona contract.

This milestone must:

- repair and harden the existing persona surfaces,
- add an additive, portable persona knowledge foundation on top of schema v1/v2/v3 compatibility,
- ship a deterministic persona evaluation gate in the default pytest lane,
- add only **minimal runtime hardening** for grounded answers and visible evidence labels,
- explicitly **not** implement the later structured authored-book runtime planner / deep persona answering milestone.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `abf921cd45fb7dbe74d438898663cb38e434a5a3`
- Last Reviewed HEAD: `current squashed HEAD (this commit)`
- Review Log:
  - `2026-03-14`: reviewed `abf921cd45fb7dbe74d438898663cb38e434a5a3..3a4398b5a78ab8a746ecaf48dd0d83624f793fb0`, outcome `changes-requested`; follow-up plan `persona-milestone0-review-fixes-ralf.md`
  - `2026-03-14`: reviewed `3a4398b5a78ab8a746ecaf48dd0d83624f793fb0..af6f1d710c1642a8dfbe46659b77f330722958cc`, squashed `abf921cd45fb7dbe74d438898663cb38e434a5a3..af6f1d710c1642a8dfbe46659b77f330722958cc` to `current squashed HEAD (this commit)`, outcome `approved+squashed`

## Done Means

- `asky persona add-sources PERSONA SOURCES...` works again through reusable persona-owned services, not through a missing `asky.research.ingestion` import.
- Persona packages gain a canonical additive knowledge layer under:
  - `persona_knowledge/sources.json`
  - `persona_knowledge/entries.json`
- The canonical data model is explicit and typed for:
  - source classes
  - trust classes
  - entry kinds
  - runtime grounding classes
- Existing persona packages remain readable and portable:
  - schema v1 and v2 personas still import and load
  - schema v3 exports include the new knowledge artifacts
  - `chunks.json` and `embeddings.json` remain as compatibility artifacts
- Authored-book viewpoints are projected into the canonical knowledge catalog instead of living only as source-specific files.
- Manual-source ingestion projects raw chunks into the canonical knowledge catalog with deterministic source identity, dedupe, warnings, and embedding rebuilds.
- Loaded persona replies gain a minimal grounded-answer contract by default for non-lean turns:
  - visible grounding classification
  - visible evidence labels
  - explicit insufficient-evidence fallback
- The new grounding contract is intentionally minimal:
  - no structured topic planner
  - no authored-book-only runtime query engine
  - no current-event deep reasoning pipeline beyond bounded or insufficient inference labeling
- A deterministic persona evaluation harness exists under `src/asky/evals/` and is exercised by default pytest coverage.
- The deterministic persona eval gate fails on:
  - missing citation labels
  - unsupported direct-claim attribution
  - missing insufficient-evidence / bounded-inference handling
  - broken persona loading / source-ingestion regressions
- Docs and affected `AGENTS.md` files are updated only for behavior implemented in this handoff.
- Final regression is run inside the Linux VM checkout at `/home/evren/code/asky`.
- Final acceptance target:
  - `uv run pytest -q` passes in the VM
  - runtime remains proportionate to the added tests
  - baseline for comparison is `1490 passed in 14.55s` with shell timing `real 14.746`.

## Critical Invariants

- All durable persona knowledge remains file-backed inside the persona package directory. Global SQLite must not become the canonical persona knowledge store.
- `chunks.json` and `embeddings.json` remain compatibility artifacts until a later milestone explicitly removes them. This handoff must not delete or bypass them.
- Runtime-generated inferences are transient answer annotations only. They must never be persisted into `persona_knowledge/entries.json`.
- The new knowledge catalog must be additive and rebuildable from existing persona artifacts. v1/v2 personas must not require re-ingestion to remain usable.
- Source taxonomy and trust taxonomy must be explicit in code and serialized data. The implementer must not leave them as comments, ad hoc strings, or prompt-only concepts.
- Exact serialized enums for this milestone are:
  - `source_class`: `manual_source`, `authored_book`, `direct_interview`, `biography_or_autobiography`, `third_party_commentary`, `scraped_web`, `audio_video_transcript`
  - `trust_class`: `authored_primary`, `user_supplied_unreviewed`, `mixed_attribution`, `third_party_secondary`, `unreviewed_web`, `transcript_unreviewed`
  - `entry_kind`: `raw_chunk`, `viewpoint`, `persona_fact`, `evidence_excerpt`
  - `grounding_class`: `direct_evidence`, `supported_pattern`, `bounded_inference`, `insufficient_evidence`
- Current source types map exactly as follows in this milestone:
  - authored books -> `source_class=authored_book`, `trust_class=authored_primary`
  - `persona add-sources` inputs -> `source_class=manual_source`, `trust_class=user_supplied_unreviewed`
- Minimal runtime hardening must stay inside plugin-owned logic and hook payloads. Do not move persona business logic into `core/`.
- Lean turns remain exempt from the new citation scaffold to preserve the existing low-context behavior.
- Default persona evals must be deterministic and provider-free. No live provider, replay cassette, or outbound network dependency may be required in the default lane.
- Unrelated worktree changes already exist and must not be reverted:
  - `tests/asky/test_openrouter.py`
  - `.envrc`
  - `fake_key_123456789/`
  - `plans/persona-feature-handoff-summary.md`

## Forbidden Implementations

- Do not "fix" `persona add-sources` by adding a shim named `asky.research.ingestion`.
- Do not keep the knowledge model implicit in `chunks.json` plus prose comments.
- Do not store the new canonical persona knowledge layer only in memory or only in SQLite.
- Do not break v1/v2 persona import/load by forcing a clean-break schema.
- Do not silently append duplicate manual-source content when the same source fingerprint is ingested again.
- Do not flatten authored-book viewpoints into unlabeled raw chunks inside the canonical catalog.
- Do not persist bounded-inference answers as persona knowledge.
- Do not implement the later milestone's full authored-book runtime planner, subtopic narrowing engine, or current-event synthesis pipeline here.
- Do not reintroduce LLM tool-driven persona creation/import/load workflows in docs or code. Persona management remains CLI-first plus `@mention` loading.
- Do not update the root `AGENTS.md`.
- Do not add a new README section or README feature blurb for this work. Search the existing README; if there is still no directly relevant persona section, leave README untouched.

## Checkpoints

### [x] Checkpoint 1: Canonical Knowledge Catalog And Schema Compatibility

**Goal:**

- Add an additive schema-v3 persona knowledge foundation and make it rebuildable from existing v1/v2 artifacts.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,220p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,320p' src/asky/plugins/manual_persona_creator/storage.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/exporter.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/importer.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/knowledge_types.py`
- `src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `tests/asky/plugins/manual_persona_creator/test_knowledge_catalog.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/storage.py`
- `src/asky/plugins/manual_persona_creator/exporter.py`
- `src/asky/plugins/persona_manager/importer.py`
- `tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py`
- `tests/asky/plugins/persona_manager/test_authored_book_import.py`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/cli/**`
- `tests/integration/**`
- Constraints:
- keep import/export backward compatible
- keep `chunks.json` and `embeddings.json` present
- keep the new catalog entirely file-backed inside each persona package

**Steps:**

- [x] Step 1: Add typed structures for `PersonaSourceRecord`, `PersonaKnowledgeEntry`, and the exact serialized enum values locked above.
- [x] Step 2: Define the exact schema-v3 durable files:
- `persona_knowledge/sources.json`
- `persona_knowledge/entries.json`
- [x] Step 3: Bump `PERSONA_SCHEMA_VERSION` to `3`, extend `SUPPORTED_SCHEMA_VERSIONS` to `{1, 2, 3}`, and implement deterministic catalog rebuild helpers for v1/v2 personas.
- [x] Step 4: Use these exact deterministic ids:
- `source_id = "book:<book_key>"` for authored books
- `source_id = "manual:<sha256(content_fingerprint)[:16]>"` for manual sources
- `entry_id = "chunk:<chunk_id>"` for raw-chunk entries
- `entry_id = "viewpoint:<viewpoint_entry_id>"` for authored-book viewpoints
- `entry_id = "evidence:<viewpoint_entry_id>:<index>"` for authored-book evidence excerpts
- [x] Step 5: Project current authored-book artifacts into the catalog exactly as:
- one `PersonaSourceRecord` per book
- one `viewpoint` entry per persisted viewpoint
- one `evidence_excerpt` entry per persisted evidence item, linked back to its viewpoint entry
- [x] Step 6: Add import/export support for `persona_knowledge/**` while still accepting v1/v2 archives that do not contain it.
- [x] Step 7: Keep missing catalog rebuild automatic on read/import for v1/v2 personas instead of failing validation.
- [x] Step 8: Add coverage for:
- v1 import remains valid
- v2 authored-book import remains valid
- schema-v3 export carries `persona_knowledge/**`
- rebuilt catalog ids are deterministic
- no absolute-path leakage reaches exported metadata

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_knowledge_catalog.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_e2e_persona_workflow.py tests/asky/plugins/persona_manager/test_persona_errors.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A v1 or v2 persona can be imported and rebuilt into schema-v3-compatible catalog artifacts without losing compatibility chunks or embeddings.
- A git commit is created with message: `persona: add canonical knowledge catalog foundation`

**Stop and Escalate If:**

- v1/v2 compatibility would require dropping authored-book data or forcing a clean-break schema.
- import/export parity would require moving persona knowledge into global tables.

### [x] Checkpoint 2: Repair Manual Source Ingestion And Hardening Surface

**Goal:**

- Replace the broken `persona add-sources` path with a reusable persona-owned service that updates chunks, embeddings, and the canonical catalog deterministically.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '440,560p' src/asky/cli/persona_commands.py`
- `sed -n '1,320p' src/asky/plugins/manual_persona_creator/ingestion.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_persona_commands.py`
- `sed -n '1,220p' tests/integration/cli_recorded/test_cli_persona_recorded.py`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/source_service.py`
- `tests/asky/plugins/manual_persona_creator/test_source_service.py`
- May modify:
- `src/asky/cli/persona_commands.py`
- `src/asky/plugins/manual_persona_creator/ingestion.py`
- `src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `tests/asky/plugins/persona_manager/test_persona_commands.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/plugins/persona_manager/plugin.py`
- Constraints:
- CLI remains a thin wrapper
- source loading must reuse existing local-source adapters and current chunker
- default persona import/export behavior must remain intact

**Steps:**

- [x] Step 1: Add a reusable service entrypoint that wraps `ingest_persona_sources()`, appends normalized chunks, updates `persona_knowledge/**`, rebuilds embeddings, and returns typed stats plus warnings.
- [x] Step 2: Replace the broken `from asky.research.ingestion import ingest_sources` path with the new service call.
- [x] Step 3: Compute a deterministic manual-source content fingerprint from normalized loaded text and skip re-adding a source when the same fingerprint already exists in `persona_knowledge/sources.json`.
- [x] Step 4: Keep chunk ids deterministic within one add-sources run and ensure repeated ingestion of unchanged sources reports `skipped_existing_sources` instead of appending duplicates.
- [x] Step 5: Surface these exact CLI outputs from the service result:
- processed source count
- skipped existing source count
- added chunk count
- warning count
- [x] Step 6: Strengthen tests so persona source ingestion asserts actual stored outcomes, not just `exit_code == 0`.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_service.py tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli`

**Done When:**

- Verification commands pass cleanly.
- `asky persona add-sources` no longer references a missing import and no longer passes with only exit-code coverage.
- A git commit is created with message: `persona: repair manual source ingestion path`

**Stop and Escalate If:**

- Existing local-source adapters cannot support the documented manual-source file types without research-package API changes.
- Reliable dedupe would require persisting raw source text outside the persona package.

### [x] Checkpoint 3: Minimal Grounded Persona Runtime Contract

**Goal:**

- Add the smallest user-visible runtime hardening needed to make persona answers grounded, citation-labeled, and evaluation-ready without pulling the later runtime milestone forward.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,240p' src/asky/plugins/hook_types.py`
- `grep -R -n "PRE_LLM_CALL\\|POST_LLM_RESPONSE\\|SYSTEM_PROMPT_EXTEND\\|PRE_PRELOAD" src/asky/core src/asky/api src/asky/plugins`
- `sed -n '120,220p' src/asky/plugins/persona_manager/plugin.py`
- `sed -n '1,240p' src/asky/plugins/persona_manager/knowledge.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_persona_manager.py`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/persona_manager/runtime_grounding.py`
- May modify:
- `src/asky/plugins/persona_manager/plugin.py`
- `src/asky/plugins/persona_manager/knowledge.py`
- `tests/asky/plugins/persona_manager/test_persona_manager.py`
- `tests/asky/plugins/persona_manager/test_mention_pipeline.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/cli/main.py`
- Constraints:
- use plugin hooks, not core imports of persona plugin modules
- lean mode remains exempt
- do not implement authored-book-specific topic planning or current-event reasoning orchestration

**Steps:**

- [x] Step 1: Add a typed `PersonaEvidencePacket` helper that joins retrieval results to canonical catalog metadata and emits packets with exact per-turn ids `P1`, `P2`, `P3` in descending rank order.
- [x] Step 2: Format persona preload context as `Persona Evidence Packet:` instead of unlabeled raw snippets. Each packet must include:
- packet id
- source label
- source class
- trust class
- evidence text
- [x] Step 3: Extend the loaded-persona system prompt with this exact answer contract for non-lean turns:
- an `Answer:` section
- a `Grounding:` line with one of `direct_evidence`, `supported_pattern`, `bounded_inference`, `insufficient_evidence`
- an `Evidence:` section citing `[P#]` packet ids
- [x] Step 4: Add a `POST_LLM_RESPONSE` validator that checks persona-loaded non-tool replies. If the answer omits a valid grounding line or omits `[P#]` evidence refs while packets exist, replace the reply with this exact fallback template:
- `I don't have enough grounded persona evidence to answer this reliably.`
- blank line
- `Grounding: insufficient_evidence`
- `Evidence:`
- one bullet per available packet using `[P#] <source label>`
- [x] Step 5: Keep the validator neutral and non-persistent. It must not write any answer content back into persona artifacts.
- [x] Step 6: Add deterministic tests for:
- evidence-packet formatting
- valid grounded reply pass-through
- invalid uncited reply fallback
- lean-mode bypass
- authored-book packet source labeling

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/persona_manager/test_persona_manager.py tests/asky/plugins/persona_manager/test_mention_pipeline.py -q -n0`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli`

**Done When:**

- Verification commands pass cleanly.
- A loaded persona reply in a normal turn visibly carries grounding classification plus evidence labels, or falls back to explicit insufficient evidence.
- A git commit is created with message: `persona: add minimal grounded runtime contract`

**Stop and Escalate If:**

- Enforcing the minimal grounding contract requires changes inside `core/engine.py` instead of plugin hooks.
- The fallback behavior would misattribute evidence to claims that were never grounded in the retrieved packet.

### [x] Checkpoint 4: Deterministic Persona Evaluation Gate

**Goal:**

- Add a persona-specific evaluation harness and make it a deterministic acceptance gate in the default pytest lane.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,220p' src/asky/evals/AGENTS.md`
- `sed -n '1,220p' src/asky/evals/research_pipeline/AGENTS.md`
- `find src/asky/evals -maxdepth 3 -type f | sort`
- `find tests/asky/evals -maxdepth 3 -type f | sort`
- `sed -n '1,240p' tests/AGENTS.md`
- `sed -n '1,240p' tests/ARCHITECTURE.md`

**Scope & Blast Radius:**

- May create:
- `src/asky/evals/persona_pipeline/__init__.py`
- `src/asky/evals/persona_pipeline/dataset.py`
- `src/asky/evals/persona_pipeline/assertions.py`
- `src/asky/evals/persona_pipeline/evaluator.py`
- `tests/asky/evals/persona_pipeline/test_persona_pipeline.py`
- `tests/fixtures/persona_eval/`
- May modify:
- `tests/AGENTS.md`
- `tests/ARCHITECTURE.md`
- Must not touch:
- `tests/integration/cli_live/**`
- `tests/integration/cli_recorded/test_cli_real_model_recorded.py`
- Constraints:
- default evals must stay deterministic
- no live provider dependency
- no outbound network

**Steps:**

- [x] Step 1: Add a persona-eval dataset schema and evaluator modeled after the research eval structure, but scoped to loaded-persona answer behavior.
- [x] Step 2: Build committed fixture personas and cases that cover exactly these acceptance scenarios:
- direct-evidence answer with citation labels
- supported-pattern answer with citations from more than one source record
- invalid uncited direct-claim draft collapsing to `insufficient_evidence`
- bounded-inference or insufficient-evidence handling for an unseen-topic query
- [x] Step 3: Run eval cases through the actual persona plugin path with deterministic model stubs rather than hand-checking helper functions only.
- [x] Step 4: Add assertion helpers that score:
- citation presence
- evidence label validity
- unsupported direct-claim attribution
- bounded-inference / insufficient-evidence discipline
- [x] Step 5: Keep the eval gate in the default pytest lane by placing the deterministic coverage under `tests/asky/evals/persona_pipeline/`.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/evals/persona_pipeline/test_persona_pipeline.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_persona_manager.py tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The default test lane now contains deterministic persona-specific acceptance coverage for grounding and citation behavior.
- A git commit is created with message: `persona: add deterministic persona eval gate`

**Stop and Escalate If:**

- A meaningful gate would require real-provider behavior instead of deterministic stubs.
- The planned fixture personas cannot model authored-book plus manual-source cases without depending on non-committed artifacts.

### [x] Checkpoint 5: Documentation Parity And Final Regression

**Goal:**

- Bring docs and agent guidance to parity with the implemented milestone-0 behavior and run the final regression pass in the VM.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,320p' ARCHITECTURE.md`
- `sed -n '1,320p' devlog/DEVLOG.md`
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,220p' src/asky/evals/AGENTS.md`
- `sed -n '1,180p' docs/plugins.md`
- `grep -R -n "persona" README.md docs src | head -n 80`

**Scope & Blast Radius:**

- May modify:
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `src/asky/plugins/AGENTS.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/plugins/persona_manager/AGENTS.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/evals/AGENTS.md`
- `docs/plugins.md`
- `tests/AGENTS.md`
- `tests/ARCHITECTURE.md`
- Must not touch:
- root `AGENTS.md`
- `README.md` unless an already relevant persona section now exists
- docs for future GUI pages or future full persona runtime behavior
- Constraints:
- docs must describe only the milestone-0 behavior that actually ships
- remove stale claims about tool-driven persona management and missing CLI surface
- if README still has no directly relevant persona section, leave it unchanged

**Steps:**

- [x] Step 1: Update architecture docs to describe:
- schema-v3 additive persona knowledge catalog
- manual-source hardening path
- minimal grounded persona runtime contract
- deterministic persona eval harness
- [x] Step 2: Update `docs/plugins.md` so it no longer claims persona plugins are tool-driven or lack dedicated CLI commands.
- [x] Step 3: Update the affected `AGENTS.md` files for the changed plugin/eval/data-flow contracts.
- [x] Step 4: Search README for an already relevant persona section. If none exists, leave README untouched and note that decision in the devlog/docs diff.
- [x] Step 5: Run the full regression from inside the VM:
- `TIMEFORMAT="real %R\nuser %U\nsys %S"; time uv run pytest -q`
- [x] Step 6: Compare the final wall time to the current baseline `real 14.746`. If the new wall time exceeds the baseline by more than `max(3.0s, 20%)`, investigate with `uv run pytest -q --durations=20` and optimize or mark newly expensive tests `slow` before closing the handoff.

**Dependencies:**

- Depends on Checkpoints 1-4.

**Verification:**

- Run scoped doc checks: `! grep -R -n "tool execution\\|tool-based entry points\\|No dedicated persona CLI commands yet" docs/plugins.md ARCHITECTURE.md src/asky/plugins src/asky/cli/AGENTS.md`
- Run final regression: `TIMEFORMAT="real %R\nuser %U\nsys %S"; time uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Stale persona documentation is removed and the final suite is green inside `/home/evren/code/asky`.
- A git commit is created with message: `persona: document milestone0 hardening and run final regression`

**Stop and Escalate If:**

- The final default suite becomes materially unstable or provider-dependent.
- Documentation parity would require describing future milestone behavior that is still unimplemented.

## Behavioral Acceptance Tests

- Given an existing authored-book persona created before this handoff, loading or importing that persona rebuilds `persona_knowledge/sources.json` and `persona_knowledge/entries.json` without removing `chunks.json` or `embeddings.json`.
- Given `asky persona add-sources analyst notes.md`, the command completes without import errors, reports processed and skipped counts, and updates both compatibility chunks and canonical knowledge records.
- Given the same manual source re-added unchanged, the command reports it as skipped and does not append duplicate chunk-backed knowledge entries.
- Given a loaded persona and a normal non-lean query with relevant evidence, the reply contains:
- an `Answer:` section
- one valid `Grounding:` label
- an `Evidence:` section with `[P#]` ids that match the retrieved packet ids
- Given a loaded persona and a query with weak or no persona evidence, the reply does not invent a direct statement from the persona and instead returns the explicit insufficient-evidence fallback.
- Given deterministic persona-eval fixtures, default pytest fails if citation labels disappear, unsupported direct claims are allowed through, or persona source-ingestion / loading regressions break the current persona flow.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Schema-v3 additive catalog exists and rebuilds from older personas | `uv run pytest tests/asky/plugins/manual_persona_creator/test_knowledge_catalog.py -q -n0` |
| v1/v2 persona import/export compatibility remains intact | `uv run pytest tests/asky/plugins/persona_manager/test_authored_book_import.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py -q -n0` |
| `persona add-sources` no longer depends on missing import and now updates real artifacts | `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_service.py tests/asky/plugins/persona_manager/test_persona_commands.py -q -n0` |
| CLI persona surface asserts real ingestion outcomes, not exit status only | `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli` |
| Minimal grounded runtime contract is enforced for non-lean persona turns | `uv run pytest tests/asky/plugins/persona_manager/test_persona_manager.py tests/asky/plugins/persona_manager/test_mention_pipeline.py -q -n0` |
| Deterministic persona eval gate covers citations, attribution, and unsupported inference | `uv run pytest tests/asky/evals/persona_pipeline/test_persona_pipeline.py -q -n0` |
| Stale persona docs are removed | `! grep -R -n "tool execution\\|tool-based entry points\\|No dedicated persona CLI commands yet" docs/plugins.md ARCHITECTURE.md src/asky/plugins src/asky/cli/AGENTS.md` |
| Final regression remains green and proportionate in runtime | `TIMEFORMAT="real %R\nuser %U\nsys %S"; time uv run pytest -q` |

## Assumptions And Defaults

- This handoff resolves the roadmap numbering mismatch by explicitly targeting **Milestone 0** from `plans/persona-roadmap.md`. The already-implemented authored-book handoff remains milestone 1 despite the conflicting summary numbering.
- The user allowed broad architectural movement because the app is still early alpha, but this plan still chooses the safer path: **additive schema-v3 migration with backward compatibility**, not a clean break.
- The minimal runtime hardening in this handoff is intentionally the ceiling for user-visible persona answering work here. The later runtime milestone still owns:
- structured authored-book-first retrieval
- deeper subtopic narrowing
- richer recent-event reasoning
- Trust/source taxonomy is defined now for future source types, but this milestone only populates `authored_book` and `manual_source` records.
- Default persona evals are deterministic and provider-free. Real-provider persona eval lanes are explicitly out of scope for this handoff.
- All implementation, testing, and verification commands for this handoff should be run **inside the Linux VM checkout** at `/home/evren/code/asky`.
- The repo already has unrelated dirty or untracked changes; the implementer must work around them and must not revert them.

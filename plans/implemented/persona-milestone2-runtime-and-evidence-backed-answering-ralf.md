# RALF Handoff Plan: Persona Milestone 2, Runtime And Evidence-Backed Answering

## Summary

Implement roadmap milestone 2 as the first real persona-answering runtime, built on top of the milestone-0 knowledge catalog and milestone-1 authored-book ingestion. The milestone must make loaded personas and `@mention` turns materially different from prompt injection by:

- retrieving from all current persona knowledge, not only compatibility chunks,
- prioritizing authored-book viewpoints and their supporting excerpts before falling back to raw manual-source chunks,
- keeping the default persona answer contract visibly structured,
- using live current-event context when needed through the existing web/tool surface,
- separating persona evidence from fresh current-context attribution in the final answer,
- failing closed to `insufficient_evidence` when fresh web context exists but persona worldview support does not.

This handoff does **not** add new source types, new persona commands, GUI work, or a review console. It only upgrades the runtime, reply contract, evaluation gate, and documentation for the already shipped persona surfaces.

## Public Interfaces

- No new persona CLI subcommands or config flags are introduced in this milestone. Existing entrypoints remain:
  - `asky persona load <name>`
  - `asky persona current`
  - `@persona_name ...`
- Persona replies keep the structured default contract and expand it to separate fresh-event attribution:
  - `Answer: ...`
  - `Grounding: <direct_evidence|supported_pattern|bounded_inference|insufficient_evidence>`
  - `Evidence: [P#], [P#]`
  - `Current Context:` followed by `- [W#] ...` lines only when live web/current-context sources were used during the turn
- Persona packages gain one new derived runtime artifact:
  - `persona_knowledge/runtime_index.json`
- `persona_knowledge/runtime_index.json` is rebuildable derived data like `embeddings.json`. It must not become the canonical source of truth and must not be exported in persona archives.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `3aa39e7724dea2814dc131a9f2482e0b53ec0fe5`
- Last Reviewed HEAD: `approved+squashed; finalized plan intentionally omits the post-squash SHA`
- Review Log:
  - `2026-03-14`: corrected the original handoff squash anchor to the actual branch ancestor `3aa39e7724dea2814dc131a9f2482e0b53ec0fe5` before final finalization.
  - `2026-03-14`: reviewed `3aa39e7724dea2814dc131a9f2482e0b53ec0fe5..16dae1b240ae4280d1a7b069fdceeb35e9a079ac`, outcome `changes-requested`; follow-up plan `persona-milestone2-runtime-and-evidence-backed-answering-fixups-ralf.md`
  - `2026-03-14`: reviewed `16dae1b240ae4280d1a7b069fdceeb35e9a079ac..996a035b1883da8545a19d370f7bb7d2a6b5552d`, then squashed the full accumulated handoff `3aa39e7724dea2814dc131a9f2482e0b53ec0fe5..996a035b1883da8545a19d370f7bb7d2a6b5552d`, outcome `approved+squashed`

## Done Means

- A loaded persona or `@mention` turn retrieves structured persona knowledge from `persona_knowledge/runtime_index.json` and no longer relies on `embeddings.json` chunk search as the primary runtime path.
- Runtime retrieval uses all current persona knowledge:
  - authored-book viewpoints first,
  - authored-book evidence excerpts next,
  - raw manual-source chunks as fallback when structured coverage is weak.
- Persona packets injected into the model include source class, trust class, publication/book metadata where available, topic/stance metadata for viewpoints, and linked supporting excerpts.
- The default persona answer contract remains visible and structured:
  - `Answer`
  - `Grounding`
  - `Evidence`
  - `Current Context` when live current-event sources were used
- `direct_evidence` answers cite persona packets only and do not claim direct quotations or positions without matching packet support.
- `supported_pattern` answers cite at least two distinct persona packets.
- `bounded_inference` answers cite at least one persona packet and, when web/current-event tools were used, also include a separate `Current Context:` section with `[W#]` lines.
- If the turn used live web/current-event sources but persona worldview support is absent, the answer collapses to `insufficient_evidence` instead of becoming a generic web answer in persona voice.
- Existing `persona load`, `persona current`, session binding, and `@mention` behavior continue to work without new commands or flags.
- The deterministic persona eval gate covers direct evidence, supported patterns, bounded inference with live context, and web-only-without-persona-support failure cases.
- Docs and affected subdirectory `AGENTS.md` files are updated only for the behavior implemented in this same handoff.
- Final regression passes with `uv run pytest -q`, and any runtime increase is compared against the current baseline:
  - `1517 passed in 14.73s`
  - `real 14.94`

## Critical Invariants

- The canonical persona knowledge source remains `persona_knowledge/sources.json` plus `persona_knowledge/entries.json`. `runtime_index.json` and `embeddings.json` are derived artifacts only.
- Milestone 2 must use all currently supported persona knowledge, but authored-book viewpoints and excerpts must rank ahead of raw chunk fallback when relevance is comparable.
- The runtime must keep persona evidence and fresh current-event evidence visibly separate. Persona packets belong in `Evidence:`; live web/current-event sources belong in `Current Context:`.
- Fresh current-event context may support a persona answer, but it may not replace missing persona worldview support. No persona answer may rest only on web search results.
- No new persona ingestion modes, GUI pages, review workflows, or browser-only acquisition paths may be added in this handoff.
- Existing CLI entrypoints and `@mention` behavior must remain the only user entrypoints for persona answering in this milestone.
- `lean` turns still skip persona preload/runtime grounding behavior.
- No new third-party package dependency may be added. Reuse the existing embedding client, vector helpers, web tools, and hook surface.

## Forbidden Implementations

- Do not keep `embeddings.json` chunk retrieval as the primary persona-answering runtime after this milestone.
- Do not stuff full authored-book text or large raw source bodies directly into the system prompt as a replacement for structured retrieval.
- Do not mix persona evidence and live current-event evidence into one unlabeled block.
- Do not answer a recent-event question in persona voice using only web/current-event sources with no persona packets.
- Do not add new persona commands, new persona config flags, or a separate persona chat mode in this milestone.
- Do not export `persona_knowledge/runtime_index.json`, raw fetched web pages, or any current-event scratch state in persona archives.
- Do not modify the root `AGENTS.md`.
- Do not update README unless an already relevant persona-runtime section exists. In this checkout, no such section exists, so README should stay untouched unless that fact changes during implementation.

## Checkpoints

### [x] Checkpoint 1: Canonical Runtime Index Foundation

**Goal:**

- Add a rebuildable runtime index derived from the canonical persona knowledge catalog so milestone 2 can retrieve structured persona entries without using compatibility chunks as the primary source.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,240p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/knowledge.py`
- `sed -n '1,260p' tests/asky/plugins/manual_persona_creator/test_knowledge_catalog.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/runtime_index.py`
- `tests/asky/plugins/manual_persona_creator/test_runtime_index.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/knowledge_catalog.py`
- `src/asky/plugins/manual_persona_creator/source_service.py`
- `src/asky/plugins/manual_persona_creator/book_ingestion.py`
- `src/asky/plugins/persona_manager/importer.py`
- `tests/asky/plugins/manual_persona_creator/test_source_service.py`
- `tests/asky/plugins/manual_persona_creator/test_book_ingestion.py`
- `tests/asky/plugins/persona_manager/test_authored_book_import.py`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/cli/**`
- `tests/integration/**`
- Constraints:
- keep `embeddings.json` present as a compatibility artifact
- keep `runtime_index.json` derived only from canonical catalog data
- exclude `runtime_index.json` from export and rebuild it on import like `embeddings.json`
- do not store raw full-book text or fetched live-web text in the derived runtime index

**Steps:**

- [ ] Step 1: Add a runtime-index record type keyed by canonical `entry_id`, carrying:
  - `entry_kind`
  - `source_id`
  - `source_class`
  - `trust_class`
  - normalized searchable text
  - metadata needed at runtime (`topic`, `stance_label`, `book_key`, `book_title`, `publication_year`, `section_ref`, parent linkage)
  - embedding vector
- [ ] Step 2: Define the exact derived artifact path:
  - `persona_knowledge/runtime_index.json`
- [ ] Step 3: Build the runtime index from canonical knowledge entries only:
  - authored-book `viewpoint` entries
  - authored-book `evidence_excerpt` entries
  - manual-source `raw_chunk` entries
- [ ] Step 4: Rebuild the runtime index whenever persona knowledge changes through:
  - manual `add-sources`
  - authored-book materialization/reingestion
  - persona archive import/rebuild
- [ ] Step 5: Keep runtime-index rebuild automatic when older persona packages are read/imported and their catalog is rebuilt.
- [ ] Step 6: Keep archive portability behavior explicit:
  - do not export `runtime_index.json`
  - after import, rebuild `runtime_index.json`
  - keep `embeddings.json` rebuild behavior intact
- [ ] Step 7: Add tests for:
  - deterministic runtime-index rebuild from authored-book viewpoints and excerpts
  - raw manual-source chunk inclusion
  - no absolute-path leakage
  - import rebuild recreates `runtime_index.json` without exporting it

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_runtime_index.py tests/asky/plugins/manual_persona_creator/test_source_service.py tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_persona_errors.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Personas with milestone-0/1 knowledge artifacts rebuild a usable `persona_knowledge/runtime_index.json` without changing the canonical catalog contract.
- A git commit is created with message: `persona: add canonical runtime index`

**Stop and Escalate If:**

- A useful runtime index would require exporting derived embeddings or storing raw full-book bodies in persona packages.
- Import compatibility would require changing the canonical persona archive contract rather than rebuilding derived artifacts.

### [x] Checkpoint 2: Structured Persona Retrieval And Packet Planning

**Goal:**

- Replace chunk-only persona retrieval with a structured runtime planner that uses all persona knowledge, prioritizes authored-book viewpoints, and injects richer persona packets before the model runs.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/persona_manager/knowledge.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/runtime_grounding.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/plugin.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/runtime_index.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_persona_manager.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_grounding.py`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/persona_manager/runtime_types.py`
- `src/asky/plugins/persona_manager/runtime_planner.py`
- `tests/asky/plugins/persona_manager/test_runtime_planner.py`
- May modify:
- `src/asky/plugins/persona_manager/knowledge.py`
- `src/asky/plugins/persona_manager/runtime_grounding.py`
- `src/asky/plugins/persona_manager/plugin.py`
- `tests/asky/plugins/persona_manager/test_persona_manager.py`
- Must not touch:
- `src/asky/cli/**`
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/plugins/manual_persona_creator/exporter.py`
- Constraints:
- no new CLI/config surface
- retrieval must read canonical runtime-index data, not `embeddings.json`
- authored-book viewpoints outrank raw manual chunks when scores are comparable
- keep existing `knowledge_top_k` config as the only packet-count tuning input in this milestone

**Steps:**

- [ ] Step 1: Add typed runtime models for:
  - structured persona evidence packets
  - turn-level persona plan state
  - any planner-side packet/source metadata needed by validation
- [ ] Step 2: Load and rank runtime-index matches by cosine similarity with exact priority:
  - `viewpoint`
  - `evidence_excerpt`
  - `raw_chunk`
  Ties prefer higher-trust sources, then authored-book sources, then deterministic entry id ordering.
- [ ] Step 3: Hydrate top viewpoint packets with linked supporting excerpts so the model sees both the worldview claim and the underlying authored-book evidence.
- [ ] Step 4: Use raw-chunk packets only as fallback support when structured viewpoint coverage is weak or the matching source is manual-source-only.
- [ ] Step 5: Expand packet formatting so the model receives:
  - source label
  - source class
  - trust class
  - topic and stance when present
  - publication year/book title when present
  - excerpt lines for supporting evidence
- [ ] Step 6: Store the planned persona packets on thread-local plugin state during `PRE_PRELOAD` and inject them through `additional_source_context`.
- [ ] Step 7: Keep persona preload skipped for `lean` turns exactly as today.
- [ ] Step 8: Add tests for:
  - authored-book viewpoint priority over raw chunks
  - fallback to manual raw chunks when no viewpoints match
  - packet formatting includes topic/book metadata and linked excerpts
  - `knowledge_top_k` still bounds the final packet count

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/persona_manager/test_runtime_planner.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_mention_pipeline.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Persona preload for loaded personas is driven by structured runtime-index retrieval and injects authored-book-first packets instead of plain chunk snippets.
- A git commit is created with message: `persona: add structured runtime planner`

**Stop and Escalate If:**

- Structured retrieval would require changing core engine/tool-registry code rather than living inside the existing persona-manager hook surface.
- Retrieval quality depends on a new vector dependency instead of the existing embedding helpers.

### [x] Checkpoint 3: Grounding Contract And Current-Context Attribution

**Goal:**

- Enforce the milestone-2 reply contract for direct evidence, supported patterns, bounded inference, and separate current-context attribution when live web/current-event sources were used.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/persona_manager/plugin.py`
- `sed -n '1,260p' src/asky/plugins/persona_manager/runtime_grounding.py`
- `sed -n '1,260p' src/asky/plugins/hook_types.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_grounding.py`
- `sed -n '1,260p' tests/asky/evals/persona_pipeline/test_persona_eval_gate.py`

**Scope & Blast Radius:**

- May create:
- `tests/asky/plugins/persona_manager/test_runtime_current_context.py`
- May modify:
- `src/asky/plugins/persona_manager/plugin.py`
- `src/asky/plugins/persona_manager/runtime_grounding.py`
- `tests/asky/plugins/persona_manager/test_grounding.py`
- Must not touch:
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- `src/asky/core/tool_registry_factory.py`
- `src/asky/api/**`
- Constraints:
- keep the structured persona reply as the default surface
- keep persona evidence and live current-context citations separate
- no new persona tools, no new query mode, no new parser path

**Steps:**

- [ ] Step 1: Register `POST_TOOL_EXECUTE` in the persona manager plugin and track live current-context sources used during persona turns for the existing web tool family:
  - `web_search`
  - `get_url_content`
  - `get_url_details`
  - any equivalent shortlist/search-only tool names already exposed by the normal registry
- [ ] Step 2: Extend the system prompt grounding contract to this exact visible structure:
  - `Answer: ...`
  - `Grounding: ...`
  - `Evidence: [P#], ...`
  - `Current Context:` followed by `- [W#] ...` lines only when live sources were used
- [ ] Step 3: Enforce these validation rules:
  - `direct_evidence` requires at least one valid persona packet citation
  - `supported_pattern` requires at least two distinct persona packet citations
  - `bounded_inference` requires at least one valid persona packet citation
  - if tracked live sources were used, `Current Context:` must exist and every `[W#]` line must map to a tracked source
  - if no persona packet support exists, fall back to `insufficient_evidence` even when live sources exist
- [ ] Step 4: Keep the existing safe fallback posture and clear all persona packets plus tracked current-context state on `TURN_COMPLETED`.
- [ ] Step 5: Add tests for:
  - valid direct evidence
  - valid supported pattern
  - valid bounded inference with `Current Context`
  - missing `Current Context` after live-source use triggers fallback
  - web-only answer with no persona packets triggers `insufficient_evidence`

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/persona_manager/test_grounding.py tests/asky/plugins/persona_manager/test_runtime_current_context.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_mention_pipeline.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Persona turns that used live current-event sources produce separate persona evidence and current-context attribution, and invalid mixed-attribution answers collapse to the safe fallback.
- A git commit is created with message: `persona: enforce runtime grounding and current context`

**Stop and Escalate If:**

- Existing web-tool results cannot be mapped back to stable source labels or URLs without changing core tool response contracts.
- The required validation rules would force a new parser/command surface instead of fitting into the current persona-manager plugin hooks.

### [x] Checkpoint 4: Persona Eval Gate And Real Chat-Path Coverage

**Goal:**

- Make milestone-2 behavior measurable in the default test lane and protect the actual `@mention`/loaded-persona chat path from regressing back to prompt-only simulation.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,240p' src/asky/evals/persona_pipeline/dataset.py`
- `sed -n '1,260p' src/asky/evals/persona_pipeline/assertions.py`
- `sed -n '1,320p' tests/asky/evals/persona_pipeline/test_persona_eval_gate.py`
- `sed -n '1,260p' tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `sed -n '1,260p' tests/asky/plugins/persona_manager/test_mention_pipeline.py`

**Scope & Blast Radius:**

- May modify:
- `src/asky/evals/persona_pipeline/dataset.py`
- `src/asky/evals/persona_pipeline/assertions.py`
- `tests/asky/evals/persona_pipeline/test_persona_eval_gate.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `tests/asky/plugins/persona_manager/test_mention_pipeline.py`
- `tests/asky/plugins/persona_manager/test_persona_manager.py`
- May create:
- additional persona-manager runtime tests under `tests/asky/plugins/persona_manager/`
- Must not touch:
- `tests/integration/cli_live/**`
- `scripts/run_research_quality_gate.sh`
- Constraints:
- keep this milestone fully testable in the default lane
- do not add live-provider or live-web requirements to persona regression coverage

**Steps:**

- [ ] Step 1: Extend persona eval assertions so they can validate:
  - `Evidence:` `[P#]` citations
  - optional `Current Context:` `[W#]` lines
  - expected fallback for unsupported direct claims or web-only persona answers
- [ ] Step 2: Update eval fixtures so they build the new runtime index and include authored-book viewpoint plus manual-source coverage in the test persona.
- [ ] Step 3: Add deterministic eval cases for:
  - direct evidence from one authored-book viewpoint
  - supported pattern across at least two persona packets
  - bounded inference with persona evidence plus tracked current context
  - live current context without persona worldview support collapsing to `insufficient_evidence`
  - missing `Current Context` after live-source usage collapsing to fallback
- [ ] Step 4: Strengthen recorded CLI coverage so a real persona chat path still renders the milestone-2 structured contract through `@mention` or a loaded session persona.
- [ ] Step 5: Keep all new persona regression tests deterministic through stubs, fake tool outputs, or cassette-backed replay only.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/evals/persona_pipeline/test_persona_eval_gate.py tests/asky/plugins/persona_manager/test_mention_pipeline.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli`

**Done When:**

- Verification commands pass cleanly.
- The default test lane fails if persona answers drop persona citations, blur current-context attribution, or answer recent-event questions without persona worldview support.
- A git commit is created with message: `persona: add runtime eval coverage`

**Stop and Escalate If:**

- Recorded CLI verification would require live provider calls or non-deterministic live web traffic.
- The eval gate cannot express current-context attribution without changing the user-visible reply contract beyond this milestone’s agreed shape.

### [x] Checkpoint 5: Documentation Parity And Final Regression

**Goal:**

- Update architecture, operator docs, and local agent guidance to match the implemented milestone-2 runtime, then run final regression and compare runtime against the captured baseline.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' ARCHITECTURE.md`
- `sed -n '1,260p' devlog/DEVLOG.md`
- `sed -n '1,260p' docs/plugins.md`
- `sed -n '1,240p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,240p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,240p' src/asky/cli/AGENTS.md`
- `grep -n "persona" README.md`

**Scope & Blast Radius:**

- May modify:
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `docs/plugins.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/plugins/persona_manager/AGENTS.md`
- `src/asky/cli/AGENTS.md`
- Must not touch:
- `AGENTS.md`
- `README.md` unless a directly relevant existing persona-runtime section appears during implementation
- docs for later milestones (biographies, scraping, GUI review, diarization)
- Constraints:
- docs must describe only behavior implemented in checkpoints 1-4
- if README still has no directly relevant persona-runtime section, leave it unchanged and say why in the devlog/docs pass

**Steps:**

- [ ] Step 1: Update `ARCHITECTURE.md` for:
  - `persona_knowledge/runtime_index.json`
  - authored-book-first structured runtime retrieval
  - current-context attribution in persona answers
  - persona-manager hook usage beyond the milestone-0 minimal grounding contract
- [ ] Step 2: Update `docs/plugins.md` so the persona section reflects milestone-2 runtime behavior and the new `Current Context:` separation.
- [ ] Step 3: Update affected subdirectory `AGENTS.md` files only where the shipped milestone changed local guidance:
  - `src/asky/plugins/manual_persona_creator/AGENTS.md`
  - `src/asky/plugins/persona_manager/AGENTS.md`
  - `src/asky/cli/AGENTS.md` only if persona runtime expectations there changed materially
- [ ] Step 4: Update `devlog/DEVLOG.md` with the milestone summary, runtime behavior change, new derived artifact, test/runtime results, and any follow-up gotchas.
- [ ] Step 5: Leave README untouched unless a directly relevant existing persona-runtime section is found.
- [ ] Step 6: Run final regression and compare against baseline `1517 passed in 14.73s`, `real 14.94`.

**Dependencies:**

- Depends on Checkpoint 4.

**Verification:**

- Run scoped checks: `grep -RIn "runtime_index.json\\|Current Context:\\|bounded_inference\\|Evidence:" ARCHITECTURE.md docs/plugins.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md src/asky/cli/AGENTS.md`
- Run final regression: `time -p uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs describe only the implemented milestone-2 runtime behavior.
- Final test runtime is compared against the recorded baseline and any material increase is explained.
- A git commit is created with message: `docs: document persona runtime milestone`

**Stop and Escalate If:**

- Documentation parity would require describing future source types, GUI review flows, or later roadmap behavior not implemented in the same handoff.
- Final suite runtime regresses materially and the cause cannot be tied to the added coverage.

## Behavioral Acceptance Tests

- A user can load persona `arendt` and ask a known-topic question. The answer uses the structured default format, cites persona packets in `Evidence:`, and does not rely on compatibility-chunk-only retrieval.
- A user can ask a question that is supported by multiple persona artifacts. The answer uses `Grounding: supported_pattern` and cites at least two distinct `[P#]` packet ids.
- A user can ask `@arendt What would she likely think about a recent labor strike today?` and the runtime can combine persona worldview packets with live current-event web context. The final answer uses `Grounding: bounded_inference`, keeps persona packet citations in `Evidence:`, and shows separate `Current Context:` `[W#]` lines for the fresh event sources used.
- If the runtime gathers fresh web/current-event context but cannot retrieve relevant persona worldview support, the final answer does not become a generic current-events answer in persona voice. It falls back to `Grounding: insufficient_evidence`.
- If the model drafts a persona answer that cites invalid packet ids, omits `Current Context:` after using live sources, or labels a synthesis as `direct_evidence`, the post-response validator replaces it with the safe fallback.
- Existing `persona load`, `persona current`, and `@mention` behavior still work after milestone 2 without any new persona commands.
- Importing an existing milestone-0 or milestone-1 persona rebuilds `runtime_index.json` automatically, and exported persona packages remain portable because the runtime index is derived and excluded from the archive.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Runtime uses all persona knowledge with authored-book-first priority | `uv run pytest tests/asky/plugins/persona_manager/test_runtime_planner.py tests/asky/plugins/persona_manager/test_persona_manager.py -q -n0` |
| Derived `runtime_index.json` is rebuilt, not canonical/exported | `uv run pytest tests/asky/plugins/manual_persona_creator/test_runtime_index.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0` |
| `direct_evidence`, `supported_pattern`, and `bounded_inference` validation rules hold | `uv run pytest tests/asky/plugins/persona_manager/test_grounding.py tests/asky/plugins/persona_manager/test_runtime_current_context.py -q -n0` |
| Fresh current-event context is visibly separated from persona evidence | `uv run pytest tests/asky/plugins/persona_manager/test_runtime_current_context.py tests/asky/evals/persona_pipeline/test_persona_eval_gate.py -q -n0` |
| Web-only-without-persona-support collapses to `insufficient_evidence` | `uv run pytest tests/asky/evals/persona_pipeline/test_persona_eval_gate.py -q -n0` |
| Existing `@mention` and loaded-persona chat path still works | `uv run pytest tests/asky/plugins/persona_manager/test_mention_pipeline.py -q -n0` |
| CLI persona chat surface preserves the structured runtime contract | `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -m recorded_cli` |
| Docs and AGENTS files describe only shipped milestone-2 behavior | `grep -RIn "runtime_index.json\\|Current Context:\\|bounded_inference" ARCHITECTURE.md docs/plugins.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md src/asky/cli/AGENTS.md` |
| Final regression remains green | `time -p uv run pytest -q` |

## Assumptions And Defaults

- Milestone 2 covers the runtime only. No new ingestion source types, review gates, browser-assisted scraping, GUI work, biography handling, or diarization are included here.
- Runtime scope is all currently stored persona knowledge. Authored-book viewpoints and excerpts are preferred, but manual-source chunks remain valid fallback evidence.
- The default persona reply stays structured. Natural-prose-only replies are out of scope for this milestone.
- Recent-event/newer-topic handling uses the existing live web/current-context tool surface. This milestone does not add a new current-events acquisition subsystem.
- Persona evidence and fresh current-event context stay separate in the final answer. `Evidence:` is only for `[P#]`. `Current Context:` is only for `[W#]`.
- `Current Context:` is required only when live current-event sources were actually used during the turn.
- `knowledge_top_k` remains the packet-budget knob. No new persona runtime tuning flags/config values are added in this milestone.
- `persona_knowledge/runtime_index.json` is rebuildable derived data and must be excluded from export.
- README should remain unchanged in this handoff because the current README only links to plugin docs and does not contain a directly relevant persona-runtime section to update.

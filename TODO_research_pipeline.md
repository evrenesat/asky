# Research Pipeline Revamp TODO (Small-Model First)

Last updated: 2026-02-09
Branch/workspace: `codex/research-feature` at `/Users/evren/.claude-worktrees/asky/codex-research-feature`
Status: Planning (do not implement until user says Proceed)

## Objective

Replace model-driven research flow with a programmatic pipeline that:
- maximizes quality for small/local models,
- unifies local-file and web research into the same downstream retrieval flow,
- uses LLMs for fuzzy reasoning (query expansion, synthesis, quality checks), not orchestration.

## Product Direction (Revised)

- Use deterministic staged orchestration before answer synthesis.
- Build a bounded source corpus first (web shortlist or local files), then run retrieval/synthesis against that corpus.
- Reduce dependency on tool-choice quality from smaller models by exposing stage-specific toolsets only.
- Keep optional "big brain" model usage small-context and narrow-purpose (query planning, quality audit).

## Phase Plan

### Phase 0 - Baseline + Instrumentation
- [ ] Add stage-level metrics for current research flow:
  - tool call frequency (`save_finding`, `get_link_summaries`, `get_relevant_content`),
  - answer quality proxies (source count used, citation coverage),
  - latency per stage.
- [ ] Add benchmark prompts set (web + local corpus) for regression tracking.
- [ ] Define success thresholds for small-model runs.

### Phase 1 - Research Run Model + Session Isolation
- [ ] Use existing `session_id` as the isolation key for findings/indexed data.
- [ ] Add retention/cleanup policy for run-scoped findings and vector entries.
- [ ] Keep optional global memory lane, but default to run-scoped retrieval.

### Phase 2 - Pipeline Orchestrator (Programmatic Flow)
- [ ] Add a new research orchestrator module to own stage transitions.
- [ ] Stages (v1):
  1. query clarification/expansion,
  2. corpus acquisition (web shortlist or local ingestion),
  3. corpus normalization/chunking/indexing,
  4. targeted retrieval,
  5. evidence synthesis,
  6. optional quality audit.
- [ ] Add per-stage tool exposure controls (reuse existing registry exclusion mechanics).

### Phase 3 - Local Research Ingestion (Classical RAG path)
- [ ] Implement file ingestion pipeline for local sources:
  - PDF/EPUB/text/HTML -> normalized markdown/text,
  - chunk + embed + store into vector DB with source metadata.
- [ ] Prefer deterministic indexing over agentic browsing for local research mode.
- [ ] Add CLI entry path for local corpus selection.
- [ ] Use PyMuPDF-based reader path for PDF + EPUB in first milestone (plus HTML/text).
- [ ] Dependency note: confirm approval before adding/updating parser libs.

### Phase 4 - Web Corpus Builder (Bounded Internet -> Same RAG path)
- [ ] Expand pre-LLM source shortlisting:
  - `40` search candidates (default, configurable),
  - fetch/index top `20` sources (default, configurable),
  - better ranking/diversity pruning,
  - stronger dedupe/canonical handling.
- [ ] Fetch shortlisted pages and index all into the same corpus store as local files.
- [ ] Ensure web flow converges into the same retrieval stage as local flow.

### Phase 5 - Targeted Summarization + Retrieval
- [ ] Add focused summarization tool/path:
  - input: document/page/chunk + research sub-question,
  - output: query-relevant facts with provenance.
- [ ] Use retrieval first; summarization only on selected evidence windows.
- [ ] Reduce or remove low-value generic summary calls.

### Phase 6 - Model Roles + Config
- [ ] Add explicit model roles in config:
  - `worker_model` (small/local default),
  - `analysis_model` (optional model for planning/audit tasks; can be same as worker).
- [ ] Keep planner/auditor responsibilities as pipeline stages, not necessarily separate model IDs.
- [ ] Add hard caps for planner/auditor usage (calls, context size).
- [ ] Keep fallback behavior when optional roles are unset.

### Phase 7 - Prompt/Tool Contract Simplification
- [ ] Simplify research system prompt to align with pipeline stages.
- [ ] Keep only stage-relevant tools enabled at each stage.
- [ ] Deprecate tool instructions that rely on autonomous long-horizon planning.

### Phase 8 - Validation + Rollout
- [ ] Add integration tests for stage transitions and retrieval quality checks.
- [ ] Compare baseline vs new pipeline on benchmark prompt set.
- [ ] Gate rollout behind feature flag (`research_pipeline_v2`).
- [ ] Document migration and operational knobs.

## Proposed Implementation File Targets

- `src/asky/cli/chat.py`
- `src/asky/cli/main.py`
- `src/asky/core/tool_registry_factory.py`
- `src/asky/core/prompts.py`
- `src/asky/research/` (new orchestrator + ingestion/retrieval helpers)
- `src/asky/data/config/research.toml`
- `src/asky/config/__init__.py`
- `tests/` (new integration + behavior tests)
- `ARCHITECTURE.md`, `DEVLOG.md`, `src/asky/research/AGENTS.md` (as architecture evolves)

## Verification Strategy

- Unit tests:
  - stage routing,
  - run/session isolation,
  - tool exposure per stage,
  - retrieval and targeted summarization contracts.
- Integration tests:
  - local corpus end-to-end,
  - web shortlist-to-corpus end-to-end,
  - small-model fallback behavior without planner/auditor.
- Manual validation:
  - compare answer quality/citation completeness across fixed prompt set,
  - validate reduced dependence on opportunistic tool calls.

## Decisions Locked (2026-02-09)

- [x] Isolation key: use existing `session_id`.
- [x] Local ingestion milestone scope includes EPUB (via PyMuPDF path).
- [x] Planner and auditor can use the same configured model (`analysis_model`).
- [x] Web shortlist defaults: `40` candidates, `20` fetched/indexed sources (configurable).

## Remaining Clarifications

- [ ] Should `analysis_model` be enabled by default, or only when explicitly configured?
- [ ] For local ingestion UX, should first milestone accept only explicit file paths, or also directory recursion in v1?

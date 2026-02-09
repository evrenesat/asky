For older logs, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md)

## 2026-02-09

### Local Filesystem Target Guardrails for Generic Tools
**Summary**: Blocked implicit local-file access in generic URL/content tools so `local://`, `file://`, and path-like targets are no longer accepted there.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/url_utils.py`
      - added shared target classifiers:
        - `is_http_url(...)`
        - `is_local_filesystem_target(...)`
    - `/Users/evren/code/asky/src/asky/tools.py`
      - `get_url_content`/`fetch_single_url` now reject local targets and non-HTTP(S) schemes with explicit per-URL errors.
      - `get_url_details` now rejects local targets and non-HTTP(S) schemes with explicit errors.
    - `/Users/evren/code/asky/src/asky/research/tools.py`
      - `extract_links`, `get_link_summaries`, `get_relevant_content`, and `get_full_content` now reject local filesystem targets with explicit errors.
  - Added/updated tests:
    - `/Users/evren/code/asky/tests/test_tools.py`
      - coverage for local-target and non-HTTP target rejection in standard URL tools.
    - `/Users/evren/code/asky/tests/test_research_tools.py`
      - coverage for local-target rejection across research content tools.
    - `/Users/evren/code/asky/tests/test_research_adapters.py`
      - updated expectations so research content tools reject `local://...` targets directly.
  - Updated docs:
    - `/Users/evren/code/asky/src/asky/research/AGENTS.md`
    - `/Users/evren/code/asky/docs/research_eval.md`
    - `/Users/evren/code/asky/ARCHITECTURE.md`

- **Why**:
  - Prevents broad URL-oriented tools from becoming implicit local-file readers.
  - Keeps local-source access explicit and intentional through dedicated local-source workflows.

- **Gotchas / Follow-up**:
  - Local-snapshot eval prompts can still include local paths; these tools now return guardrail errors for those targets.
  - If local-source evaluation is still desired through tool calls, introduce dedicated explicit local-source tools and point matrix profiles to those tools.

### RFC/NIST Dataset Expectation Tuning (Wording-Robust Pass Conditions)
**Summary**: Relaxed brittle sentence-exact assertions in `rfc_http_nist_v1` to keyword/number-focused regex checks so semantically-correct paraphrases pass.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/evals/research_pipeline/datasets/rfc_http_nist_v1.yaml`
      - converted multiple `contains` checks to robust `regex` patterns with lookaheads:
        - `tls13-legacy-renegotiation-serverhello`
        - `http-obsoletes`
        - `http-safe-idempotent`
        - `nist-aal1-factors`
        - `nist-aal1-30-days`
        - `nist-password-salt-32-bits`
      - patterns now focus on required facts (keywords/numbers), not exact sentence formatting.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added guidance for `(?is)` and lookahead-based regex expectation tuning.

- **Why**:
  - Failures were dominated by strict string matching against otherwise-correct answers (markdown emphasis, casing, reordered phrasing).
  - Pass criteria now better reflect fact correctness instead of exact wording.

### Report Rendering Fixes + Single-File Failure Triage
**Summary**: Fixed markdown report table rendering, added per-tool total call counts, and embedded per-run failure details directly into `report.md`.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - fixed summary table separator row column mismatch that broke markdown rendering.
      - added `## Tool Call Totals` section (aggregated counts by tool type).
      - added `## Case Failure Details` section in `report.md`, sourced from run `results.jsonl`.
      - run execution and `report` regeneration now pass case-result payloads into report builder.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented single-file triage behavior in `report.md`.
    - `/Users/evren/code/asky/ARCHITECTURE.md`
      - updated eval artifact/report behavior notes.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates tool totals section and case-failure detail rendering.

- **Why**:
  - `report.md` needed to be directly useful without opening extra files.
  - malformed table delimiter prevented reliable markdown rendering in editors.

### Results JSONL Markdown Converter (Auto-Generated)
**Summary**: Added automatic markdown conversion for per-run `results.jsonl` artifacts to make failure triage easy in editors that do not render JSONL well.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - added JSONL reader and markdown converter for case results.
      - new per-run artifact: `artifacts/results.md`.
      - `run_evaluation_matrix` now writes `results.md` immediately after `results.jsonl`.
      - `regenerate_report` now also regenerates each run's `results.md` from stored JSONL.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - terminal run summary now prints per-run `results_markdown` path.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented `results.md` artifact and how to use it for fast failure analysis.
    - `/Users/evren/code/asky/ARCHITECTURE.md`
      - updated eval-flow artifact list and markdown-conversion note.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates markdown conversion content.
      - validates automatic write during matrix runs.
      - validates regeneration from existing JSONL during `report`.

- **Why**:
  - JSONL is hard to inspect interactively in VS Code.
  - A fail-focused markdown rendering shortens iteration time when adjusting prompts, tools, or expectations.

### Eval Tool-Call Argument Breakdown + Disabled-Tool Comparisons
**Summary**: Added per-run tool-call breakdowns (tool + arguments + count) to summaries/reports and surfaced disabled-tool profile settings so pass-rate impact can be compared directly.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/core/engine.py`
      - `tool_start` runtime event now includes raw `tool_arguments`.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - per-case results now record `tool_calls` (tool name + parsed args).
      - run summaries now include:
        - `disabled_tools`
        - `tool_call_counts`
        - `tool_call_breakdown` (tool+args signature counts).
      - markdown report now includes:
        - `Disabled Tools` summary column
        - `Tool Call Breakdown` section per run with arguments.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - run summary printout now includes disabled tools and per-tool call counts.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added explicit `disabled_tools` per-run usage example and breakdown interpretation.
    - `/Users/evren/code/asky/src/asky/core/AGENTS.md`
      - documented `tool_start` event payload extension.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates tool-call breakdown aggregation and report rendering.

- **Why**:
  - Needed visibility into exact tool argument patterns and tool-disable experiments to explain pass-rate changes and guide profile tuning.

### Eval Harness End-to-End Timing Instrumentation
**Summary**: Added detailed timing metrics across prepare/run pipeline stages so eval outputs expose where time is spent (ingestion, llm/tool windows, run/session wall time).

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - `prepare_dataset_snapshots` now records:
        - manifest-level timing totals (`prepare_total_ms`, downloaded/reused counts)
        - per-document prepare action + elapsed time.
      - per-case `results.jsonl` rows now include `timings_ms`:
        - `case_total_ms`, `source_prepare_ms`, `client_init_ms`, `run_turn_ms`
        - `llm_total_ms`, `tool_total_ms`, `local_ingestion_ms`, `shortlist_ms`
        - call counters for llm/tool/local_ingestion/shortlist.
      - run summaries now include:
        - `timing_totals_ms`
        - `timing_averages_ms`
        - `timing_counts`
        - `run_wall_ms` per run
      - session summary now includes `session_wall_ms` + `runs_wall_ms`.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - `prepare` prints timing totals and per-doc timing lines.
      - `run` prints per-run timing totals and session timing summary.
      - live progress now includes elapsed ms for external transition end events.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented timing fields, semantics, and interpretation guidance.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates timing aggregation and report headers.

- **Why**:
  - Needed visibility into ingestion/preload/orchestration/model/tool time to tune quality-vs-latency tradeoffs and detect bottlenecks.

### Eval Runner Live External-Invocation Progress
**Summary**: Added real-time progress output during eval execution, including before/after transitions for external invocation phases.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - `_evaluate_case` now emits case-scoped progress events for:
        - `run_turn` start/end/error
        - engine external transitions (`llm_start`, `llm_end`, `tool_start`, `tool_end`)
        - preload and summarizer status callbacks
      - `run_evaluation_matrix` forwards case progress events through the existing run progress callback.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - progress printer now renders external transition/status lines in addition to run/case start/end lines.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented live console progress behavior and event coverage.

- **Why**:
  - Long-running real-model eval cases previously looked idle; users needed explicit live feedback while waiting for network/model/tool phases.

### Eval Harness Role-Based Token Usage Metrics
**Summary**: Added model-role token usage reporting to research eval outputs so each run shows `main`, `summarizer`, and `audit_planner` input/output/total counts.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - records per-case `token_usage` in `results.jsonl` with role-level `input_tokens`, `output_tokens`, `total_tokens`.
      - aggregates run-level `token_usage_totals` in `summary.json`.
      - includes token usage columns in `report.md` (`in/out/total` per role).
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - prints role token totals per run in terminal output after execution.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates default zero token totals, aggregation math, and report token columns.
  - Updated docs:
    - `/Users/evren/code/asky/docs/research_eval.md`
    - `/Users/evren/code/asky/ARCHITECTURE.md`

- **Why**:
  - Makes model-quality vs token-cost comparisons explicit across matrix runs.
  - Gives visibility into token split between primary answer generation and summarization work.

### Notes
- `audit_planner` is a forward-compatible placeholder role in v1; counts remain zero until that stage is integrated.

### Research Eval Documentation Expansion
**Summary**: Rewrote the eval harness guide into an operator-focused manual covering dataset/matrix authoring, expectation tuning, and output interpretation.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added end-to-end workflow for creating new datasets and matrices
      - documented full dataset and matrix schema references
      - added expectation tuning guidance (`contains` vs `regex`)
      - added practical troubleshooting and interpretation guidance for summary/report/results
      - clarified path resolution, provider behavior, and rerun output directory behavior

- **Why**:
  - Existing documentation was too brief for creating and iterating new evaluations confidently.
  - Needed concrete examples for extending scenarios and tuning strictness without changing code.

### Research Runtime Warning Fixes (Tokenizer Length + Chroma Filter)
**Summary**: Eliminated two noisy/compatibility warnings observed in research eval runs by hardening embedding/chunker tokenization and Chroma metadata filter construction.

- **Changed**:
  - Updated:
    - `src/asky/research/vector_store_chunk_link_ops.py`
      - added strict-compatible Chroma metadata filter builder using `$and` for combined `cache_id` + `embedding_model` constraints.
      - applied it across chunk/link/hybrid Chroma query paths.
    - `src/asky/research/embeddings.py`
      - added pre-encode truncation path that caps embedding input texts to `max_seq_length`.
      - added tokenizer-compat encode/decode helpers and `verbose=False` in tokenizer token-count path.
    - `src/asky/research/chunker.py`
      - suppressed tokenizer length warning noise in token counting/encoding path via `verbose=False` compatible call pattern.
  - Added/updated tests:
    - `tests/test_research_vector_store.py`
      - validates Chroma query uses `$and` metadata filter.
    - `tests/test_research_embeddings.py`
      - validates over-length embedding input is truncated before model encode.
  - Updated package docs:
    - `src/asky/research/AGENTS.md`

- **Why**:
  - Research eval runs emitted:
    - tokenizer warning (`sequence length ... > 256`)
    - Chroma warning (`Expected where to have exactly one operator`)
  - Both were avoidable runtime noise and the Chroma filter warning forced unnecessary SQLite fallback.

### Eval Runtime DB Schema Initialization Fix
**Summary**: Fixed immediate per-case failures in eval runs caused by missing `sessions` table in isolated runtime databases.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/evaluator.py`
      - added `_initialize_runtime_storage()` and call it at the start of each isolated run (`run_evaluation_matrix`) before processing test cases.
  - Added regression test:
    - `tests/test_research_eval_evaluator.py`
      - verifies isolated runtime initialization creates the `sessions` table.

- **Why**:
  - Eval runs create isolated DB paths; without explicit schema init, `AskyClient.run_turn()` session resolution hit `OperationalError: no such table: sessions` and every case failed instantly.

### Eval Runner UX + Output Collision Safeguards
**Summary**: Improved eval-runner feedback for fast-failure runs and prevented same-second output directory reuse.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/evaluator.py`
      - output directory allocation now guarantees uniqueness (adds `_001`, `_002`, ...) when a timestamp directory already exists.
      - run summary now includes `error_cases` and `halted_cases`.
      - markdown report includes failed/error/halted columns.
    - `src/asky/evals/research_pipeline/run.py`
      - `run` command now prints per-run `passed/failed/errors/halted` counts from session summary.
      - prints a follow-up note when execution errors are present so users know to inspect `results.jsonl`.
  - Added tests:
    - `tests/test_research_eval_evaluator.py`
      - covers output directory collision suffixing and summary error/halt counting.
  - Updated docs:
    - `docs/research_eval.md`
      - documented unique output suffix behavior and terminal summary/error guidance.

- **Why**:
  - Fast execution failures previously looked like a silent early exit because only artifact paths were printed.
  - Same-second reruns could reuse one timestamp folder name, making reruns confusing.

### Eval Matrix Path Policy Refinement
**Summary**: Refined matrix path resolution rules so non-existent bare output paths do not get misinterpreted as matrix-relative.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/matrix.py`
      - `./` / `../` prefixes resolve relative to matrix file.
      - bare relative paths resolve from current working directory.
      - absolute paths unchanged.
  - Added test:
    - `tests/test_research_eval_matrix.py`
      - verifies `output_root = "temp/..."` resolves from cwd.
  - Updated docs:
    - `docs/research_eval.md` path-resolution section.

- **Why**:
  - Avoids duplicated path segments for output/snapshot roots when those directories do not already exist.

### Eval Matrix Dataset Path Resolution Fix
**Summary**: Fixed dataset path resolution in eval matrix loading so repo-root relative dataset paths no longer get incorrectly prefixed by the matrix directory.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/matrix.py`
      - relative matrix paths now resolve by preferring existing cwd-relative paths, then falling back to matrix-relative paths.
    - `evals/research_pipeline/matrices/default.toml`
      - switched dataset reference to matrix-relative form (`../datasets/...`) for portability.
  - Added regression test:
    - `tests/test_research_eval_matrix.py`
      - covers `dataset = "evals/research_pipeline/datasets/..."` with matrix file under `.../matrices`.
  - Updated docs:
    - `docs/research_eval.md`
      - clarified supported matrix path resolution behavior.

- **Why**:
  - Prevents `FileNotFoundError` caused by combining matrix directory + repo-root relative dataset path.

### Dual-Mode Research Eval Harness (Programmatic API, Manual Integration Runs)
**Summary**: Added a standalone evaluation harness around `AskyClient.run_turn(...)` to run real-model research/non-research integration checks with pinned datasets and model-parameter sweeps.

- **Changed**:
  - Added eval harness package:
    - `src/asky/evals/research_pipeline/run.py` (`prepare` / `run` / `report` commands)
    - `src/asky/evals/research_pipeline/dataset.py` (dataset parsing + validation, `doc_id`/`doc_ids` normalization)
    - `src/asky/evals/research_pipeline/matrix.py` (run-matrix parsing, source-provider resolution)
    - `src/asky/evals/research_pipeline/source_providers.py` (`local_snapshot`, `live_web`, `mock_web` placeholder)
    - `src/asky/evals/research_pipeline/runtime_isolation.py` (per-run DB/Chroma isolation + singleton reset)
    - `src/asky/evals/research_pipeline/assertions.py` (`contains` / `regex` assertions)
    - `src/asky/evals/research_pipeline/evaluator.py` (snapshot prep + run execution + result/report artifact writing)
  - Added seed evaluation data/config:
    - `evals/research_pipeline/datasets/rfc_http_nist_v1.yaml`
    - `evals/research_pipeline/matrices/default.toml`
  - Expanded API config surface for sweeps:
    - `src/asky/api/types.py` added `AskyConfig.model_parameters_override`
    - `src/asky/api/client.py` now deep-copies model config and merges overrides into effective LLM parameters.
  - Added docs:
    - `docs/research_eval.md`
    - updated `docs/library_usage.md`
    - updated `ARCHITECTURE.md`
    - updated `src/asky/api/AGENTS.md`
    - updated `tests/AGENTS.md`
  - Added tests:
    - `tests/test_research_eval_dataset.py`
    - `tests/test_research_eval_assertions.py`
    - `tests/test_research_eval_matrix.py`
    - `tests/test_research_eval_source_providers.py`
    - `tests/test_api_model_parameter_override.py`

- **Why**:
  - Enables repeatable manual evaluation of retrieval/orchestration quality across models and parameter sets.
  - Keeps the harness programmatic and future-ready for mocked/stubbed web-source testing without redesign.

- **Gotchas / Follow-ups**:
  - `mock_web` source provider is intentionally a placeholder in v1; stubbed network mode is deferred.
  - Live web runs can vary due to network/content drift; pinned local snapshots are recommended for stable baselines.

### Library Usage Documentation (API Config + Turn Request Options)
**Summary**: Added dedicated docs for programmatic `asky.api` usage, with explicit configuration/request field mapping and runnable examples.

- **Changed**:
  - Added:
    - `docs/library_usage.md`
      - `AskyConfig` option table (`model_alias`, `research_mode`, `disabled_tools`, etc.)
      - `AskyTurnRequest` option table (`continue_ids`, session fields, preload flags, persistence flag)
      - callback integration docs
      - `AskyTurnResult`/halt semantics
      - error handling (`ContextOverflowError`)
      - end-to-end examples (standard, research/lean, context continuation, sessions)
  - Updated:
    - `README.md` with a clear pointer to the library usage guide.

- **Why**:
  - Makes the new API-first orchestration discoverable and usable without reading source code.
  - Clarifies exactly how configuration and per-turn options should be passed.

- **Tests**:
  - Validation run:
    - `uv run pytest` (full suite)

### Full API Orchestration Migration (Context + Session + Shortlist)
**Summary**: Completed the migration of chat orchestration into `asky.api` so `AskyClient.run_turn()` now provides CLI-equivalent context/session/preload/model/persist flow.

- **Changed**:
  - Added API orchestration services:
    - `src/asky/api/context.py` (history selector parsing + context resolution)
    - `src/asky/api/session.py` (session create/resume/auto/research resolution)
    - `src/asky/api/preload.py` (local ingestion + shortlist preload pipeline)
  - Expanded API contract:
    - `src/asky/api/types.py`
      - added `AskyTurnRequest`, `AskyTurnResult`, and structured resolution payload types.
    - `src/asky/api/client.py`
      - added `run_turn(...)` as the full orchestration entrypoint,
      - integrated context/session/preload orchestration + persistence,
      - preserved callback hooks for CLI/web renderers.
  - Added API package docs:
    - `src/asky/api/AGENTS.md`
  - Refactored CLI into interface adapter:
    - `src/asky/cli/chat.py`
      - now maps argparse/UI callbacks to `AskyClient.run_turn(...)`,
      - keeps terminal rendering, html/email/push behaviors in CLI layer,
      - retains compatibility helper functions for existing tests/import paths.
  - Updated architecture/docs:
    - `ARCHITECTURE.md`
    - `src/asky/cli/AGENTS.md`

- **Tests**:
  - Extended API tests:
    - `tests/test_api_library.py` (new `run_turn` coverage)
  - Updated CLI integration expectation:
    - `tests/test_cli.py` (persistence assertions aligned with API-owned orchestration)
  - Validation runs:
    - `uv run pytest tests/test_cli.py tests/test_api_library.py`
    - `uv run pytest` → 422 passed

- **Why**:
  - Makes full chat orchestration callable as a stable programmatic API.
  - Keeps CLI as presentation/interaction layer over the same API workflow.

- **Gotchas / Follow-ups**:
  - `shortlist_flow.py` remains in `cli/` for now but orchestration path is API-owned.
  - Optional future cleanup: retire legacy helper wrappers in `cli/chat.py` once external imports no longer rely on them.

### Library API Slice + Non-Interactive Context Overflow Handling
**Summary**: Added a first-class programmatic API (`asky.api`) and removed interactive `input()` recovery from the core engine so library/web callers can control error handling safely.

- **Changed**:
  - Added new API package:
    - `src/asky/api/__init__.py`
    - `src/asky/api/types.py` (`AskyConfig`, `AskyChatResult`)
    - `src/asky/api/client.py` (`AskyClient` with message build + registry/engine orchestration)
    - `src/asky/api/exceptions.py` (public exception exports)
  - Added core exceptions module:
    - `src/asky/core/exceptions.py` (`AskyError`, `ContextOverflowError`)
  - Refactored core engine:
    - `src/asky/core/engine.py`
      - removed interactive 400 recovery (`input()` loop),
      - raises `ContextOverflowError` on HTTP 400 with compacted-message payload,
      - removed direct terminal rendering in engine fallback paths,
      - added optional structured `event_callback(name, payload)` hooks,
      - changed verbose tool callback payload to structured dicts.
  - Updated CLI orchestration:
    - `src/asky/cli/chat.py`
      - uses `AskyClient.run_messages(...)` for registry+engine execution,
      - adapts verbose dict payloads back into Rich panels for terminal UX,
      - handles `ContextOverflowError` with user-facing guidance.
  - Updated exports/docs:
    - `src/asky/core/__init__.py`
    - `ARCHITECTURE.md`
    - `src/asky/core/AGENTS.md`
    - `src/asky/cli/AGENTS.md`

- **Tests**:
  - Added `tests/test_api_library.py` for `AskyClient` behavior.
  - Updated `tests/test_context_overflow.py` to assert raised `ContextOverflowError` instead of interactive prompt flow.
  - Validation runs:
    - Pre-change baseline: `uv run pytest` → 416 passed
    - Post-change full suite: `uv run pytest` → 420 passed

- **Why**:
  - Separates core/business orchestration from terminal interaction.
  - Enables safe server/web embedding (no hidden stdin prompt paths).
  - Establishes a stable typed API surface for incremental CLI-to-library migration.

- **Gotchas / Follow-ups**:
  - CLI still owns post-answer delivery UI actions (mail/push/report) and shell-specific terminal context fetch.

### Pre-LLM Local Corpus Preload Stage + PyMuPDF Dependency
**Summary**: Added a deterministic local ingestion stage before first model call in research chat and added `pymupdf` as a project dependency.

- **Changed**:
  - Added new module:
    - `src/asky/cli/local_ingestion_flow.py`
      - extracts local targets from prompt text,
      - ingests/caches local sources via research adapter path,
      - indexes chunk embeddings before model/tool turns,
      - formats a compact preloaded-corpus context block.
  - Updated chat flow:
    - `src/asky/cli/chat.py`
      - runs local preload stage in research mode before shortlist stage,
      - merges local + shortlist contexts into one preloaded-source block.
  - Extended adapter helpers:
    - `src/asky/research/adapters.py`
      - added `extract_local_source_targets(...)` for deterministic prompt token extraction.
  - Added dependency:
    - `pyproject.toml` / `uv.lock`
      - `pymupdf==1.26.7` added via `uv add pymupdf`.

- **Tests**:
  - Added new tests:
    - `tests/test_local_ingestion_flow.py`
  - Extended existing tests:
    - `tests/test_cli.py`
    - `tests/test_research_adapters.py`
  - Validation run:
    - `uv run pytest` → 416 passed.

- **Why**:
  - Shifts more research orchestration into deterministic program flow (small-model-first goal).
  - Ensures local corpus material is indexed and available before model reasoning starts.

### Built-in Local Source Ingestion Fallback (Phase 3 Slice)
**Summary**: Added deterministic local-file ingestion fallback in research adapters so local corpus reads can flow through the existing cache/vector retrieval path without custom adapter tooling.

- **Changed**:
  - `src/asky/research/adapters.py`
    - Added built-in local target handling when no configured custom adapter matches.
    - Supported target forms: `local://...`, `file://...`, absolute/relative local paths.
    - Directory discover mode returns `local://` links for supported files (non-recursive in v1).
    - File read normalization added for text-like formats (`.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`).
    - PDF/EPUB read path added via optional PyMuPDF import with explicit dependency error when unavailable.
  - No changes required in research tool orchestration: existing adapter/cache/vector flow consumes this fallback directly.

- **Tests**:
  - `tests/test_research_adapters.py`
    - Added coverage for builtin local text-file reads.
    - Added coverage for builtin directory discovery link generation.
    - Added coverage for PDF dependency-missing error behavior.
  - Validation runs:
    - `uv run pytest tests/test_research_adapters.py tests/test_research_tools.py`
    - `uv run pytest` (full suite)

- **Why**:
  - Moves local research toward deterministic ingestion and away from model-driven browsing behavior.
  - Reuses the same downstream caching/chunking/indexing retrieval pipeline already used for web content.

### Research Mode Now Auto-Starts a Session
**Summary**: Enforced session-backed execution for research mode so session-scoped memory isolation is always effective.

- **Changed**:
  - Added research-session guard in chat flow:
    - `src/asky/cli/chat.py`
      - New `_ensure_research_session(...)` helper.
      - `run_chat()` now auto-creates a session in research mode when no active/resumed session exists.
  - Added tests:
    - `tests/test_cli.py`
      - session creation path when research starts without session
      - no-op path when session already exists
  - Updated docs:
    - `ARCHITECTURE.md`
    - `src/asky/cli/AGENTS.md`
    - `src/asky/research/AGENTS.md`

- **Why**:
  - Session-scoped research memory (`save_finding` / `query_research_memory`) depends on an active `session_id`.
  - Auto-starting research sessions removes a footgun where isolation could silently degrade.

### Session-Scoped Research Memory + Shortlist Budget Defaults
**Summary**: Implemented first research-pipeline slice to scope findings memory by active chat session and increased default pre-LLM shortlist budgets.

- **Changed**:
  - Threaded active session context from chat into research registry construction:
    - `src/asky/cli/chat.py`
    - `src/asky/core/engine.py`
    - `src/asky/core/tool_registry_factory.py`
  - Added session-aware handling in research memory tool executors:
    - `src/asky/research/tools.py`
      - `save_finding` now persists `session_id` when provided.
      - `query_research_memory` now queries semantic/fallback memory in optional session scope.
  - Extended vector-store finding operations for session-filtered retrieval paths:
    - `src/asky/research/vector_store.py`
    - `src/asky/research/vector_store_finding_ops.py`
  - Raised shortlist defaults for larger bounded corpus construction:
    - `src/asky/data/config/research.toml` (`search_result_count=40`, `max_candidates=40`, `max_fetch_urls=20`)
    - `src/asky/config/__init__.py` fallback defaults aligned to `40/40/20`.

- **Tests**:
  - Added/updated coverage:
    - `tests/test_tools.py` (research registry session-id injection behavior)
    - `tests/test_research_tools.py` (session propagation for save/query memory tools)
    - `tests/test_research_vector_store.py` (session-scoped finding search)
  - Validation runs:
    - Pre-change baseline: `uv run pytest` → 402 passed
    - Post-change full suite: `uv run pytest` → 406 passed

- **Why**:
  - Keeps research-memory writes/reads isolated by active session without relying on the model to manage scope.
  - Increases shortlist breadth while keeping fetch/index work bounded for deterministic pipeline stages.

### Documentation Sync for Session-Scoped Memory + Shortlist Budgets
**Summary**: Updated architecture/package docs to reflect new research-memory scoping behavior and shortlist defaults.

- **Updated**:
  - `ARCHITECTURE.md`
  - `src/asky/cli/AGENTS.md`
  - `src/asky/core/AGENTS.md`
  - `src/asky/research/AGENTS.md`
  - `src/asky/config/AGENTS.md`

### Research Pipeline Plan Revisions (Decisions Applied)
**Summary**: Updated the research pipeline planning artifact with concrete defaults and decisions from review discussion.

- **Updated**:
  - `TODO_research_pipeline.md` now locks `session_id` as run isolation key.
  - Local ingestion milestone scope now explicitly includes EPUB support through the PyMuPDF path.
  - Model-role plan now supports a single shared optional `analysis_model` for both planning and audit stages.
  - Web corpus defaults now set to `40` candidates and `20` fetched/indexed sources (configurable).

- **Why**:
  - Converts ambiguous planning choices into implementable defaults so the first build phase can proceed without re-litigating core assumptions.

- **Gotchas / Follow-ups**:
  - Two clarifications remain in TODO: `analysis_model` default enablement and initial local ingestion UX scope (explicit files only vs directory recursion in v1).

### Research Pipeline Revamp Planning Artifact
**Summary**: Added a dedicated multi-session TODO plan for a pipeline-driven, small-model-first research workflow redesign.

- **Added**:
  - New planning document: `TODO_research_pipeline.md`
  - Phased roadmap covering orchestration stages, local/web corpus unification, retrieval-first targeted summarization, model-role split (worker/planner/auditor), and rollout gates.

- **Why**:
  - Current research behavior depends too much on model initiative for tool use.
  - Goal is to move orchestration and data flow into deterministic program logic so smaller/local models produce more consistent results.

- **Gotchas / Follow-ups**:
  - Implementation intentionally not started yet; this entry tracks planning output only.
  - Open architecture decisions are listed in `TODO_research_pipeline.md` and need confirmation before coding starts.

### Tool Metadata Prompt Guidance + Runtime Tool Exclusion Flags
**Summary**: Added per-tool prompt-guideline metadata and runtime tool exclusion flags so enabled tools can shape system prompt behavior and selected tools can be disabled from CLI invocation.

- **Refactors / Features**:
  - Extended `ToolRegistry` to store optional `system_prompt_guideline` metadata and expose enabled-tool guideline lines in registration order.
  - Updated `ToolRegistry.get_schemas()` to emit API-safe function schemas (`name`, `description`, `parameters`) while keeping internal metadata out of tool payloads.
  - Added `disabled_tools` support to `create_default_tool_registry()` and `create_research_tool_registry()` (including built-in, research, custom, and push-data tools).
  - Added CLI flags `-off`, `-tool-off`, and `--tool-off` (repeatable and comma-separated values supported).
  - Updated chat flow to parse runtime tool exclusions, build the filtered registry, and append enabled-tool guideline bullets into the system prompt before LLM execution.
  - Added `system_prompt_guideline` fields to research tool schemas and built-in registry schemas; custom tools now support the same optional field from config.
  - Updated `ConversationEngine.run()` to disable tool-calling automatically when the registry has no enabled tools.

- **Tests**:
  - Extended `tests/test_cli.py` with parser and helper coverage for tool-off alias parsing, disabled-tool normalization, and system-prompt guideline block injection.
  - Extended `tests/test_tools.py` with coverage for API schema sanitization and registry filtering/guideline behavior.

- **Why**:
  - Makes tool behavior instructions composable and tied to enabled toolset rather than hardcoded prompt text.
  - Supports quick per-run tool toggling from command line without editing config.

- **Gotchas / Follow-ups**:
  - Tool names in `--tool-off` are exact string matches against registered names.
  - If all tools are disabled, the LLM call now runs tool-free automatically.

### Summarization Latency + Non-Streaming LLM Requests
**Summary**: Reduced hierarchical summarization call count and forced non-streaming mode for all LLM requests.

- **Refactors**:
  - Updated `src/asky/summarization.py` to use bounded `map + single final reduce` for long content instead of recursive pairwise merge rounds.
  - Added reduce-input sizing helpers so final reduce input stays within `SUMMARIZATION_INPUT_LIMIT`.
  - Updated `src/asky/core/api_client.py` so every LLM payload explicitly sets `stream = false`, even if model parameters include `stream`.

- **Tests**:
  - Extended `tests/test_summarization.py` with a regression test that verifies hierarchical mode now performs `N map calls + 1 final reduce call`.
  - Extended `tests/test_model_params.py` to verify streaming is always disabled in outbound LLM payloads.

- **Why**:
  - Hierarchical summarization was creating too many round trips on long inputs.
  - Streaming responses are not consumed in current CLI/chat flow, so enabling them adds overhead without product value.

### Gotchas / Follow-ups
- If a future UI path consumes token streams incrementally, `get_llm_msg()` will need an explicit opt-in streaming mode rather than global `stream=false`.

### Maintainability Refactor (Phase 1-2)
**Summary**: Reduced duplication around URL handling and lazy imports, and extracted pre-LLM shortlist orchestration from `chat.py` to a dedicated helper module.

- **New Modules**:
  - Added `src/asky/url_utils.py` for shared URL sanitization and normalization.
  - Added `src/asky/lazy_imports.py` for shared lazy import/call helpers.
  - Added `src/asky/cli/shortlist_flow.py` to run shortlist stage and banner updates outside `run_chat()`.

- **Refactors**:
  - Updated `retrieval.py`, `tools.py`, `research/tools.py`, and `research/source_shortlist.py` to reuse shared URL helpers.
  - Updated `core/engine.py` lazy tool and research binding imports to use shared lazy-import utilities.
  - Slimmed `cli/chat.py` by extracting shortlist execution orchestration while preserving existing public helper functions and test patch points.

- **Why**:
  - Removes repeated URL sanitization/normalization implementations.
  - Makes lazy-loading patterns consistent and easier to maintain.
  - Reduces `run_chat()` complexity and isolates shortlist-side effects (banner/status/verbose output) in one place.

- **Gotchas / Follow-ups**:
  - `source_shortlist.py`, `vector_store.py`, and `sqlite.py` remain large; deeper module splits are still pending.
  - Config constants are still flat in `config/__init__.py`; grouping into structured settings is a later phase.

### Maintainability Refactor (Phase 3)
**Summary**: Extracted tool registry construction out of `core/engine.py` into `core/tool_registry_factory.py`, while preserving backwards compatibility for test patch points and public APIs.

- **New Module**:
  - Added `src/asky/core/tool_registry_factory.py` to own `create_default_tool_registry()` and `create_research_tool_registry()`.

- **Refactors**:
  - Replaced large in-module registry builders in `core/engine.py` with thin delegating wrappers.
  - Kept `engine.py` compatibility symbols (`execute_get_url_content`, `execute_web_search`, etc.) so existing tests and patch targets continue to work.
  - Updated core architecture docs (`ARCHITECTURE.md`, `src/asky/core/AGENTS.md`) to reflect the new module boundary.

- **Why**:
  - Reduces `engine.py` scope to conversation orchestration and summary logic.
  - Isolates registry/tool assembly for easier future extraction (e.g., custom/push-data/research registration).

### Maintainability Refactor (Phase 4)
**Summary**: Split shortlist internals into focused modules while keeping `source_shortlist.py` as the stable public API surface.

- **New Modules**:
  - Added `src/asky/research/shortlist_types.py` for shared shortlist datatypes and callback aliases.
  - Added `src/asky/research/shortlist_collect.py` for candidate collection + seed-link expansion.
  - Added `src/asky/research/shortlist_score.py` for scoring, ranking heuristics, and query fallback resolution.

- **Refactors**:
  - `source_shortlist.py` now delegates collection and scoring to dedicated modules.
  - Kept existing imports/functions in `source_shortlist.py` so tests and callers remain unchanged.

- **Why**:
  - Reduces single-module cognitive load and makes pipeline stages independently maintainable.
  - Creates clearer boundaries for future changes (collection vs scoring).

### Maintainability Refactor (Phase 5)
**Summary**: Split heavy `VectorStore` internals into dedicated operation modules and kept `vector_store.py` focused on lifecycle + compatibility wrappers.

- **New Modules**:
  - Added `src/asky/research/vector_store_common.py` for shared vector math/constants.
  - Added `src/asky/research/vector_store_chunk_link_ops.py` for chunk/link embedding and retrieval operations.
  - Added `src/asky/research/vector_store_finding_ops.py` for findings-memory embedding/search operations.

- **Refactors**:
  - Rewrote `vector_store.py` to delegate heavy method bodies to ops modules.
  - Preserved existing `VectorStore` method names and behavior for compatibility with current tests/callers.

- **Why**:
  - Shrinks the core class file and isolates distinct operational concerns.
  - Makes future work on chunk/link retrieval independent from findings-memory logic.

## 2026-02-08

### Codebase Documentation Restructuring
**Summary**: Restructured documentation by creating package-level `AGENTS.md` files, slimming `ARCHITECTURE.md`, and generating a maintainability report.
- **New Files**: Created `AGENTS.md` in `cli`, `core`, `storage`, `research`, `config`, and `tests` directories.
- **Refactor**: Reduced `ARCHITECTURE.md` to a high-level overview (~220 lines).
- **Report**: Analyzed maintainability (file sizes, config sprawl, duplication, testing gaps).

### CLI & UX Improvements
**Argcomplete & Selectors**:
- Added `argcomplete`-backed shell completion with dynamic value hints.
- implemented word-based selector tokens for `--continue-chat`, `--print-session`, `--resume-session`, `--print-answer`, and `--session-from-message`.
- Renamed `--from-message` to `--session-from-message` (`-sfm`).
- Selectors now support "word-based" matching for easier recall.
- Added `--completion-script` for easy shell setup.

**Session Features**:
- **Message to Session**: `-sfm <ID>` promotes a history message to a new session.
- **Quick Reply**: `--reply` shortcut to continue from the last message (resuming session or converting if needed).

**Banner & Observability**:
- **Live Progress**: Banner now shows pre-LLM retrieval progress (shortlist stats) before the model call.
- **Stability**: Fixed banner redraw issues caused by embedding model load noise (loading bars, warnings).
- **Verbose Trace**: Added rich terminal tables for shortlist candidates and tool calls in `-v` mode.
- **Summarization**: Added live banner updates for hierarchical summarization progress.

### Performance & Startup
**Optimization**:
- **Lazy Imports**: Made core package exports lazy (`asky.cli`, `asky.core`, `asky.research`) to reduce startup time.
- **Startup Slimming**: Reordered `main()` to short-circuit fast commands (help, edit-model) before DB init.
- **Background Cleanup**: Moved research cache cleanup to a background thread to unblock startup.

**Guardrails**:
- Added `tests/test_startup_performance.py` to enforce latency (<0.2s median) and idle RSS memory usage limits.

### Research & Retrieval Enhancements
**Shared Pipeline**:
- Unified URL retrieval logic in `retrieval.py` for standard tools, research mode, and shortlist.
- Implemented **Hierarchical Summarization** (map-reduce) for long content.

**Source Shortlist**:
- **Shared Pipeline**: Added a pre-LLM shortlist pipeline (URL parsing, extraction, ranking) shared by research/chat modes.
- **Models**: Added per-model control (`source_shortlist_enabled` in config) and runtime override (`--lean`).
- **Seed-Link Expansion**: Added support for expanding links from seed URLs in the prompt.
- **Hardening**: Improved filtering of utility/auth links and canonical deduplication.
- **Debug**: Added extensive performance logging for the shortlist path.

**Embeddings**:
- **Cache-First**: Application now prefers local cache and only hits HuggingFace if needed.
- **Fallback**: Added auto-download of fallback model (`all-MiniLM-L6-v2`) if configured model fails.
- **Fixes**: Fixed tokenizer max-length warnings and added noise suppression during load.

### Reliability & Testing
**Fixes**:
- **Graceful Exit**: Refactored max-turns exit to use a tool-free system prompt swap, preventing hallucinated XML calls.
- **Tests**: Fixed slow CLI tests (mocking cleanup/logging), fixed import errors in prompt tests, and resolved various failures.
- **XML Support**: Added support for parsing XML-style tool calls.

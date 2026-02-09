# Research Eval Harness

This harness runs manual integration evaluations through the programmatic API (`AskyClient.run_turn`).

## What It Is For

- Primary use: evaluate research pipeline behavior and answer quality.
- Also supports non-research runs (`research_mode=false`) with the same dataset and scoring.
- Designed for manual benchmark/evaluation runs, not default unit-test flow.

## Core Concepts

- **Dataset**: documents + test cases + expected checks.
- **Matrix**: one or more run profiles (model + mode + params + knobs).
- **Snapshots**: pinned local copies of source docs for reproducibility.
- **Run Output**: per-case JSONL plus summary and markdown report.

## Directory Layout

- Dataset seed: `/Users/evren/code/asky/evals/research_pipeline/datasets/rfc_http_nist_v1.yaml`
- Matrix seed: `/Users/evren/code/asky/evals/research_pipeline/matrices/default.toml`
- Snapshot root (default): `/Users/evren/code/asky/temp/research_eval/snapshots`
- Run output root (default): `/Users/evren/code/asky/temp/research_eval/runs`

## Quick Start

```bash
# 1) Prepare pinned local documents
uv run python -m asky.evals.research_pipeline.run prepare \
  --dataset evals/research_pipeline/datasets/rfc_http_nist_v1.yaml

# 2) Execute all runs from a matrix
uv run python -m asky.evals.research_pipeline.run run \
  --matrix evals/research_pipeline/matrices/default.toml

# 3) Execute only selected run IDs
uv run python -m asky.evals.research_pipeline.run run \
  --matrix evals/research_pipeline/matrices/default.toml \
  --run research-glmflash-local

# 4) Rebuild report from existing outputs
uv run python -m asky.evals.research_pipeline.run report \
  --dataset evals/research_pipeline/datasets/rfc_http_nist_v1.yaml \
  --results-dir temp/research_eval/runs/<timestamp>
```

## How To Create Extra Evaluations

### 1) Create a dataset file

Add a new file under `/Users/evren/code/asky/evals/research_pipeline/datasets/`, for example:

```yaml
id: my_policy_eval_v1

docs:
  - id: policy-1
    title: "Policy A"
    url: "https://example.com/policy-a.pdf"
  - id: policy-2
    title: "Policy B"
    url: "https://example.com/policy-b.pdf"

tests:
  - id: policy-a-claim-1
    doc_id: policy-1
    query: "What is the minimum review interval?"
    expected:
      type: contains
      text: "at least every 90 days"

  - id: compare-a-b
    doc_ids: [policy-1, policy-2]
    query: "Which document requires annual external audit?"
    expected:
      type: regex
      pattern: "(?i)annual\\s+external\\s+audit"
```

Notes:
- `doc_id` and `doc_ids` are both supported.
- `doc_ids` enables multi-document questions in one test case.
- Supported expectation types right now: `contains`, `regex`.

### 2) Create a matrix file

Add a matrix under `/Users/evren/code/asky/evals/research_pipeline/matrices/`, for example:

```toml
dataset = "../datasets/my_policy_eval_v1.yaml"
snapshot_root = "temp/research_eval/snapshots"
output_root = "temp/research_eval/runs"

[[runs]]
id = "research-glmflash-local"
model_alias = "glmflash"
research_mode = true
source_provider = "local_snapshot"
lean = true
preload_local_sources = true
preload_shortlist = false
save_history = false

[runs.parameters]
temperature = 0.1

[[runs]]
id = "standard-gf-live"
model_alias = "gf"
research_mode = false
source_provider = "live_web"
lean = false
preload_local_sources = false
preload_shortlist = true
save_history = false
```

### 3) Prepare snapshots and run

```bash
uv run python -m asky.evals.research_pipeline.run prepare --dataset evals/research_pipeline/datasets/my_policy_eval_v1.yaml
uv run python -m asky.evals.research_pipeline.run run --matrix evals/research_pipeline/matrices/my_policy_eval_v1.toml
```

## Dataset Schema Reference

Top-level fields:
- `id`: optional string (defaults to filename stem)
- `docs`: required non-empty list
- `tests`: required non-empty list

`docs[]` fields:
- `id` (required, unique)
- `title` (required)
- `url` (required)

`tests[]` fields:
- `id` (required, unique)
- `query` (required)
- `doc_id` or `doc_ids` (required, references `docs.id`)
- `expected` (required)

`expected` fields:
- `type="contains"` with `text`
- `type="regex"` with `pattern`

## Matrix Schema Reference

Top-level fields:
- `dataset`: optional path (if omitted, pass `--dataset` at runtime)
- `snapshot_root`: optional path
- `output_root`: optional path
- `[[runs]]`: required, at least one

`runs[]` fields:
- `id` (required, unique)
- `model_alias` (required)
- `research_mode` (default `true`)
- `source_provider` (`auto`, `local_snapshot`, `live_web`, `mock_web`)
- `lean` (default `false`)
- `preload_local_sources` (default `true`)
- `preload_shortlist` (default `true`)
- `save_history` (default `false`)
- `disabled_tools` (string CSV or string list)
- `additional_source_context` (optional string)
- `query_prefix` / `query_suffix` (optional strings)
- `[runs.parameters]` (optional key/value model parameters)

Disable tools per run:
- `disabled_tools` accepts CSV string or string list.
- Example:

```toml
[[runs]]
id = "research-gf-no-web-search"
model_alias = "gf"
research_mode = true
source_provider = "local_snapshot"
disabled_tools = ["web_search", "get_url_content"]
```

This is useful for A/B comparisons of pass rate, latency, and tool-mix impact.

Provider behavior:
- `source_provider="auto"`:
  - research mode -> `local_snapshot`
  - standard mode -> `live_web`
- `mock_web` is a placeholder for future stubbed-network mode (not yet implemented).

## Path Resolution Rules

Matrix paths (`dataset`, `snapshot_root`, `output_root`) resolve as:
- `./...` or `../...`: relative to matrix file location.
- other relative paths (for example `temp/...`, `evals/...`): relative to current working directory.
- absolute paths: used directly.

## How To Tune Expectations

### Use `contains` when wording is stable

Best for normative phrases you want exactly:

```yaml
expected:
  type: contains
  text: "no more than 30 days"
```

Guidelines:
- Keep target substring short but specific.
- Avoid punctuation/capitalization-sensitive long phrases unless needed.
- If the model often paraphrases, prefer `regex`.

### Use `regex` when wording/order may vary

```yaml
expected:
  type: regex
  pattern: "(?i)\\bhead\\b.*\\boptions\\b.*\\btrace\\b"
```

Guidelines:
- Use `(?i)` for case-insensitive matches.
- Prefer robust patterns over exact long sentence matching.
- Keep pattern focused on required facts.

### Typical tuning workflow

1. Run matrix.
2. Inspect failed cases in `results.jsonl`.
3. Compare `expected` vs actual `answer` content.
4. Adjust expectation strictness (shorter `contains` or better `regex`).
5. Re-run only target profile with `--run`.

## Reading Outputs

Per-run artifacts:
- `<output>/<run_id>/artifacts/results.jsonl`
- `<output>/<run_id>/artifacts/results.md`
- `<output>/<run_id>/artifacts/summary.json`

Session artifacts:
- `<output>/summary.json`
- `<output>/report.md`

Meaning of key summary fields:
- `passed_cases` / `failed_cases`: assertion outcomes.
- `error_cases`: execution errors (infra/runtime), not answer-quality misses.
- `halted_cases`: run-turn halted before normal answer completion.
- `avg_elapsed_ms`: average latency per case.
- `token_usage_totals`: role-based token totals:
  - `main`: primary model calls for `run_turn`.
  - `summarizer`: summarization model calls.
  - `audit_planner`: reserved for future pipeline stage (currently `0/0/0` unless implemented).
- `timing_totals_ms`: per-run timing totals including:
  - `run_wall_ms`, `case_total_ms`, `source_prepare_ms`, `client_init_ms`, `run_turn_ms`
  - `llm_total_ms`, `tool_total_ms`, `local_ingestion_ms`, `shortlist_ms`
- `timing_averages_ms`: per-case averages for timing metrics.
- `timing_counts`: call counts for `llm`, `tool`, `local_ingestion`, `shortlist`.
- `disabled_tools`: tools disabled for this run profile.
- `tool_call_counts`: aggregate counts by tool name.
- `tool_call_breakdown`: aggregate counts by tool name + argument payload.

Per-case `results.jsonl` rows also include `token_usage` with the same roles and
`input_tokens` / `output_tokens` / `total_tokens`.
Per-case rows also include `timings_ms` for detailed phase timing breakdown.
Per-case rows also include `tool_calls` (tool name + parsed arguments).

`results.md` is an automatic markdown conversion of `results.jsonl` with:
- case summary table (`PASS`/`FAIL`/`ERROR`/`HALTED`)
- fail-focused detail sections including query, expected assertion payload, answer text,
  and captured tool calls with arguments.

`report.md` now also includes:
- per-run tool call totals by tool type
- per-run case failure details (query/expected/answer/tool calls)

This gives a single top-level markdown file for most analysis, while keeping
`results.md` as per-run drill-down.

## Troubleshooting

### "No runs selected for execution"

Cause: `--run` filter did not match any `[[runs]].id` (or run is commented out in matrix).

### Fast completion with many failures

Check `error` field in `results.jsonl`.
If `error_cases > 0`, failures are runtime/integration errors, not model-quality misses.
`artifacts/results.md` usually gives the quickest failure triage view.

### Understanding live console progress

`run` now prints live progress for:
- run lifecycle (`run_start`, `run_end`)
- case lifecycle (`case_start`, `case_end`)
- external invocation transitions (`run_turn`, `llm`, `tool` start/end)
- preload/summarizer status messages when callbacks emit updates

This means long waits should still show heartbeat-style lines while each case executes.
`run_end` now includes `run_wall_ms`, and per-run summary lines include timing totals.

### Understanding token usage numbers

Each role reports `input/output/total` token counts:
- `main`: request/response tokens consumed by the selected run model alias.
- `summarizer`: tokens consumed by the configured summarization model.
- `audit_planner`: currently a placeholder counter for future planner/audit stages.

You can compare these fields across runs to evaluate quality/cost tradeoffs when
changing model aliases or `[runs.parameters]`.

### Understanding timing fields

Key timing metrics:
- `source_prepare_ms`: source-provider query construction and query-affix assembly.
- `client_init_ms`: `AskyClient` creation overhead.
- `run_turn_ms`: total orchestration/model/tool duration for one case.
- `llm_total_ms`: sum of measured LLM request windows (`llm_start` -> `llm_end`).
- `tool_total_ms`: sum of measured tool dispatch windows (`tool_start` -> `tool_end`).
- `local_ingestion_ms`: timed local corpus preload execution.
- `shortlist_ms`: timed shortlist preload execution.
- `run_wall_ms`: total wall clock per run profile.
- `session_wall_ms` (session summary): total wall clock for the whole matrix execution.

## Tool Breakdown In Report

`report.md` now includes:
- Summary table column `Disabled Tools`
- A dedicated `Tool Call Breakdown` section per run
  - tool name
  - number of calls
  - normalized argument payload

Use this to verify how tool usage patterns changed between run profiles and how that
affects pass/fail outcomes.

### Snapshot missing

Run `prepare` first for datasets that use `local_snapshot` provider.

### Output directory confusion on reruns

Runs now create unique timestamp dirs; if same-second collision occurs, suffixes are appended (`_001`, `_002`, ...).

## Advanced Notes

- Runs are isolated with per-run DB/Chroma runtime dirs to avoid cross-run contamination.
- Model parameter sweeps are supported via `[runs.parameters]` and merged into `AskyConfig.model_parameters_override`.
- Non-research runs (`research_mode=false`) can still be evaluated against the same test dataset.

# API Package (`asky/api/`)

Programmatic library surface for full asky orchestration without CLI coupling.

## Module Overview

| Module | Purpose |
|--------|---------|
| `client.py` | `AskyClient` orchestration entrypoint |
| `types.py` | Typed request/result dataclasses |
| `context.py` | History selector parsing and context loading |
| `session.py` | Session lifecycle resolution (create/resume/auto/research) |
| `preload.py` | Local-ingestion + shortlist preload pipeline |
| `exceptions.py` | Public error exports |

## Primary Entry Point

Use `AskyClient.run_turn(request)` for CLI-equivalent orchestration:

1. Resolve history context (`context.py`)
2. Resolve session state (`session.py`)
3. Run pre-LLM preload pipeline (`preload.py`)
4. Build messages (with local-target query redaction + optional local-KB system hint) and execute `ConversationEngine`
5. Generate summaries and persist session/history turns

Research mode is resolved per turn from effective session state:

- `resolve_session_for_turn()` now returns effective research profile
  (`research_mode`, `research_source_mode`, `research_local_corpus_paths`).
- `AskyClient.run_turn()` uses that resolved profile for prompt/tool/preload branching,
  even when `AskyConfig.research_mode=False` (for resumed research sessions).
- `AskyClient.run_messages(...)` now forwards `research_source_mode` into research
  registry construction so local-only section tools (`list_sections`,
  `summarize_section`) are exposed only for local-capable modes.
- `AskyTurnRequest.shortlist_override` (`auto|on|off`) controls shortlist policy for
  that turn with precedence below lean mode and above model/global settings.
- Explicit local-only/mixed research runs fail fast when zero local documents ingest.

## Preload Notes

- In standard mode, URL-bearing prompts now preload seed URL page content into
  the first model request context.
- In research mode with preloaded corpus, `run_turn()` performs one deterministic
  retrieval bootstrap (`execute_get_relevant_content`) before first model call,
  then appends those evidence snippets into preloaded user context.
- Seed URL preload uses a combined 80% main-model context budget and labels each
  seed block as `full_content`, `summarized_due_budget`,
  `summary_truncated_due_budget`, or `fetch_error`.
- When seed URL blocks are complete (`full_content` within budget and no fetch
  errors), message assembly now switches to a strict direct-answer instruction:
  use preloaded seed content directly and avoid refetching the same URL via
  `get_url_content`/`get_url_details` unless freshness or completeness is
  explicitly required.
- In the same condition (standard mode + complete seed preload), run-turn policy
  also disables `web_search`, `get_url_content`, and `get_url_details` for that
  turn to guarantee direct-answer behavior without extra retrieval loops.
- Shortlist-ranked links/snippets are still included after seed URL content.
- Preload metadata now carries `preloaded_source_urls` and
  `preloaded_source_handles` so tool registry/runtime can inject safe corpus
  identifiers for retrieval tools when models omit explicit URL lists.
- When effective source mode is `local_only` or `mixed`, message assembly adds
  local section-tool guidance so model flow can use `list_sections` then
  `summarize_section` for section-bounded queries.
- Section-scoped retrieval now supports explicit `section_ref` /
  `section_id` and compatibility legacy `corpus://cache/<id>/<section-id>`
  source tokens, with canonical section promotion handled in research tools.

## Runtime Boundary

- `asky.api` does not render terminal UI.
- Callers pass optional callbacks for status/events/display integration.
- Shell-sticky session lock behavior is injected via optional callbacks, so API
  callers can opt in/out of CLI lock-file semantics.
- `AskyConfig.double_verbose` enables full main-model request/response payload
  emissions (`llm_request_messages`, `llm_response_message`) through the
  configured verbose output callback.
- Verbose mode also propagates structured transport metadata events from LLM and
  tool/summarization HTTP paths (`transport_request`, `transport_response`, `transport_error`).
- During full turn orchestration, verbose mode emits a structured
  `preload_provenance` event before the first model call, summarizing which seed
  and shortlist sources were preloaded into model-visible context.
- `AskyConfig.model_parameters_override` can override/extend configured model
  generation parameters for a specific client instance (for evaluation sweeps).

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

## Preload Notes

- In standard mode, URL-bearing prompts now preload seed URL page content into
  the first model request context.
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

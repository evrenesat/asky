# asky Library Usage Guide

This guide covers programmatic usage of `asky` as a Python library.

## Quick Start

```python
from asky.api import AskyClient, AskyConfig, AskyTurnRequest

client = AskyClient(
    AskyConfig(
        model_alias="gf",        # required
        research_mode=True,      # optional
        summarize=False,         # optional
        verbose=False,           # optional
        open_browser=False,      # optional
        disabled_tools=set(),    # optional
        model_parameters_override={},  # optional per-client generation overrides
    )
)

result = client.run_turn(
    AskyTurnRequest(
        query_text="Compare FastAPI and Flask for a production API",
    )
)

print(result.final_answer)
```

## Public API Surface

Import from:

```python
from asky.api import (
    AskyClient,
    AskyConfig,
    AskyTurnRequest,
    AskyTurnResult,
    AskyChatResult,
    ContextOverflowError,
)
```

## Configuration (`AskyConfig`)

`AskyConfig` configures the client instance itself (model/mode/tool behavior).

| Field                       | Type             | Required | Default | Description                                                         |
| --------------------------- | ---------------- | -------- | ------- | ------------------------------------------------------------------- |
| `model_alias`               | `str`            | yes      | -       | Must exist in configured `MODELS` (for example `gf`).               |
| `summarize`                 | `bool`           | no       | `False` | Passed into core tool dispatch/summarization behavior.              |
| `verbose`                   | `bool`           | no       | `False` | Enables verbose tool tracing payloads/callback behavior.            |
| `open_browser`              | `bool`           | no       | `False` | Allows engine/browser rendering path for final answer.              |
| `research_mode`             | `bool`           | no       | `False` | Explicitly requests research mode for turns from this client. Effective mode can still come from resumed session profile. |
| `disabled_tools`            | `set[str]`       | no       | `set()` | Runtime tool exclusion by exact tool name.                          |
| `model_parameters_override` | `dict[str, Any]` | no       | `{}`    | Merged over configured model `parameters` for this client instance. |
| `system_prompt_override`    | `str \| None`    | no       | `None`  | Override the default system prompt.                                 |

Example:

```python
cfg = AskyConfig(
    model_alias="gf",
    research_mode=True,
    disabled_tools={"web_search"},
)
client = AskyClient(cfg)
```

## Request Options (`AskyTurnRequest`)

`AskyTurnRequest` controls one full orchestrated turn.

| Field                       | Type          | Required | Default | Description                                                   |
| --------------------------- | ------------- | -------- | ------- | ------------------------------------------------------------- |
| `query_text`                | `str`         | yes      | -       | User query text.                                              |
| `continue_ids`              | `str \| None` | no       | `None`  | History selector string, e.g. `"1,2"` or `"~1"`.              |
| `summarize_context`         | `bool`        | no       | `False` | If `True`, loads summarized context instead of full.          |
| `sticky_session_name`       | `str \| None` | no       | `None`  | Create and attach to a new named session.                     |
| `resume_session_term`       | `str \| None` | no       | `None`  | Resume by ID/name/partial-name.                               |
| `shell_session_id`          | `int \| None` | no       | `None`  | Optional pre-resolved shell session id for auto-resume logic. |
| `lean`                      | `bool`        | no       | `False` | Disables shortlist via policy resolution (`lean` mode).       |
| `preload_local_sources`     | `bool`        | no       | `True`  | Run local-source ingestion preload stage.                     |
| `preload_shortlist`         | `bool`        | no       | `True`  | Run shortlist preload stage.                                  |
| `additional_source_context` | `str \| None` | no       | `None`  | Extra corpus context appended to preload context.             |
| `save_history`              | `bool`        | no       | `True`  | Persist turn (session/global history) after completion.       |
| `research_flag_provided`    | `bool`        | no       | `False` | Marks this turn as an explicit `-r`-style request.            |
| `research_source_mode`      | `str \| None` | no       | `None`  | Optional source intent: `web_only`, `local_only`, `mixed`.   |
| `replace_research_corpus`   | `bool`        | no       | `False` | Replace persisted session corpus pointers for this turn.      |
| `shortlist_override`        | `str \| None` | no       | `None`  | Per-turn shortlist override: `auto`, `on`, or `off`.         |

Example:

```python
request = AskyTurnRequest(
    query_text="Continue this thread with latest updates",
    continue_ids="~1",
    summarize_context=True,
    resume_session_term="project alpha",
    shortlist_override="auto",
    save_history=True,
)
result = client.run_turn(request)
```

## Result Objects

### `AskyTurnResult`

Returned by `run_turn()`. Includes:

- `final_answer`, `query_summary`, `answer_summary`
- `messages` (final message list sent through engine)
- `session_id`
- `halted`, `halt_reason` (for command-style session operations or ambiguous resumes)
- `notices` (user-facing status strings)
- `context` (`ContextResolution`)
- `session` (`SessionResolution`)
- `preload` (`PreloadResolution`)

`SessionResolution` includes effective session-owned research profile values:

- `research_mode`
- `research_source_mode`
- `research_local_corpus_paths`

### Halt behavior

`run_turn()` may return `halted=True` with empty `final_answer`, for example:

- session create command without a query turn
- ambiguous resume search (multiple session matches)
- no matching session

Always check:

```python
if result.halted:
    print(result.halt_reason, result.notices)
```

### Preload metadata for research reliability

`result.preload` now includes:

- `preloaded_source_urls`: resolved preloaded source identifiers used for retrieval
- `preloaded_source_handles`: safe-handle mapping for local corpus sources

In research mode with preloaded corpus, `AskyClient.run_turn()` also performs one
deterministic bootstrap retrieval and appends the resulting evidence snippets into
the first model-visible user message context.

### Local section tools in research mode

Research registry now includes local section tools:

- `list_sections`
- `summarize_section`

Exposure depends on effective `research_source_mode`:

- `web_only`: section tools are hidden.
- `local_only`: section tools are enabled.
- `mixed`: section tools are enabled, but executors require local corpus handles
  (`corpus://cache/<id>`) and reject web URLs.

Section-reference contract for tool calls:

- Preferred format: `corpus://cache/<id>#section=<section-id>` (`section_ref`).
- Explicit `section_id` is also supported.
- Compatibility mode accepts legacy `corpus://cache/<id>/<section-id>` sources for
  retrieval/full-content flows.
- `list_sections` defaults to canonical body sections and includes `section_ref` in
  each row. Use `include_toc=true` only when TOC/debug rows are needed.

## Minimal vs Full APIs

### `run_turn()` (recommended)

Runs complete orchestration:

1. context resolution
2. session resolution
3. preload pipeline (local + shortlist)
4. message build + model/tool loop
5. summaries + persistence

### `chat()` and `run_messages()`

Use these lower-level calls when you already manage orchestration yourself.

## Callbacks

`run_turn()` supports callbacks to integrate with custom UIs:

- `display_callback`
- `verbose_output_callback`
- `summarization_status_callback`
- `event_callback`
- `preload_status_callback`
- `messages_prepared_callback`

Example:

```python
def on_event(name: str, payload: dict) -> None:
    print(name, payload)

result = client.run_turn(
    AskyTurnRequest(query_text="status"),
    event_callback=on_event,
)
```

## Shell Session Integration (optional)

For CLI-like shell-sticky behavior, pass:

- `set_shell_session_id_fn`
- `clear_shell_session_fn`

If you are building a web/backend service, usually omit these and manage session ids explicitly.

## Error Handling

Handle overflow explicitly:

```python
from asky.api import ContextOverflowError

try:
    result = client.run_turn(AskyTurnRequest(query_text="very large prompt..."))
except ContextOverflowError as exc:
    print("Context overflow:", exc)
    # exc.compacted_messages contains compacted fallback context
```

## End-to-End Examples

### 1. Standard chat turn

```python
client = AskyClient(AskyConfig(model_alias="gf"))
result = client.run_turn(AskyTurnRequest(query_text="Summarize Redis vs Memcached"))
print(result.final_answer)
```

### 2. Research mode turn with shortlist disabled

```python
client = AskyClient(
    AskyConfig(
        model_alias="gf",
        research_mode=True,
    )
)
result = client.run_turn(
    AskyTurnRequest(
        query_text="Analyze latest rust async ecosystem trends",
        lean=True,                  # disables shortlist stage
        preload_local_sources=True,
    )
)
print(result.preload.shortlist_enabled)  # False
```

### 3. Continue from existing history context

```python
client = AskyClient(AskyConfig(model_alias="gf"))
result = client.run_turn(
    AskyTurnRequest(
        query_text="Expand this with implementation plan",
        continue_ids="12,13",
        summarize_context=False,
    )
)
print(result.context.resolved_ids)  # [12, 13]
```

### 4. Session-oriented flow

```python
client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))

# Create/attach session
create_result = client.run_turn(
    AskyTurnRequest(
        query_text="",                      # command-style create only
        sticky_session_name="my_research",
    )
)

# Resume by name and run query
resume_result = client.run_turn(
    AskyTurnRequest(
        query_text="continue with benchmarking section",
        resume_session_term="my_research",
    )
)
print(resume_result.session_id)
```

## Notes

- `model_alias` must match configured models in your asky configuration.
- Tool disable names are exact string matches.
- `run_turn(save_history=False)` lets you use asky as a stateless inference step.
- On resumed sessions, effective research mode/profile is derived from persisted session metadata when no explicit override is supplied.

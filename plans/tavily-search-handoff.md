# Tavily Search Integration Handoff Plan

## Summary

Integrate the Tavily Search API (`https://api.tavily.com/search`) as a supported search provider in `asky`, alongside the existing `searxng` and `serper` providers. We must use the `requests` library exclusively (no Tavily Python client) and introduce a `TAVILY_API_KEY` configuration option. The implementation must map properties required by Tavily and return standard asky search result structured data.

## Done Means

- Setting `SEARCH_PROVIDER = "tavily"` and exporting `TAVILY_API_KEY` successfully triggers a web search through Tavily API.
- Search queries emit proper `transport_request`, `transport_response`, and `transport_error` telemetry events using the `trace_callback`.
- Tests for `execute_web_search` and `_execute_tavily_search` are implemented and passing cleanly.

## Critical Invariants

- The implementation MUST NOT introduce any new dependencies (e.g., `# no tavily-python`).
- The standard timeout parameter (`SEARCH_TIMEOUT`) must be honored on all requests.
- The system must not silently swallow `TAVILY_API_KEY` missing errors; it must return a clear JSON error payload akin to Serper functionality.
- The user agent must remain consistent with existing API calls if standard `asky` headers are used.
- Output must use the AskY search result schema: `{"results": [{"title": "...", "url": "...", "snippet": "...", "engine": "tavily"}]}`.

## Forbidden Implementations

- Do not use the `tavily-python` client library. Use only `requests.post`.
- Do not forget to truncate the snippet using `[:SEARCH_SNIPPET_MAX_CHARS]`.
- Do not return empty results without checking API status codes. Raise or format errors properly.
- Do not hardcode the API key—always read from the specific environment variable derived from config.

## Checkpoints

### [ ] Checkpoint 1: Config and Telemetry Additions

**Goal:**

- Expose the necessary configuration settings `TAVILY_API_URL` and `TAVILY_API_KEY_ENV`.

**Context Bootstrapping:**

- Run these commands before editing:
- `cat src/asky/config/__init__.py | grep -i serper`
- `cat src/asky/tools.py | grep -A 5 _execute_serper`

**Scope & Blast Radius:**

- May create/modify: `src/asky/config/__init__.py`
- Must not touch: Database or core retrieval routing.
- Constraints: Maintain existing config dict structure.

**Steps:**

- [ ] Step 1: In `src/asky/config/__init__.py`, under `# General`, add `TAVILY_API_URL` and `TAVILY_API_KEY_ENV` properties mirroring `SERPER_API_URL` with defaults `"https://api.tavily.com/search"` and `"TAVILY_API_KEY"` respectively. Add reading from `_gen.get(...)`.

**Dependencies:**

- None.

**Verification:**

- Run scoped tests: `uv run python -c "from asky.config import TAVILY_API_URL, TAVILY_API_KEY_ENV; print(TAVILY_API_URL)"`
- Run non-regression tests: `uv run pytest tests/asky/config -q`

**Done When:**

- Verification commands pass cleanly.
- The new config variables are fully importable.
- A git commit is created with message: `feat(config): add Tavily API URL and key environment config constants`

**Stop and Escalate If:**

- There's a cyclic import issue when importing into config.

### [ ] Checkpoint 2: Core Provider Implementation

**Goal:**

- Implement `_execute_tavily_search` in `tools.py` and hook it into `execute_web_search`.

**Context Bootstrapping:**

- Run these commands before editing:
- `grep -n "execute_web_search" src/asky/tools.py`

**Scope & Blast Radius:**

- May create/modify: `src/asky/tools.py`
- Must not touch: `searxng` and `serper` function bodies.
- Constraints: You must use `requests.post`, mapping results properly, returning standard `results` dict.

**Steps:**

- [ ] Step 1: Import `TAVILY_API_URL` and `TAVILY_API_KEY_ENV` inside `src/asky/tools.py`.
- [ ] Step 2: Implement `_execute_tavily_search(q: str, count: int, trace_callback: Optional[TraceCallback] = None) -> Dict[str, Any]`.
  - Read key from `os.environ.get(TAVILY_API_KEY_ENV)`. If missing, return error analogous to Serper.
  - Dispatch `transport_request` event.
  - Perform POST `requests.post(TAVILY_API_URL, json={"query": q, "max_results": count, "include_answer": False}, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=SEARCH_TIMEOUT)`
  - Form response schema handling title, url, snippet/content. (Map `result["content"]` to `snippet` after standard `strip_tags` and `[:SEARCH_SNIPPET_MAX_CHARS]`).
  - Dispatch `transport_response` and `transport_error` on exception.
- [ ] Step 3: Modify `execute_web_search` to route `"tavily"` to `_execute_tavily_search`.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `TAVILY_API_KEY=fake uv run python -c "from asky.tools import execute_web_search; import asky.config; asky.config.SEARCH_PROVIDER='tavily'; print(execute_web_search({'q':'test', 'count': 1}))" || true`

**Done When:**

- Function logic matches standard Serper layout exactly but accesses Tavily.
- Tool properly returns `{"results": [...]}` format.
- A git commit is created with message: `feat(tools): implement Tavily search provider via requests`

**Stop and Escalate If:**

- Config variables are not exposed properly preventing tools execution.

### [ ] Checkpoint 3: Test Coverage

**Goal:**

- Implement unit tests for `_execute_tavily_search` mimicking Serper tests.

**Context Bootstrapping:**

- Run these commands before editing:
- `grep -A 10 "test_execute_serper_search_success" tests/asky/test_tools.py`

**Scope & Blast Radius:**

- May create/modify: `tests/asky/test_tools.py`
- Must not touch: Other tests.

**Steps:**

- [ ] Step 1: Add `test_execute_tavily_search_success` patching `requests.post` and returning dummy Tavily results format mapping `{"results": [{"title": "X", "url": "Y", "content": "Z"}]}`.
- [ ] Step 2: Add `test_execute_web_search_dispatch_tavily` asserting execution routes correctly when config says `tavily`.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/test_tools.py -k tavily -v`
- Run non-regression tests: `uv run pytest tests/asky -q`

**Done When:**

- Existing and new tests pass perfectly.
- A git commit is created with message: `test(tools): add coverage for Tavily search provider`

**Stop and Escalate If:**

- Pytest discovers incompatible fixtures.

## Behavioral Acceptance Tests

- Given `TAVILY_API_KEY` is exported and `SEARCH_PROVIDER='tavily'` in config, calling `asky` with a web search query retrieves and formats snippets successfully without throwing API schema errors.
- Given the `TAVILY_API_KEY` is completely missing but `SEARCH_PROVIDER='tavily'`, a graceful JSON `{"error": "Tavily API key not found..."}` block is returned preventing an ugly crash.

## Plan-to-Verification Matrix

| Requirement                         | Verification Method                         |
| ----------------------------------- | ------------------------------------------- |
| Config defaults created             | Checkpoint 1: Python import check           |
| No `tavily-python` dep              | Review `src/asky/tools.py` imports          |
| Telemetry structure parity          | Same event emitter hooks used as Serper     |
| Request format honors `max_results` | Code review and patched unit test assertion |
| Unit Tests implementation           | Checkpoint 3: `pytest -k tavily` execution  |

## Assumptions And Defaults

- Tavily snippet payload key is `content` based on standard API documentation structure.
- We do not use their advanced features (`include_images`, `include_raw_content`), setting standard baseline logic only to maintain parity with SearXNG/Serper `count` outputs.

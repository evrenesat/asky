# Low Severity Issues

These issues are minor and primarily affect code quality, style, or minor redundancies.

## 1. Redundant Loop Check

**File:** `src/asky/api/client.py`

**Issue:**
```python
            if rendered >= (
                RESEARCH_BOOTSTRAP_MAX_SOURCES
                * RESEARCH_BOOTSTRAP_MAX_CHUNKS_PER_SOURCE
            ):
                break
```
The inner loop already breaks if `rendered` exceeds the chunk limit *per source*. The outer loop also breaks if `rendered` exceeds the *total* limit. While safe, the logic for limiting the total number of chunks is slightly duplicated between `execute_get_relevant_content` (which takes `max_chunks` per source) and this formatting logic.

**Recommendation:**
- Rely on `execute_get_relevant_content` to enforce chunk limits, or simplify the loop to just iterate over whatever `execute_get_relevant_content` returns.

## 2. Inconsistent Naming Style

**Files:** `src/asky/config/loader.py` vs `src/asky/core/engine.py`

**Issue:**
`tomllib.load` is used in `config/loader.py`, which is modern Python standard library. However, `engine.py` uses `json.loads` for tool arguments parsing. While correct, unifying on a configuration format standard (TOML vs JSON) across the project (config vs payloads) is good, but understandable given JSON is standard for LLM tool calls. The inconsistency is minor but noticeable when switching contexts.

**Recommendation:**
- Ensure all *user-facing* configuration (files) is consistently TOML, while *machine-facing* data (API payloads) remains JSON. (This seems to be the current state, so just a note to maintain).

## 3. Redundant Import Aliases

**File:** `src/asky/cli/chat.py`

**Issue:**
```python
from asky.api.preload import (
    build_shortlist_stats as api_build_shortlist_stats,
    combine_preloaded_source_context as api_combine_preloaded_source_context,
    shortlist_enabled_for_request as api_shortlist_enabled_for_request,
)
```
The aliases `api_*` are used but the original names are descriptive enough and unlikely to conflict if imported directly.

**Recommendation:**
- Remove the `as api_*` aliases unless specifically needed for disambiguation.

## 4. Minor Redundancy in `ConversationEngine.run`

**File:** `src/asky/core/engine.py`

**Issue:**
The `ContextOverflowError` handling logic:
```python
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.error(f"API Error 400: {e}")
                self._handle_400_error(e, messages)
```
`_handle_400_error` calls `check_and_compact` again. However, `check_and_compact` was likely already called at the start of the turn loop. If compaction failed (phase 2), calling it again here won't fix anything unless the context window size has changed or messages were modified externally (unlikely).

**Recommendation:**
- Instead of re-running compaction, `_handle_400_error` should probably just raise `ContextOverflowError` directly with the *already compacted* messages from the loop iteration, or attempt a *more aggressive* compaction strategy (e.g., dropping the last user message entirely as a last resort).

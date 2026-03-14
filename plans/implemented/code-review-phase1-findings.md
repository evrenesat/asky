# Phase 1 Findings — Core Query Execution & Tool Loop

## Audit Summary

All code paths were traced from CLI entry through `chat.py` → `api/client.py` → `core/engine.py` → `core/registry.py`. Hooks, lean mode, max-turns, verbose tracing, seed URL preload, and ContextOverflowError were verified against documentation claims.

**Overall verdict: The core query path is solid.** One documentation bug found, one test coverage gap, and a few minor items.

---

## Findings

### F1. ARCHITECTURE.md lists POST_TURN_RENDER as "deferred" — it is fully implemented
**Priority:** P2 (doc mismatch)
**Verdict:** Fix Now

**Location:** [ARCHITECTURE.md:736](ARCHITECTURE.md#L736)

**What it says:**
> Deferred hooks (`CONFIG_LOADED`, `POST_TURN_RENDER`, `SESSION_END`) remain unimplemented in v1.

**What the code does:**
- `POST_TURN_RENDER` is fully implemented and actively fired in `cli/chat.py:1039`
- It is handled by `email_sender/plugin.py` and `push_data/plugin.py`
- `hook_types.py:48-51` correctly lists only `CONFIG_LOADED` and `SESSION_END` as deferred (not `POST_TURN_RENDER`)
- The code and `DEFERRED_HOOK_NAMES` set are correct — only the prose in ARCHITECTURE.md is stale

**Fix:** Update ARCHITECTURE.md line 736 to remove `POST_TURN_RENDER` from the deferred list.

---

### F2. No test for lean-mode memory recall suppression
**Priority:** P3 (missing test)
**Verdict:** Fix Now

**Location:** `tests/test_lean_mode.py` + `src/asky/api/preload.py:454`

**What is tested:**
- Lean mode disables all tools (CLI layer) ✅
- Lean mode suppresses system prompt updates (engine layer) ✅
- Lean mode propagates to engine and registry (API layer) ✅
- Lean mode POST_TURN_RENDER answer_title regression ✅

**What is NOT tested:**
- That `run_preload_pipeline()` with `lean=True` skips `recall_memories()` call
- The guard is at `preload.py:454`: `if USER_MEMORY_ENABLED and not lean:`
- This is the **only** place memory recall is guarded by lean — if it regresses, lean mode would inject memory context into the system prompt despite claiming it doesn't

**Fix:** Add a test to `test_lean_mode.py` that mocks `recall_memories` and verifies it is NOT called when `lean=True`.

---

### F3. All hooks fire at documented locations and with documented payloads ✅
**Priority:** —
**Verdict:** No action needed

Verified:
| Hook | Fired at | Payload matches `hook_types.py` |
|------|----------|--------------------------------|
| `SESSION_RESOLVED` | `client.py:604` | ✅ |
| `PRE_PRELOAD` | `client.py:717` | ✅ |
| `POST_PRELOAD` | `client.py:776` | ✅ |
| `SYSTEM_PROMPT_EXTEND` | `client.py:894` | ✅ |
| `TOOL_REGISTRY_BUILD` | `tool_registry_factory.py:345,574` (standard + research) | ✅ |
| `PRE_LLM_CALL` | `engine.py:168` | ✅ |
| `POST_LLM_RESPONSE` | `engine.py:254` | ✅ |
| `PRE_TOOL_EXECUTE` | `registry.py:98` | ✅ |
| `POST_TOOL_EXECUTE` | `registry.py:145` | ✅ |
| `TURN_COMPLETED` | `client.py:555` (once per turn, not per tool) | ✅ |
| `POST_TURN_RENDER` | `chat.py:1039` (after final answer, only if answer exists) | ✅ |

---

### F4. Max-turns enforcement produces graceful exit, not crash ✅
**Priority:** —
**Verdict:** No action needed

- `engine.py` loop: `while turn < self.max_turns`
- When limit hit without final answer: `_execute_graceful_exit()` fires a tool-free LLM call
- This produces a final answer rather than raising an exception
- Test coverage exists in `test_max_turns_duplication.py` and `test_llm.py`

---

### F5. ContextOverflowError properly raised and caught ✅
**Priority:** —
**Verdict:** No action needed

- Defined in `core/exceptions.py:8-37` with `compacted_messages` fallback
- Raised in `engine.py:789-804` on HTTP 400 errors
- Caught in `cli/chat.py:1052-1056` with user-friendly message
- Test coverage exists in `test_context_overflow.py`

---

### F6. Lean mode bypasses are comprehensive ✅
**Priority:** —
**Verdict:** No action needed (except F2's test gap)

Verified lean mode suppresses:
1. **All tools** — `chat.py:581-587` disables all via `get_all_available_tool_names()`
2. **Shortlist** — `preload.py` lean guard skips shortlist pipeline
3. **Memory recall** — `preload.py:454` guarded by `not lean`
4. **Memory extraction** — `client.py:960` skips auto-extraction
5. **System status updates** — `engine.py:142-145` suppresses context usage warnings
6. **Live banner** — `chat.py:759` suppresses live banner in lean mode
7. **POST_TURN_RENDER** — still fires (correct — email/push-data should still work in lean mode)

---

### F7. Verbose tracing correctly separates main-model vs tool/summarization payloads ✅
**Priority:** —
**Verdict:** No action needed

- `-v` enables tool/summarization transport metadata traces
- `-vv` additionally enables full main-model request/response payload boxes
- `engine.py` methods `_emit_main_model_request_messages()` and `_emit_main_model_response_message()` guard on `self.double_verbose`
- Tool and summarization traces use `self.config.verbose` (not `double_verbose`)
- Verbose output router in `cli/verbose_output.py` handles routing correctly

---

### F8. Seed URL preload and direct-answer mode work as documented ✅
**Priority:** —
**Verdict:** No action needed

- `preload.py:395-419` determines if seed content is full and within budget
- `client.py:204-228` resolves disabled tools: adds `web_search`, `get_url_content`, `get_url_details` to disabled set
- `client.py:156-162` adds direct-answer instruction to system prompt
- Guards: research mode → never direct-answer; lean mode → handled separately; errors in seed docs → never direct-answer
- Test coverage exists in `test_api_preload.py`, `test_cli.py`, `test_api_library.py`

---

## Action Items

| # | Finding | Action | File |
|---|---------|--------|------|
| 1 | F1: ARCHITECTURE.md lists POST_TURN_RENDER as deferred | Remove from deferred list in prose | `ARCHITECTURE.md:736` |
| 2 | F2: No test for lean-mode memory recall suppression | Add test | `tests/test_lean_mode.py` |

# RALF Plan: Plain-Query Helper Notice Post-Answer Fix

## Summary
Finish the helper-notice fix by correcting the actual CLI integration path instead of only the renderer’s behavior for fabricated `AskyTurnResult` fixtures.

Remaining problem:
- Helper notices are appended to `notices` in `AskyClient.run_turn()`.
- `run_chat()` passes `initial_notice_callback`, so those notices are printed immediately and then cleared before `turn_result.notices` is built.
- The green renderer in `cli/chat.py` only sees post-answer `turn_result.notices`, so the promised `New memory: ...`, `Updated memory: ...`, and `Your prompt enriched: ...` post-answer UX is still unreachable in the real flow.

## Done Means
1. Helper notices are not consumed by `initial_notice_callback`.
2. After a real `run_chat() -> AskyClient.run_turn()` execution, helper notices survive into the post-answer rendering loop.
3. CLI prints helper notices in bold green after the final answer and not before it.
4. Tests cover the real integration path, not only a hand-constructed `AskyTurnResult`.

## Critical Invariants
1. Non-helper operational notices may keep their current `initial_notice_callback` behavior.
2. Helper notices must still remain available in `PreloadResolution.interface_notices` for non-CLI consumers.
3. The fix must not duplicate helper notices before and after the answer.
4. The fix must not regress error-notice handling for session lookup failures.

## Forbidden Implementations
1. Do not solve this only by changing the test fixture.
2. Do not remove helper notices from structured preload metadata.
3. Do not route all notices around `initial_notice_callback`; only helper notices should change.
4. Do not weaken the green post-answer rendering rule into generic bracketed notices.

## Checkpoints

### [x] Checkpoint 1: Separate Helper Notices From Early Notice Delivery

**Goal:**
- Ensure helper notices bypass the early `initial_notice_callback` path and survive to post-answer rendering.

**Context Bootstrapping:**
- Run these commands before editing:
- `nl -ba src/asky/api/client.py | sed -n '717,825p'`
- `nl -ba src/asky/cli/chat.py | sed -n '903,972p'`
- `rg -n "initial_notice_callback|interface_notices|Your prompt enriched:|New memory:|Updated memory:" src/asky`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/client.py`, `src/asky/cli/chat.py`
- Must not touch: config loading, memory validation, helper prompt contract
- Constraints: keep existing non-helper notice behavior unchanged

**Steps:**
- [ ] Split helper notices from generic `notices` inside `AskyClient.run_turn()`.
- [ ] Prevent helper notices from being emitted through `initial_notice_callback`.
- [ ] Append helper notices back onto the final `AskyTurnResult.notices` only after the early-notice phase is complete.
- [ ] Keep `preload.interface_notices` populated for metadata consumers.

**Dependencies:**
- Depends on none.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/cli/test_plain_query_helper_notices.py -q`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_cli.py -q`

**Done When:**
- Verification commands pass cleanly.
- Helper notices no longer print before the answer in the real CLI flow.
- A git commit is created with message: `Fix post-answer helper notice routing`

**Stop and Escalate If:**
- Existing CLI behavior depends on helper notices being emitted before preload.

### [x] Checkpoint 2: Replace Fixture-Only Coverage With Real Integration Coverage

**Goal:**
- Cover the actual `run_chat -> AskyClient.run_turn` notice lifecycle so the regression cannot recur.

**Context Bootstrapping:**
- Run these commands before editing:
- `sed -n '1,240p' tests/asky/cli/test_plain_query_helper_notices.py`
- `sed -n '240,420p' tests/asky/api/test_api_library.py`
- `rg -n "run_chat\\(|initial_notice_callback|turn_result.notices" tests/asky`

**Scope & Blast Radius:**
- May create/modify: `tests/asky/cli/test_plain_query_helper_notices.py`, `tests/asky/api/test_api_library.py`, `devlog/DEVLOG.md`
- Must not touch: docs unrelated to CLI notice timing
- Constraints: assert ordering and visibility in the real path, not only static rendering

**Steps:**
- [ ] Replace the current fixture-only CLI notice test with one that exercises the real callback/clear/render sequence.
- [ ] Add an API-level regression test showing helper notices are preserved into the final result object even when `initial_notice_callback` is provided.
- [ ] Update DEVLOG with a short follow-up note describing the integration correction.

**Dependencies:**
- Depends on Checkpoint 1.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/cli/test_plain_query_helper_notices.py tests/asky/api/test_api_library.py -q`
- Run non-regression tests: `time uv run pytest -q`

**Done When:**
- Verification commands pass cleanly.
- The tests fail against the pre-fix implementation and pass with the fix.
- A git commit is created with message: `Add integration coverage for helper notices`

**Stop and Escalate If:**
- The CLI architecture cannot preserve helper notices post-answer without broader notice-type refactoring.

## Behavioral Acceptance Tests
1. Given a real helper memory save in CLI, `New memory: ... MemID#...` appears in bold green after the final answer.
2. Given prompt enrichment in CLI, `Your prompt enriched: ...` appears in bold green after the final answer.
3. Given a normal non-helper notice, its current rendering behavior stays unchanged.
4. Given `initial_notice_callback` is present, helper notices are still present in the final result notice list.

## Plan-to-Verification Matrix
| Requirement | Verification |
| --- | --- |
| Helper notices skip early callback consumption | `uv run pytest tests/asky/api/test_api_library.py -q` |
| Helper notices render after the answer in CLI | `uv run pytest tests/asky/cli/test_plain_query_helper_notices.py -q` |
| Non-helper notices keep current behavior | `uv run pytest tests/asky/cli/test_cli.py -q` |
| Full suite remains green | `time uv run pytest -q` |

## Assumptions And Defaults
1. The remaining bug is limited to notice timing and coverage; the activation and memory-validation fixes are otherwise acceptable.
2. No new config keys or CLI flags are needed.
3. This plan intentionally does not reopen the broader plain-query helper design.

# RALF Plan: Plain-Query Helper Follow-Up Fixes

## Summary
Bring the shipped plain-query interface helper back into alignment with the approved handoff by fixing four regressions:

1. `general.interface_model=""` must disable the helper instead of silently falling back to `default_model`.
2. The helper must not run side effects in `lean` mode or ignore explicit caller tool disables.
3. Automatic memory saves must be validated and forced to global scope before calling `execute_save_memory()`.
4. Helper notices promised by the feature (`New memory: ...`, `Updated memory: ...`, `Your prompt enriched: ...`) must actually reach the user in the approved post-answer green rendering path.

Public/runtime contract to preserve after the fix:
- `plain_query_interface_enabled` still defaults to `true`, but it is inert unless `general.interface_model` is explicitly configured to a non-empty valid alias.
- `plain_query_prompt_enrichment_enabled` stays separately gated and default-off.
- `PreloadResolution.interface_*` metadata stays available to library callers.
- No new CLI flags or config keys are introduced in this fix handoff.

## Done Means
1. With `general.interface_model=""`, standard turns behave exactly as they did before this feature: no helper LLM call, no prompt enrichment, no automatic memory save.
2. With `lean=True`, the helper does not run prompt enrichment or automatic memory save, and it does not influence shortlist/tool policy.
3. If `save_memory` is disabled by the caller, helper memory actions are skipped.
4. Helper memory actions are sanitized to `{memory, tags, session_id=None}` and cannot inject session-scoped writes or extra executor arguments.
5. Prompt-enrichment and helper-memory notices are emitted after the final answer in CLI green formatting and remain exposed in structured preload metadata for non-CLI consumers.
6. New tests cover the regression cases above, and the full suite passes.

## Critical Invariants
1. Empty `general.interface_model` remains an explicit off switch.
2. `lean=True` is a hard bypass for the plain-query helper.
3. Caller-disabled tools remain hard constraints, including `save_memory`.
4. Helper memory writes are always global and pre-LLM.
5. Prompt enrichment remains append-only and must not be shown to the user before the final answer unless explicitly rendered as a live banner status update.
6. The fix handoff does not expand helper scope beyond standard turns.
7. Docs must match actual runtime behavior after the fix, especially around optional activation and notice visibility.

## Forbidden Implementations
1. Do not keep `INTERFACE_MODEL = ... or DEFAULT_MODEL` behavior for the empty-string case.
2. Do not rely on prompt wording alone to enforce global-only memory writes.
3. Do not keep helper notices trapped only in `PreloadResolution.interface_notices` while CLI rendering reads `turn_result.notices`.
4. Do not special-case the fix in docs while leaving runtime behavior unchanged.
5. Do not add a new helper flag or a new planner alias to paper over the regressions.

## Checkpoints

### [x] Checkpoint 1: Restore Optional Activation And Explicit-Constraint Bypass

**Goal:**
- Make helper activation and bypass semantics match the approved contract.

**Context Bootstrapping:**
- Run these commands before editing:
- `nl -ba src/asky/config/__init__.py | sed -n '40,70p'`
- `nl -ba src/asky/api/client.py | sed -n '660,780p'`
- `rg -n "INTERFACE_MODEL =|plain_query_interface_enabled|request\.lean|disabled_tools" src/asky/config src/asky/api tests/asky`

**Scope & Blast Radius:**
- May create/modify: `src/asky/config/__init__.py`, `src/asky/api/client.py`, `tests/asky/config/test_config.py`, `tests/asky/api/test_api_library.py`
- Must not touch: docs, CLI rendering, memory executor code
- Constraints: preserve the `default_model` robustness fix; only restore empty-string disable semantics for `interface_model`

**Steps:**
- [x] Split `DEFAULT_MODEL` robustness from `INTERFACE_MODEL` resolution so an empty `interface_model` stays empty.
- [x] Gate the helper behind `not request.lean`.
- [x] Skip helper memory writes when `save_memory` is already disabled by the caller.
- [x] Add tests proving helper inactivity for empty `interface_model`, `lean=True`, and `disabled_tools={"save_memory"}`.

**Dependencies:**
- Depends on none.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/config/test_config.py tests/asky/api/test_api_library.py -q`
- Run non-regression tests: `uv run pytest tests/asky/api/test_interface_query_policy.py -q`

**Done When:**
- Verification commands pass cleanly.
- Empty `interface_model` no longer activates the helper implicitly.
- A git commit is created with message: `Fix plain-query helper activation gates`

**Stop and Escalate If:**
- Another subsystem now depends on empty `interface_model` falling back to `default_model`.

### [x] Checkpoint 2: Harden Helper Memory Action Validation

**Goal:**
- Prevent helper memory actions from writing anything except one sanitized global memory update.

**Context Bootstrapping:**
- Run these commands before editing:
- `nl -ba src/asky/api/interface_query_policy.py | sed -n '90,130p'`
- `nl -ba src/asky/api/client.py | sed -n '700,730p'`
- `nl -ba src/asky/memory/tools.py | sed -n '40,90p'`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/interface_query_policy.py`, `src/asky/api/client.py`, `tests/asky/api/test_interface_query_policy.py`, `tests/asky/memory/test_user_memory.py`
- Must not touch: `src/asky/memory/store.py`, `src/asky/memory/vector_ops.py`
- Constraints: keep the one-memory-action contract; do not add new storage behavior

**Steps:**
- [x] Validate `memory_action` shape in the policy layer:
- [x] Require `scope == "global"`.
- [x] Require non-empty string `memory`.
- [x] Normalize `tags` to a list of non-empty strings.
- [x] Discard any extra keys from the helper payload.
- [x] In `client.py`, call `execute_save_memory()` with a sanitized dict that explicitly sets `session_id=None`.
- [x] Add regression tests proving a payload with `session_id` or invalid `scope` cannot create session-scoped saves.

**Dependencies:**
- Depends on Checkpoint 1.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/api/test_interface_query_policy.py tests/asky/memory/test_user_memory.py -q`
- Run non-regression tests: `rg -n "session_id=None|scope == \"global\"|memory_action" src/asky/api tests/asky`

**Done When:**
- Verification commands pass cleanly.
- Helper memory saves are forced global even if the model returns extra fields.
- A git commit is created with message: `Harden helper memory action validation`

**Stop and Escalate If:**
- Existing callers depend on passing arbitrary extra fields through helper memory payloads.

### [x] Checkpoint 3: Fix Notice Delivery, Docs, And Regression Coverage

**Goal:**
- Make helper notices visible in the promised CLI path and align docs/tests with the corrected behavior.

**Context Bootstrapping:**
- Run these commands before editing:
- `nl -ba src/asky/api/client.py | sed -n '752,800p'`
- `nl -ba src/asky/cli/chat.py | sed -n '940,975p'`
- `sed -n '1,220p' docs/configuration.md`
- `sed -n '1,220p' docs/elephant_mode.md`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/client.py`, `src/asky/cli/chat.py`, `tests/asky/cli/test_cli.py`, `tests/asky/api/test_api_library.py`, `docs/configuration.md`, `docs/library_usage.md`, `docs/elephant_mode.md`, `docs/xmpp_daemon.md`, `ARCHITECTURE.md`, `devlog/DEVLOG.md`
- Must not touch: root `AGENTS.md`
- Constraints: keep structured preload metadata; fix CLI rendering instead of removing notices from metadata

**Steps:**
- [x] Ensure helper notices survive to the post-answer CLI rendering path.
- [x] Keep live banner status optional, but make post-answer green notice delivery deterministic.
- [x] Add CLI tests for:
- [x] prompt enrichment notice shown in green after the answer
- [x] memory save/update notice shown in green after the answer
- [x] no false notice when helper is bypassed
- [x] Correct docs so they state:
- [x] `interface_model` must be explicitly configured for helper activation
- [x] automatic helper memory saves are global-only
- [x] helper notices are visible in CLI after the answer
- [x] Add a DEVLOG follow-up entry describing the fix.
- [x] Run the full suite and compare runtime against the current baseline.

**Dependencies:**
- Depends on Checkpoint 2.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/cli/test_cli.py tests/asky/api/test_api_library.py -q`
- Run non-regression tests: `time uv run pytest -q`
- Run doc consistency checks:
- `rg -n "interface_model must be configured|global-only|after the answer|green" docs ARCHITECTURE.md devlog/DEVLOG.md`

**Done When:**
- Verification commands pass cleanly.
- CLI users can actually see the promised helper notices in the approved rendering path.
- Docs no longer overstate activation semantics.
- A git commit is created with message: `Fix helper notice delivery and docs`

**Stop and Escalate If:**
- The existing CLI flow cannot surface post-answer helper notices without broader display refactoring.

## Behavioral Acceptance Tests
1. Given `interface_model=""`, a standard query performs no helper call and produces no helper metadata side effects.
2. Given `lean=True`, a standard query performs no prompt enrichment and no automatic memory save.
3. Given `disabled_tools={"save_memory"}`, a helper memory suggestion is ignored and no global memory is written.
4. Given a helper payload with `{"scope":"global","memory":"...", "session_id":123}`, the saved memory is still global and does not attach to session `123`.
5. Given prompt enrichment on a normal standard turn, the user sees `Your prompt enriched: ...` in green after the answer.
6. Given a successful helper memory save, the user sees `New memory: ... MemID#...` or `Updated memory: ... MemID#...` in green after the answer.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Empty `interface_model` disables helper | `uv run pytest tests/asky/config/test_config.py tests/asky/api/test_api_library.py -q` |
| Lean bypass holds | `uv run pytest tests/asky/api/test_api_library.py -q` |
| Disabled `save_memory` blocks helper save | `uv run pytest tests/asky/api/test_api_library.py tests/asky/memory/test_user_memory.py -q` |
| Helper saves are forced global | `uv run pytest tests/asky/api/test_interface_query_policy.py tests/asky/memory/test_user_memory.py -q` |
| CLI notices are visible post-answer | `uv run pytest tests/asky/cli/test_cli.py -q` |
| Docs reflect optional activation and notice behavior | `rg -n "interface_model.*configured|after the answer|global-only" docs ARCHITECTURE.md devlog/DEVLOG.md` |

## Assumptions And Defaults
1. The follow-up keeps the same feature surface; it only removes unintended behavior and finishes the promised UX.
2. No new config keys or CLI flags are needed.
3. `PreloadResolution.interface_*` metadata remains the stable place for non-CLI consumers to inspect helper behavior.
4. The existing `plans/Plain-Query-Interface-Helper.md` remains the original implementation handoff; this file is the corrective follow-up.

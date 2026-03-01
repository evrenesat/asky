### Implicit Research Cleanup on Session Deletion

## Summary
Implement implicit `clean-research` behavior for **all** session deletion paths, so deleting a session also deletes that session’s research findings/vectors and clears session upload-link metadata before the session row/messages are removed. Then update docs/help text to reflect this new behavior.

Decisions locked from your input:
- Cleanup scope: **match current `clean-research` behavior**.
- Apply to delete modes: **all session deletes** (single, range/list, and `--all`, including remote command path via shared delete flow).

## Definition of Done
When any session is deleted (single selector, multiple selectors, or `--all`):
1. Session messages and session rows are deleted (existing behavior).
2. Session-scoped research findings/embeddings are deleted first.
3. `session_uploaded_documents` links for that session are deleted.
4. CLI/help/docs clearly state this behavior.
5. Tests cover the implicit cleanup path and pass.

## Public Interface / Behavior Changes
- `delete_sessions(...)` behavior changes from:
  - “delete session rows/messages only”
  - to:
  - “delete session rows/messages **plus implicit research cleanup** (findings/vectors + session upload links).”
- `session delete` command help text updated to document implicit research cleanup.
- `session clean-research` remains available as a standalone cleanup command.

## Files to Modify
1. `/Users/evren/code/asky/src/asky/storage/sqlite.py`
2. `/Users/evren/code/asky/src/asky/storage/AGENTS.md`
3. `/Users/evren/code/asky/src/asky/cli/main.py`
4. `/Users/evren/code/asky/src/asky/cli/AGENTS.md`
5. `/Users/evren/code/asky/ARCHITECTURE.md`
6. `/Users/evren/code/asky/DEVLOG.md`
7. `/Users/evren/code/asky/tests/test_storage.py`
8. `/Users/evren/code/asky/tests/test_cli.py`
9. `/Users/evren/code/asky/tests/test_integration.py` (only if needed for wording/behavior assertions)

## Before/After by Area

### 1) Storage delete flow
- Before:
  - `SQLiteHistoryRepository.delete_sessions()` deletes `messages` and `sessions` only.
- After:
  - It computes target session IDs as today.
  - For each target session ID, it runs implicit research cleanup equivalent to:
    - `VectorStore.delete_findings_by_session(str(session_id))`
    - delete rows from `session_uploaded_documents` for that session
  - Then deletes `messages` and `sessions` as today.
  - Return value remains count of deleted session rows (no API break).

### 2) CLI/help docs
- Before:
  - `session delete` help text says “Delete sessions and their messages.”
- After:
  - Help text explicitly says deletion also performs implicit research cleanup.
  - AGENTS/ARCHITECTURE reflect that `session delete` now subsumes session cleanup behavior for deleted sessions.

### 3) Tests
- Before:
  - Deletion tests verify session/message cascade only.
- After:
  - Add coverage that `delete_sessions(...)` calls research cleanup logic for deleted session IDs.
  - Keep existing deletion assertions intact.

## Sequential Atomic Steps

1. **Refactor storage deletion logic for cleanup hook**
   - In `sqlite.py`, add an internal helper for “cleanup research state for session IDs”.
   - Use session IDs resolved by existing delete selector logic.
   - Step dependency: none.

2. **Integrate cleanup into `delete_sessions`**
   - Invoke helper before deleting session rows/messages.
   - Ensure no behavior change for invalid selector handling and return shape.
   - Step dependency: Step 1.

3. **Update CLI/help strings**
   - Update user-facing `session delete` descriptions in `main.py`.
   - Keep `clean-research` command documented as explicit standalone operation.
   - Step dependency: Step 2.

4. **Update architecture/package docs**
   - Reflect new invariant: deleting sessions includes implicit research cleanup for those sessions.
   - Keep TTL/global cache notes accurate (shared cache still TTL-managed).
   - Step dependency: Step 2.

5. **Add/update tests**
   - `tests/test_storage.py`: add unit test asserting implicit research cleanup path is invoked for targeted sessions.
   - `tests/test_cli.py`: adjust expectation text/help where needed.
   - `tests/test_integration.py`: only update if behavior messaging/assertions changed.
   - Step dependency: Steps 2–4.

6. **Verification**
   - Run targeted tests for changed areas.
   - Run full suite.
   - Step dependency: Step 5.

## Constraints (What Not To Do)
- Do not add new dependencies.
- Do not change `delete_sessions` function signature/return type.
- Do not introduce global hard deletes of `research_cache`, `content_chunks`, `link_embeddings`, or uploaded artifact files.
- Do not auto-run `clean-research` for non-deleted sessions.
- Do not alter selector semantics (`id`, `id-id`, `id,id`, `--all`).

## Edge Cases to Handle
- Session has no findings/upload links: cleanup should be no-op and deletion still succeeds.
- Multiple session deletion (`id,id` / `id-id`) and `--all`: cleanup runs per deleted session ID.
- Invalid selectors: existing error behavior unchanged.
- Empty match (no sessions selected): no cleanup calls and return `0`.
- Mixed state where findings exist but no messages (or vice versa): all applicable records still cleaned.

## Verification Commands

### Targeted
1. `uv run pytest tests/test_storage.py -q`
2. `uv run pytest tests/test_cli.py -q`
3. `uv run pytest tests/test_integration.py -q`
4. `uv run pytest tests/test_session_research_cleanup.py -q`

### Final
1. `uv run pytest`

## Final Checklist
- [ ] Session deletion triggers implicit research cleanup for all delete selectors.
- [ ] Return values and selector parsing behavior unchanged.
- [ ] CLI/help text updated to reflect new behavior.
- [ ] Architecture/AGENTS docs updated consistently.
- [ ] DEVLOG entry added.
- [ ] Full test suite passes.

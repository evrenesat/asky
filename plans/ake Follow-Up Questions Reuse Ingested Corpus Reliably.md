# Plan: Make Follow-Up Questions Reuse Ingested Corpus Reliably (Without Workflow Regressions)

## Brief Summary
Your repro is valid, and current behavior is inconsistent with user expectation.

Observed facts from the codebase and local DB:
1. Both example turns were in the same session (`session_id=3`), so this is not a session-mismatch issue.
2. Session `3` is `research_mode=1`, `research_source_mode='local_only'`, with persisted corpus path `["/Users/evren/Books/test/bio/2025.11.07.687135v2.full.pdf"]`.
3. The first follow-up still answered with “no prior research memory,” which means the model path did not reliably ground on preloaded corpus content.

Likely root cause:
1. `PreloadResolution.is_corpus_preloaded` currently treats local corpus as preloaded only when new embeddings were added (`indexed_chunks > 0`).
2. On follow-up turns where embeddings already exist, `indexed_chunks` is commonly `0`, so corpus is treated as “not preloaded” even though corpus handles are available.
3. That suppresses stronger retrieval-only behavior and can let the model over-index on empty `query_research_memory` instead of corpus retrieval.

You selected:
1. Retrieval mode: **Always bootstrap corpus**.
2. Scope: **All interfaces** (shared API path).

## Done Definition
Behavior is done when:
1. In a research session with persisted local corpus, a follow-up question without `-r` consistently gets corpus-grounded evidence context pre-handover.
2. The same fix applies through shared API orchestration (CLI and XMPP parity).
3. Existing non-research flows, web-only flows, and session semantics remain unchanged.
4. Full test suite remains green.

## Public API / Interface Impact
No user-facing CLI flag/API shape changes.
Internal semantic change:
1. `PreloadResolution.is_corpus_preloaded` meaning will become “usable corpus is available” rather than “new chunk embeddings were added this turn.”
2. This changes orchestration behavior in `AskyClient.run_turn` and research registry setup, but not public function signatures.

## Files To Modify
1. `/Users/evren/code/asky/src/asky/api/types.py`
2. `/Users/evren/code/asky/src/asky/api/client.py`
3. `/Users/evren/code/asky/tests/test_api_turn_resolution.py`
4. `/Users/evren/code/asky/tests/test_api_library.py`
5. `/Users/evren/code/asky/tests/test_api_preload.py`
6. `/Users/evren/code/asky/ARCHITECTURE.md`
7. `/Users/evren/code/asky/DEVLOG.md`
8. `/Users/evren/code/asky/src/asky/api/AGENTS.md`
9. `/Users/evren/code/asky/src/asky/core/AGENTS.md` (if guidance contract wording is touched)

## Sequential Atomic Steps

### Step 1: Fix “corpus preloaded” detection semantics
Before:
1. Local preloaded is effectively tied to `local_payload.stats.indexed_chunks > 0`.

After:
1. Local preloaded is true when corpus is available this turn, using robust signals:
2. `local_payload.ingested` has at least one content-bearing item, or
3. `preloaded_source_urls` contains at least one corpus handle/source from preload.
4. Keep shortlist detection behavior intact unless it has similar false-negative patterns.

Constraints:
1. Do not force “preloaded” true on empty/failed local payload.
2. Do not alter schema/dataclass field names.

Verification:
1. Add/extend unit tests to prove `is_corpus_preloaded` is true when `indexed_chunks=0` but ingested corpus handles exist.

### Step 2: Guarantee deterministic bootstrap retrieval when preloaded corpus exists
Before:
1. Bootstrap retrieval context is appended only when `effective_research_mode and preload.is_corpus_preloaded`.

After:
1. Preserve research-mode guard.
2. Ensure bootstrap runs whenever preloaded corpus sources are available for the turn (aligned with new semantics and your “always bootstrap” choice).
3. Keep current caps/constants for source/chunk counts to limit latency/token impact.

Constraints:
1. Do not bootstrap in standard mode.
2. Do not change max-turn behavior or tool disable logic outside this gate.
3. No new dependencies.

Verification:
1. Add test where local corpus is available but no new embeddings were generated; assert bootstrap evidence is added to user-visible preloaded context path.

### Step 3: Keep registry/tool behavior aligned with new corpus-ready semantics
Before:
1. Research registry’s `corpus_preloaded` can be false for cached local follow-ups, so acquisition tools stay exposed and retrieval-only behavior weakens.

After:
1. Ensure `run_messages(... create_research_tool_registry ...)` receives correct `corpus_preloaded=True` for cached local follow-ups.
2. Preserve existing behavior for genuinely non-preloaded turns.

Constraints:
1. Do not remove acquisition tools when no corpus is actually ready.
2. Keep existing fallback `corpus_urls` injection behavior unchanged.

Verification:
1. Test asserts registry call receives `corpus_preloaded=True` for “ingested exists + indexed_chunks=0” preload payload.

### Step 4: Regression tests for no-degradation guarantees
Add/extend tests for:
1. Research follow-up with persisted local corpus path and cached embeddings: corpus bootstrap still happens.
2. Research turn with no local corpus and no shortlist preload: behavior unchanged.
3. Standard mode turn: behavior unchanged.
4. Existing fallback injection of `corpus_urls` remains intact.

Verification commands (per-step targeted):
1. `uv run pytest tests/test_api_preload.py -q`
2. `uv run pytest tests/test_api_library.py -q`
3. `uv run pytest tests/test_api_turn_resolution.py -q`
4. `uv run pytest tests/test_tools.py -q`

### Step 5: Documentation and changelog updates
Update:
1. `ARCHITECTURE.md` with revised corpus-preloaded semantics and bootstrap trigger.
2. `src/asky/api/AGENTS.md` to reflect follow-up reliability contract.
3. `src/asky/core/AGENTS.md` only if tool-exposure contract wording changes.
4. `DEVLOG.md` with date, root cause, fix summary, tests, and residual follow-up notes.

Verification:
1. `rg -n "is_corpus_preloaded|bootstrap retrieval|preloaded corpus" /Users/evren/code/asky/ARCHITECTURE.md /Users/evren/code/asky/src/asky/api/AGENTS.md /Users/evren/code/asky/src/asky/core/AGENTS.md`

### Step 6: Final full-suite verification
1. `uv run pytest`

## Explicit Assumptions
1. The inconsistent output is from orchestration gating, not a model outage.
2. Local corpus follow-up reliability is more important than minimal extra retrieval cost.
3. Shared API path is the right layer for parity and lowest maintenance risk.

## Edge Cases Required In Scope
1. Cached local corpus where embeddings already exist (`indexed_chunks=0`).
2. Mixed/local-only source modes with valid persisted corpus paths.
3. Turns where local ingestion succeeds but yields no meaningful content (must not falsely mark preloaded).
4. Sessions with persisted research mode but no corpus paths (existing halt behavior remains).

## Explicit “Do Not Do”
1. Do not change shell lock/session selection semantics.
2. Do not auto-resume arbitrary recent sessions when no lock exists.
3. Do not add dependencies.
4. Do not weaken local path/root safety checks.
5. Do not alter unrelated shortlist policy precedence.

## Final Checklist
1. Behavior: follow-up local-corpus questions work without repeating `-r`.
2. CLI/XMPP parity preserved via shared API path.
3. No regressions in standard mode, web-only research mode, or session handling.
4. Targeted tests added/updated and passing.
5. Full suite passing.
6. `ARCHITECTURE.md`, `DEVLOG.md`, and relevant AGENTS docs updated.

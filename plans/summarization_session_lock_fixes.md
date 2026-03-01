## Remove Background Document Summarization, Keep On-Demand Tool Summaries, Fix Directory Counting, and Persist Shell Lock

### Summary
Implement three fixes together without removing tools:

1. Stop all background “warm-up for future” document summarization (web + local).
2. Keep `get_link_summaries` available, but make it synchronous/on-demand: when called and summary is missing/stale, generate it immediately and return it in the same tool call.
3. Fix local directory ingestion so only real documents are counted (no synthetic directory pseudo-document).
4. Fix shell lock persistence by removing auto-clear-on-process-exit behavior.

Conversation/session summarization behavior remains as-is (threshold-based compaction only), with no document-summary drain at turn end.

### Done Definition (observable)
1. `asky -r "~/Books/test/bio" "Summarize the key points across all documents"` with 3 PDFs reports/uses 3 ingested documents, not 4.
2. After final model output is shown, no background document summarization continues or blocks exit.
3. If model calls `get_link_summaries` and the page has no cached summary yet, tool call waits, computes summary, and returns it immediately.
4. Session sticky lock file persists across `asky` process exits in same shell until explicit detach or stale-shell cleanup.
5. Session/conversation compaction summarization still works only when threshold triggers.

### Important API / Interface Behavior Changes
1. `get_link_summaries` behavior changes from “status-only for pending background jobs” to “on-demand synchronous summary generation when needed.”
2. No tool removal: `get_link_summaries` remains in research tool schemas/registry.
3. CLI no longer performs end-of-turn background-summary drain status for research turns.
4. Shell-lock lifecycle changes: `set_shell_session_id()` no longer registers process-exit auto-clear.

### Files (complete list)
1. [src/asky/research/adapters.py](/Users/evren/code/asky/src/asky/research/adapters.py)
2. [src/asky/cli/local_ingestion_flow.py](/Users/evren/code/asky/src/asky/cli/local_ingestion_flow.py)
3. [src/asky/research/cache.py](/Users/evren/code/asky/src/asky/research/cache.py)
4. [src/asky/research/tools.py](/Users/evren/code/asky/src/asky/research/tools.py)
5. [src/asky/cli/chat.py](/Users/evren/code/asky/src/asky/cli/chat.py)
6. [src/asky/core/session_manager.py](/Users/evren/code/asky/src/asky/core/session_manager.py)
7. [tests/test_research_adapters.py](/Users/evren/code/asky/tests/test_research_adapters.py)
8. [tests/test_local_ingestion_flow.py](/Users/evren/code/asky/tests/test_local_ingestion_flow.py)
9. [tests/test_research_tools.py](/Users/evren/code/asky/tests/test_research_tools.py)
10. [tests/test_research_cache.py](/Users/evren/code/asky/tests/test_research_cache.py)
11. [tests/test_cli.py](/Users/evren/code/asky/tests/test_cli.py)
12. [tests/test_safety_and_resilience_guards.py](/Users/evren/code/asky/tests/test_safety_and_resilience_guards.py)
13. [src/asky/research/AGENTS.md](/Users/evren/code/asky/src/asky/research/AGENTS.md)
14. [src/asky/cli/AGENTS.md](/Users/evren/code/asky/src/asky/cli/AGENTS.md)
15. [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md)
16. [DEVLOG.md](/Users/evren/code/asky/DEVLOG.md)

### Before/After (by change area)

1. Local directory ingestion counting
Before: directory “discover” payload is cached/indexed as a pseudo-document and counted.
After: directory payload is discovery metadata only; only discovered/read file targets are cached/indexed/counted as documents.

2. Research cache summarization trigger model
Before: cache writes can schedule background summarization jobs; jobs may continue after user-facing answer.
After: cache writes never schedule background summarization jobs.

3. `get_link_summaries`
Before: returns completed/pending/failed status from cache; does not ensure summary exists now.
After: if summary missing/invalid, performs synchronous summarization now, stores result, returns summary in same call; if summarization fails, returns clear failed status/error.

4. End-of-turn research drain
Before: research chat finalization waits/drains pending background summaries.
After: no background-summary drain path at end of turn.

5. Shell sticky lock lifecycle
Before: `set_shell_session_id()` registers `atexit.clear_shell_session`, lock removed at process exit.
After: no auto-remove on process exit; lock remains until explicit detach/stale cleanup.

### Sequential Atomic Steps

1. Mark directory-discovery payloads explicitly and stop pseudo-document ingestion.
Files: `adapters.py`, `local_ingestion_flow.py`, adapter+ingestion tests.
Verification:
- `uv run pytest tests/test_research_adapters.py tests/test_local_ingestion_flow.py -q`

2. Disable background document-summary scheduling in cache write path.
Files: `cache.py`, callers in `local_ingestion_flow.py` and `research/tools.py`, cache tests.
Verification:
- `uv run pytest tests/test_research_cache.py -q`

3. Implement synchronous on-demand summary generation in `get_link_summaries`.
Files: `research/tools.py`, related tool tests.
Verification:
- `uv run pytest tests/test_research_tools.py -q`

4. Remove CLI end-of-turn background-summary drain behavior.
Files: `cli/chat.py`, chat tests.
Verification:
- `uv run pytest tests/test_cli.py -q`

5. Fix shell lock persistence by removing process-exit auto-clear registration.
Files: `core/session_manager.py`, safety/session tests.
Verification:
- `uv run pytest tests/test_safety_and_resilience_guards.py tests/test_cli.py -q`

6. Update docs and devlog for architecture/behavior changes.
Files: `ARCHITECTURE.md`, `research/AGENTS.md`, `cli/AGENTS.md`, `DEVLOG.md`.
Verification:
- `rg -n "background summar|get_link_summaries|sticky|lock|local ingestion" ARCHITECTURE.md src/asky/research/AGENTS.md src/asky/cli/AGENTS.md DEVLOG.md`

7. Full regression run.
Verification:
- `uv run pytest`

### Edge Cases (must pass)
1. Directory target with supported files only counts those files.
2. Directory target with zero supported files yields zero ingested docs and no pseudo-doc entry.
3. `get_link_summaries` for uncached URL still returns “not cached; extract first.”
4. `get_link_summaries` for cached URL with existing summary returns immediately without recompute.
5. `get_link_summaries` summarization failure returns explicit failed state, no crash.
6. No extra wait/status at end of research/non-research turns tied to document-summary futures.
7. Existing stale-shell lock cleanup behavior remains intact.

### Assumptions and Defaults
1. Keep all existing tools; do not remove `get_link_summaries`.
2. No new dependencies.
3. Keep DB schema backward-compatible; no migration to drop summary columns.
4. Session compaction threshold logic already exists and remains unchanged.
5. Any currently running background jobs from older process exit naturally; new runs no longer spawn them.

### Explicit Constraints (what NOT to do)
1. Do not remove research tools from registry.
2. Do not add “future warm-up” background workers.
3. Do not change public CLI command syntax.
4. Do not add broad exception swallowing.
5. Do not regress session compaction behavior.

### Final Checklist
1. Tests pass (`uv run pytest`).
2. No debug prints or temp artifacts outside `temp/`.
3. No new dependencies.
4. Docs updated (`ARCHITECTURE.md`, relevant `AGENTS.md`, `DEVLOG.md`).
5. Tool surface preserved; behavior updated as specified.

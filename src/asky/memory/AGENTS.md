# memory/ — User Memory Package

Persistent cross-session user memory. Memories are global (not session-scoped), stored in SQLite and optionally indexed in a dedicated Chroma collection.

## Module Overview

| Module           | Responsibility                                                      |
|------------------|---------------------------------------------------------------------|
| `store.py`       | SQLite CRUD for `user_memories` table                               |
| `vector_ops.py`  | Embedding persistence (Chroma + SQLite BLOB fallback) and search    |
| `recall.py`      | Per-turn recall pipeline — returns a formatted `## User Memory` block |
| `tools.py`       | `save_memory` LLM tool definition and executor                      |
| `auto_extract.py`| Background LLM fact extraction for `--elephant-mode` sessions       |

## Data Storage

- **SQLite table**: `user_memories` in `history.db` (same file as conversations)
  - Columns: `id`, `memory_text`, `tags` (JSON), `embedding` (BLOB), `embedding_model`, `created_at`, `updated_at`
  - Initialized via `init_memory_table()` called from `storage/sqlite.py:init_db()`
- **Chroma collection**: `asky_user_memories` (separate from research findings)
  - `cosine` distance space; document IDs use `memory:{id}` pattern
  - Falls back to full SQLite cosine scan if Chroma is unavailable

## Key Constants (from `config/memory.toml`)

| Constant                        | Default | Meaning                                    |
|---------------------------------|---------|--------------------------------------------|
| `USER_MEMORY_ENABLED`           | `True`  | Gate for the entire recall pipeline        |
| `USER_MEMORY_RECALL_TOP_K`      | `5`     | Max memories injected per turn             |
| `USER_MEMORY_RECALL_MIN_SIMILARITY` | `0.35` | Minimum cosine score to include a result |
| `USER_MEMORY_DEDUP_THRESHOLD`   | `0.90`  | Cosine score above which a save is treated as an update |
| `USER_MEMORY_CHROMA_COLLECTION` | `"asky_user_memories"` | Chroma collection name         |

### Threshold Interpretation

Cosine similarity scores for normalized vectors range from 0 (orthogonal / unrelated) to 1 (identical). The two thresholds above mean:

- **0.35 (recall cutoff)**: "moderately related" — the memory text shares enough conceptual overlap with the query to be worth injecting. Below this, the memory is considered too far off-topic.
- **0.90 (dedup threshold)**: "near-duplicate" — the new text is nearly identical to an existing memory, so an update is performed instead of a new insert. This prevents accumulating slight rephrasing of the same fact.

## Recall Pipeline (per turn)

1. `has_any_memories()` — short-circuit if no embedded memories exist.
2. `expand_query_deterministic()` — YAKE keyphrase expansion of the query.
3. `search_memories()` — Chroma (primary) or SQLite cosine scan (fallback).
4. Format results as `## User Memory\n- fact1\n- fact2…` and return.
5. Caller (`api/preload.py`) appends this to the system prompt via `PreloadResolution.memory_context`.

Recall is skipped in `lean` mode.

## `save_memory` Tool

- Available in **all** registries (default and research).
- Respects `--tool-off save_memory`.
- Dedup: embeds the new text, queries Chroma/SQLite for the nearest neighbor. If cosine ≥ `USER_MEMORY_DEDUP_THRESHOLD`, updates the existing row instead of inserting.
- Returns `{"status": "saved"|"updated"|"error", "memory_id": int, "deduplicated": bool}`.

## Auto-Extraction (`--elephant-mode`)

- Enabled per-session via `sessions.memory_auto_extract` column.
- After each `run_turn()`, a daemon thread calls `extract_and_save_memories_from_turn()`.
- Uses `EXTRACTION_PROMPT` to ask the LLM for a JSON array of persistent facts.
- Each fact passes through `execute_save_memory()` (dedup built in).
- Thread is daemon — response delivery is never blocked.
- Requires an active session; `--elephant-mode` without `-ss`/`-rs` prints a warning and is ignored.

## CLI Commands

| Flag                    | Behavior                                    |
|-------------------------|---------------------------------------------|
| `--list-memories`       | Print a Rich table of all saved memories    |
| `--delete-memory ID`    | Delete one memory by ID                     |
| `--clear-memories`      | Prompt for confirmation, then delete all    |
| `--elephant-mode` / `-em` | Enable auto-extraction for this session   |

## Invariants

- Memories are **global** — never filtered by session or research scope.
- `embedding IS NOT NULL` is the condition for a memory to be searchable.
- `memory/vector_ops.py` does NOT use the `VectorStore` singleton; it manages its own Chroma client to keep memory separate from research findings.

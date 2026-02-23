# Medium Severity Issues

This document outlines issues that may impact robustness, performance, or maintainability, but do not pose an immediate security or critical failure risk.

## 1. Context Compaction Edge Case

**File:** `src/asky/core/engine.py`

**Issue:**
In `ConversationEngine.check_and_compact`, the destructive compaction (phase 2) attempts to drop history messages.

```python
        while history:
            history.pop(0)
            candidate = system_msgs + history + [last_msg]
            if count_tokens(candidate) < threshold_tokens:
                logger.info(f"Compacted to {count_tokens(candidate)} tokens.")
                # ...
                return candidate

        final_attempt = system_msgs + [last_msg]
        # ...
        logger.info(
            f"Compaction failed to preserve history. Returning minimal context: {count_tokens(final_attempt)} tokens."
        )
        return final_attempt
```

If `system_msgs + [last_msg]` (the `final_attempt`) *still* exceeds `threshold_tokens` (or more critically, the model's context limit), the function returns it anyway. This will cause the subsequent LLM API call to fail with HTTP 400. While `ConversationEngine.run` catches this and raises `ContextOverflowError`, and the CLI handles it, this creates a scenario where the user cannot continue the conversation without manually clearing history or restarting, even if compaction was attempted.

**Recommendation:**
- Implement a fallback that truncates the *content* of `last_msg` or `system_msgs` (if feasible) if even the minimal message set exceeds the limit.
- Or, explicitly detect this case and raise a specific error that suggests the user must shorten their query.

## 2. Tight Coupling of Research Schema

**Files:** `src/asky/research/cache.py`, `src/asky/research/vector_store.py`

**Issue:**
`ResearchCache.init_db()` is responsible for creating the SQLite tables `content_chunks`, `link_embeddings`, and `research_findings`. However, `VectorStore` (via `vector_store_chunk_link_ops.py` and `vector_store_finding_ops.py`) contains the logic for inserting into and querying these tables.

If the schema definition in `ResearchCache` changes without corresponding updates to the SQL queries in `VectorStore` (or vice-versa), the application will break. This split ownership increases the risk of regressions during refactoring.

**Recommendation:**
- Centralize the schema definition and SQL query logic for these tables in one module (e.g., `vector_store_storage.py` or within `ResearchCache`), and have `VectorStore` delegate to it.
- Alternatively, move the table creation logic for vector-related tables into `VectorStore.init_db()`.

## 3. Potential Resource Loading Issue

**File:** `src/asky/config/loader.py`

**Issue:**
```python
            # Load default content
            with resource_path.open("rb") as f:
                file_config = tomllib.load(f)
```
The code uses `resource_path.open("rb")` on a `Traversable` object returned by `resources.files()`. While this works for standard file systems, some zip-based environments or future Python versions might require `resources.as_file` context manager to ensure a file-like object is available, especially if `tomllib.load` expects a seekable stream (though `open("rb")` usually provides one). The usage in the subsequent block (for `shutil.copy`) correctly uses `as_file`.

**Recommendation:**
- Consistently use `resources.as_file(resource_path)` context manager when opening resources to ensure maximum compatibility across different packaging environments.

## 4. Lazy Loading Hiding Import Errors

**Files:** `src/asky/api/preload.py`, `src/asky/cli/chat.py`, `src/asky/core/engine.py`

**Issue:**
Extensive use of `asky.lazy_imports.call_attr` (e.g., for `shortlist_prompt_sources`, `ResearchCache`, etc.) improves startup time but delays `ImportError` or `AttributeError` until the function is actually called. This can make debugging configuration or dependency issues harder, as the stack trace will occur deep in the runtime rather than at startup.

**Recommendation:**
- Add a test suite (`tests/test_imports.py`) that explicitly imports all lazily-loaded modules to verify they are importable in the production environment.
- Consider using a more structured lazy proxy pattern that validates existence at module load time if possible, or document this behavior clearly for developers.

## 5. Memory Search Fallback Inefficiency

**File:** `src/asky/memory/vector_ops.py`

**Issue:**
In `search_memories`, if ChromaDB returns results but they are all filtered out (e.g., by `min_similarity`), the code falls back to a full SQLite scan (`_search_with_sqlite`).

```python
        if chroma_results:
            # ... checks results ...
            if ranked:
                return ranked

        return _search_with_sqlite(...)
```

If Chroma is working correctly but simply found no *relevant* matches (i.e., similarity is too low), falling back to SQLite (which uses the same embeddings) is unlikely to yield better results but incurs a significant performance penalty (scanning all rows). The fallback should probably only occur if Chroma fails or returns *no* results (empty list) due to an error/empty collection, not because of relevance filtering.

**Recommendation:**
- Distinguish between "Chroma error/empty" and "Chroma found low-relevance results".
- Only fall back to SQLite if Chroma is unavailable or the collection is empty.

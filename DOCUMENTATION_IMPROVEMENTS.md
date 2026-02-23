# Documentation Improvements

After reviewing the documentation (README.md, AGENTS.md, etc.) against the codebase, the following improvements are recommended.

## 1. Document Schema Ownership

**Location:** `src/asky/research/AGENTS.md`

**Current State:**
The documentation describes `ResearchCache` and `VectorStore`. It mentions tables but doesn't explicitly state which module *owns* the schema definitions vs. which *uses* them for querying.

**Recommendation:**
Add a section explicitly stating:
> **Schema Ownership:** `ResearchCache` owns the SQLite schema definition (table creation) for `research_cache`, `content_chunks`, `link_embeddings`, and `research_findings`. `VectorStore` (via `vector_store_chunk_link_ops` and `vector_store_finding_ops`) assumes these tables exist and performs CRUD operations on them. Changes to schema in `ResearchCache` must be coordinated with updates in `VectorStore`.

## 2. Document Lazy Loading Strategy

**Location:** `src/asky/core/AGENTS.md` and `src/asky/api/AGENTS.md`

**Current State:**
The documentation mentions "Lazy Loading" as a design decision but doesn't detail *how* it's implemented (using `asky.lazy_imports.call_attr`) or the implications for debugging import errors.

**Recommendation:**
Add a section explaining:
> **Lazy Loading Implementation:** To improve startup time, many modules (especially research tools and heavy dependencies like `yake` or `chromadb`) are imported lazily using `asky.lazy_imports.call_attr`. This means `ImportError` or `AttributeError` for these dependencies will only occur when the specific feature is first used, not at application startup. Developers should be aware of this when debugging configuration issues.

## 3. Clarify Memory Search Fallback Behavior

**Location:** `src/asky/memory/AGENTS.md`

**Current State:**
The documentation mentions "SQLite fallback" for memory search but implies it happens if Chroma is unavailable. It doesn't clarify that it *also* happens if Chroma returns results that are filtered out by `min_similarity`.

**Recommendation:**
Update the **Recall Pipeline** section to clarify:
> 3. `search_memories()` — attempts semantic search via ChromaDB first. If Chroma is unavailable OR if Chroma returns results that are all below `USER_MEMORY_RECALL_MIN_SIMILARITY`, it falls back to a full SQLite cosine scan using the same embeddings. This ensures robust recall even if the vector index is temporarily suboptimal or disconnected.

## 4. Document Configuration File Merging Order

**Location:** `src/asky/config/AGENTS.md`

**Current State:**
The documentation mentions "Deep-merge user config over defaults" but doesn't explicitly list the precedence order of the specific files loaded (e.g. `general.toml` vs `user.toml` vs `config.toml` legacy).

**Recommendation:**
Add a list showing the exact load order:
1. Bundled defaults (`asky.data.config/*.toml`)
2. User split config files (`~/.config/asky/*.toml`)
3. Legacy `config.toml` (if present, overrides split files)
4. Environment variable overrides (e.g., API keys)

# Research Package (`asky/research/`)

RAG-powered research mode with caching, semantic search, and persistent memory.

## Module Overview

| Module                           | Purpose                                         |
| -------------------------------- | ----------------------------------------------- |
| `tools.py`                       | Research tool schemas and executors             |
| `cache.py`                       | `ResearchCache` for URL content/links           |
| `vector_store.py`                | `VectorStore` for hybrid semantic search        |
| `vector_store_chunk_link_ops.py` | Chunk/link embedding and retrieval operations   |
| `vector_store_finding_ops.py`    | Research findings embedding/search operations   |
| `vector_store_common.py`         | Shared vector math and constants                |
| `embeddings.py`                  | `EmbeddingClient` for local embeddings          |
| `chunker.py`                     | Token-aware text chunking                       |
| `source_shortlist.py`            | Pre-LLM source ranking pipeline                 |
| `query_expansion.py`             | Decomposing queries into sub-queries.           |
| `evidence_extraction.py`         | Post-retrieval LLM fact extraction.             |
| `shortlist_collect.py`           | Candidate/seed-link collection stage            |
| `shortlist_score.py`             | Semantic + heuristic scoring stage              |
| `shortlist_types.py`             | Shared shortlist datatypes and callback aliases |
| `corpus_context.py`              | Corpus-aware context extraction for shortlist query enrichment |
| `sections.py`                    | Deterministic section indexing + strict matching |
| `adapters.py`                    | Built-in local-source loading helpers           |

## Research Tools (`tools.py`)

### Available Tools

| Tool                    | Description                                |
| ----------------------- | ------------------------------------------ |
| `extract_links`         | Cache URL content, return discovered links |
| `get_link_summaries`    | Get AI-generated page summaries            |
| `get_relevant_content`  | RAG retrieval of relevant chunks           |
| `get_full_content`      | Complete cached content                    |
| `list_sections`         | List section headings for local corpus     |
| `summarize_section`     | Deep summary for one local section         |
| `save_finding`          | Persist insights to research memory        |
| `query_research_memory` | Semantic search over saved findings        |

Tool schemas also support optional `system_prompt_guideline` metadata used by
chat/system-prompt assembly when the tool is enabled for a run.
When a chat session is active, registry plumbing can inject `session_id` into
memory tool calls so findings are written/read in session scope.
Research chat flow now guarantees that a session exists (auto-created when needed),
so session-scoped memory isolation is available by default in research mode.

`get_relevant_content` and `get_full_content` now also accept internal
`corpus_urls` identifiers and can resolve safe cache handles
(`corpus://cache/<id>`) to cached entries. This enables local-corpus retrieval
without exposing filesystem paths to the model.

Section-scoped retrieval contract:

- Preferred: `section_ref` (`corpus://cache/<id>#section=<section-id>`) or explicit `section_id`.
- Compatibility: legacy `corpus://cache/<id>/<section-id>` source suffixes are accepted.
- `list_sections` defaults to canonical body sections and emits `section_ref` for each row.

Parameter priority in `get_relevant_content`:

- If both `section_ref` and `section_id` are provided, `section_ref` takes precedence.
- If only `section_id` is provided alongside a source URL, it is applied as a section filter on that source.

### Tool Sets by Stage

Tools are grouped into constants to support per-stage exposure:

- `ACQUISITION_TOOL_NAMES`: `extract_links`, `get_link_summaries`, `get_full_content`.
- `RETRIEVAL_TOOL_NAMES`: `get_relevant_content`, `list_sections`, `summarize_section`, `save_finding`, `query_research_memory`.

When a corpus is pre-loaded by acquisition stages, acquisition tools are excluded to prevent redundant LLM work.

### Execution Flow

```
extract_links(urls, query?)
    ↓
ResearchCache.cache_url()
    ↓
VectorStore.store_chunk_embeddings()
    ↓
get_relevant_content(urls, query)
    ↓
Hybrid ranking (dense + lexical)
    ↓
Diverse chunk selection
```

## ResearchCache (`cache.py`)

Caches fetched URL content and extracted links with TTL.

### Key Features

- **TTL-based expiry**: Configurable `cache_ttl_hours`
- **Startup cleanup**: Expired entries purged on init (daemon thread)
- **Content + links**: Both cached together per URL
- **Invalidation**: Clears related vectors when content changes
- **Background summary drain support**: Tracks pending thread-pool summary futures
  and exposes `wait_for_background_summaries()` so callers can perform a final
  synchronized banner refresh before UI teardown.

### Schema (SQLite)

- `research_cache`: URL, content, links JSON, timestamps, TTL
- `research_findings`: Persistent research insights with embeddings

`ResearchCache` also exposes helper lookups used by manual/debug retrieval
workflows:

- `get_cached_by_id(cache_id)`
- `list_cached_sources(limit)`

## VectorStore (`vector_store.py`)

Hybrid semantic search combining ChromaDB dense and SQLite BM25 lexical retrieval.

### Collections

| Collection          | Content                                  |
| ------------------- | ---------------------------------------- |
| `content_chunks`    | Text chunks from cached pages            |
| `link_embeddings`   | Link anchor text for relevance filtering |
| `research_findings` | Saved insights for memory queries        |

### Hybrid Ranking

```python
final_score = (dense_weight * semantic_score) + ((1 - dense_weight) * lexical_score)
```

- **Dense**: Chroma nearest-neighbor cosine similarity
- **Lexical**: SQLite FTS5 BM25 scoring
- **Fallback**: SQLite-based cosine scan if Chroma unavailable

### Key Methods

- `store_chunk_embeddings()`: Generate and persist chunk vectors
- `search_content_chunks()`: Hybrid search with diversity filtering
- `search_relevant_links()`: Filter links by semantic relevance
- `clear_cache_embeddings()`: Remove stale vectors on invalidation
- `delete_findings_by_session()`: Session-scoped cleanup of findings and vectors

### Internal Module Split

- `vector_store.py` now focuses on `VectorStore` lifecycle, DB/Chroma capability checks, and compatibility wrappers.
- Heavy operations were extracted:
  - `vector_store_chunk_link_ops.py` for content chunks and links
  - `vector_store_finding_ops.py` for research memory findings
  - `vector_store_common.py` for shared math/constants
- Chroma chunk/link query filters use single-operator metadata conditions
  (`$and`) for compatibility with stricter Chroma metadata parsing.

## EmbeddingClient (`embeddings.py`)

Local sentence-transformer embeddings.

### Configuration

- **Model**: `all-MiniLM-L6-v2` (default)
- **Device**: CPU or CUDA
- **Batch size**: Configurable for memory management

### Features

- Singleton pattern for efficient reuse
- Lazy loading with cache-first Hugging Face download
- Pre-encode truncation to model max sequence length for embedding inputs
- Token counting for chunk alignment
- Usage stats exposed for banner display

## Text Chunker (`chunker.py`)

Token-aware sentence chunking for optimal embedding boundaries.

### Strategy

1. Split text into sentences
2. Build chunks within token budget
3. Maintain overlap for context continuity
4. Char-based fallback for non-sentence text

## Source Shortlist (`source_shortlist.py`)

Pre-LLM source ranking to improve prompt relevance.

### Pipeline

1. Extract URLs from prompt
2. Optional keyphrase extraction (YAKE)
3. Collect candidates: seed URLs + search results + expanded links
4. Fetch and extract main content
5. Score with embeddings + heuristics
6. Select top-k diverse sources

`shortlist_prompt_sources(...)` now accepts an optional `trace_callback` and
forwards it across search/fetch/seed-link transport paths when supported. This
enables verbose metadata traces for shortlist-stage HTTP calls (including
request failures such as 401/403).

Seed URL extraction accepts both explicit `http(s)://...` links and bare-domain
targets (e.g., `example.com/path`), normalizing bare targets to `https://...`
for deterministic fetch behavior.

When formatting shortlist context, explicitly mentioned seed URLs are included
in the model-facing shortlist context even if they rank below the usual top-k
context cutoff.

### Internal Module Split

- `source_shortlist.py` keeps public API and orchestration.
- `shortlist_collect.py` handles candidate gathering and seed-link expansion.
- `shortlist_score.py` handles embedding-based scoring and ranking reasons.
- `shortlist_types.py` holds shared shortlist datatypes and callback aliases.

### Enablement

- Global flags per mode (research/standard)
- Per-model override in `models.toml`
- `--lean` flag disables for single run
- Default shortlist budgets are bounded (`max_candidates=40`, `max_fetch_urls=20`)
  and remain configurable in `research.toml`.

## Local Loader (`adapters.py`)

`adapters.py` is now a built-in local-source loader only (no custom adapter routing).

- Accepted targets: `local://...`, `file://...`, absolute/relative local paths.
- Local loading is enabled only when `research.local_document_roots` is configured.
- Absolute paths are accepted only when they are inside configured roots.
- Root-relative targets (for example `/nested/doc.txt`) resolve under configured roots.
- `extract_local_source_targets(...)` provides deterministic token extraction from prompts for pre-LLM local preload.
- Directory targets (discover): produce file links as `local://...` (non-recursive in v1).
- File targets (read/discover): normalize to plain text for cache/indexing.
  - Text-like: `.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`
  - Document-like: `.pdf`, `.epub` via PyMuPDF
- Directory targets are discovery-only in v1; select returned file links for content reads.

### Local Target Guardrails in Research Tools

- Generic research LLM tools (`extract_links`, `get_link_summaries`, `get_relevant_content`, `get_full_content`) reject local filesystem targets.
- Safe corpus handles (`corpus://cache/<id>`) are allowed for retrieval tools
  and map to cached entries without revealing local paths.
- `list_sections` and `summarize_section` are local-corpus-only tools:
  - web URLs are rejected explicitly,
  - they are hidden from registry exposure in `web_only` mode,
  - in `mixed` mode they only accept corpus handles (`corpus://cache/<id>`).
  - `summarize_section` resolves aliases to canonical body sections and refuses tiny sections.
- This prevents implicit local-file access via broad URL-oriented tools.
- Local-file access should be handled through explicit local-source tooling/adapters in dedicated workflows.
- Query preprocessing can redact local path tokens from model-visible user text when local
  preload is active, avoiding direct file-path exposure to the model.

## Dependencies

```
research/
├── tools.py → cache.py, vector_store.py
├── cache.py → embeddings.py (for summaries)
├── vector_store.py → embeddings.py, chunker.py
├── source_shortlist.py → retrieval.py, embeddings.py
└── adapters.py → builtin local loading helpers
```

# Research Package (`asky/research/`)

RAG-powered research mode with caching, semantic search, and persistent memory.

## Module Overview

| Module | Purpose |
|--------|---------|
| `tools.py` | Research tool schemas and executors |
| `cache.py` | `ResearchCache` for URL content/links |
| `vector_store.py` | `VectorStore` for hybrid semantic search |
| `embeddings.py` | `EmbeddingClient` for local embeddings |
| `chunker.py` | Token-aware text chunking |
| `source_shortlist.py` | Pre-LLM source ranking pipeline |
| `adapters.py` | Non-HTTP source adapters |

## Research Tools (`tools.py`)

### Available Tools

| Tool | Description |
|------|-------------|
| `extract_links` | Cache URL content, return discovered links |
| `get_link_summaries` | Get AI-generated page summaries |
| `get_relevant_content` | RAG retrieval of relevant chunks |
| `get_full_content` | Complete cached content |
| `save_finding` | Persist insights to research memory |
| `query_research_memory` | Semantic search over saved findings |

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

### Schema (SQLite)

- `research_cache`: URL, content, links JSON, timestamps, TTL
- `research_findings`: Persistent research insights with embeddings

## VectorStore (`vector_store.py`)

Hybrid semantic search combining ChromaDB dense and SQLite BM25 lexical retrieval.

### Collections

| Collection | Content |
|------------|---------|
| `content_chunks` | Text chunks from cached pages |
| `link_embeddings` | Link anchor text for relevance filtering |
| `research_findings` | Saved insights for memory queries |

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

## EmbeddingClient (`embeddings.py`)

Local sentence-transformer embeddings.

### Configuration

- **Model**: `all-MiniLM-L6-v2` (default)
- **Device**: CPU or CUDA
- **Batch size**: Configurable for memory management

### Features

- Singleton pattern for efficient reuse
- Lazy loading with cache-first Hugging Face download
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

### Enablement

- Global flags per mode (research/standard)
- Per-model override in `models.toml`
- `--lean` flag disables for single run

## Adapters (`adapters.py`)

Route non-HTTP sources to custom tools.

### Configuration

```toml
[research.source_adapters.local]
prefix = "local://"
tool = "read_local"  # or discover_tool + read_tool
```

### Flow

- Match URL prefix to adapter
- Execute configured custom tool
- Parse JSON response (title, content, links)
- Cache result for reuse

## Dependencies

```
research/
├── tools.py → cache.py, vector_store.py
├── cache.py → embeddings.py (for summaries)
├── vector_store.py → embeddings.py, chunker.py
├── source_shortlist.py → retrieval.py, embeddings.py
└── adapters.py → tools.py (custom tool execution)
```

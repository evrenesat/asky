# Deep Research Mode

**asky** features a powerful Deep Research Mode (`-r`) that breaks away from simple question-and-answer interactions. When enabled, asky utilizes a specialized prompt and a dynamic toolset to conduct multi-step, RAG-backed investigations. It can formulate its own sub-queries, search the web, ingest local directories, read contents, and summarize findings before generating a final answer.

## Enabling Research Mode

You can enable research mode by passing the `-r` or `--research` flag:

```bash
asky -r "Compare the latest iPhone vs Samsung flagship specs and reviews"
```

_Note: Passing local corpus paths with `-lc` implicitly enables research mode._

## The Research Workflow

Research mode fundamentally changes how asky approaches a query:

1. **Query Expansion:** If your query is complex, asky decompositions it into smaller, more focused sub-queries (e.g., separating "iPhone specs" from "Samsung reviews").
2. **Source Discovery:**
   - **Local Corpus:** If you provided local documents (via `-lc`), it indexes them.
   - **Web Search:** asky searches the web for the sub-queries.
3. **Source Ranking (Shortlisting):** Before reading any full pages, asky scores and ranks the discovered links based on relevance to your query, ensuring it only spends time on the most promising sources.
4. **Content Ingestion & RAG:** The top-ranked pages are fetched, stripped of HTML noise, and chunked into a local vector database.
5. **Investigation Loop:** The agent uses an iterative loop, utilizing its toolset to search within the vector database (`get_relevant_content`), extract specific evidence, or even discover more links from the pages it read (`extract_links`).
6. **Synthesis:** Once it has gathered enough evidence, it synthesizes a comprehensive final answer.

### Evidence Extraction

For smaller models or complex documents, asky includes a post-retrieval fact extraction step. Before passing raw chunks of text to the main model, a secondary process extracts precise, structured facts (evidence) from the retrieved text. This ensures the main model bases its answer on concrete data rather than noisy web page content. You can enable this in `research.toml` with `evidence_extraction_enabled = true`.

## Local Corpus vs Web-Based Research

You can use research mode strictly on the web, strictly on your local files, or a mix of both.

### Web-Based Research

Use natural prompts. Provide a query, and the agent will use SearXNG or Serper to find sources:

```bash
asky -r "Compare OAuth2 device flow vs PKCE for a CLI app"
```

### Local-Corpus Research

You can restrict asky's research to specific local files or directories. First, configure your allowed local roots in `research.toml` to prevent unintended file access:

```toml
[research]
local_document_roots = [
  "/Users/you/docs/security",
  "/Users/you/docs/engineering"
]
```

Then, use the `-lc` (or `--local-corpus`) flag, or reference the files directly in your query:

```bash
asky -lc /Users/you/docs/security/passwords.md "Summarize the password requirements"
```

Or reference them in the query (paths must be relative to your configured `local_document_roots`):

```bash
asky -r "Use /passwords.md and list MFA requirements"
```

_Note: asky processes local files (.txt, .md, .pdf, .csv, etc.) similar to web pages. It chunks them, embeds them, and the model uses RAG tools to query the content._

### Mixed Web & Local Research

You can combine both sources in a single query:

```bash
asky -r "Use /passwords.md and verify whether NIST 800-63B guidance has changed on the web"
```

Asky will ingest your local policy document, then use web search to find current NIST guidance, and compare the two.

## Research Memory (Session-Scoped)

Research mode automatically creates a session for each run. Any findings the agent deems important can be explicitly saved to a "Research Memory".

- **Isolation:** Research findings are scoped strictly to the session they were created in.
- **Persistence:** Findings remain available until the session research data is explicitly deleted.
- **Usage:** This allows you to build knowledge incrementally. You can run one research query, let it save findings, and then ask follow-up questions in the same session, relying on the already-established research memory.

```bash
# Start a research session (auto-creates a session if none specified)
asky -ss "OAuth Research" -r "Investigate OAuth2 device flow implementation patterns"

# Later, in the same session, query the saved findings
asky -rs "OAuth Research" -r "What were the key security considerations from our previous research?"
```

## Specialized Toolset

In standard mode, asky uses generic tools. In research mode, the toolset is swapped for a highly specialized RAG toolkit:

- `extract_links`: Scans discovered pages for more citations/links without loading full content.
- `get_link_summaries`: Rapidly summarizes multiple pages to help the agent decide what to read fully.
- `get_relevant_content`: Uses hybrid semantic search (dense embeddings + lexical BM25) to pull precise paragraphs from long documents.
- `get_full_content`: Retrieves complete cached content when a deep read is required.
- `save_finding`: Persists a specific insight to the session's Research Memory.
- `query_research_memory`: Searches over previously saved findings using natural language.

_Note: To optimize token usage, if asky has already ingested a local corpus or shortlisted web links for a query, it dynamically hides "acquisition" tools (like web search) from the model to force it to focus on reading the data already collected._

## Architecture Overview

Research mode is built on a robust local RAG pipeline:

- **ResearchCache:** Caches fetched URL content and extracted links (with TTL) to avoid re-fetching.
- **VectorStore:** A hybrid search engine combining ChromaDB (dense cosine similarity) and SQLite FTS5 (lexical BM25).
- **EmbeddingClient:** Uses local Sentence-Transformers (`all-MiniLM-L6-v2`) to generate embeddings locally on your machine.
- **TextChunker:** Token-aware sentence chunker ensures logical context boundaries.
- **SourceShortlist:** Pre-LLM ranking pipeline to filter out low-value URLs.
- **QueryExpander:** Decomposes complex user queries into sub-queries.
- **EvidenceExtractor:** Post-retrieval step to turn noisy text chunks into structured facts.

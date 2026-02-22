# Deep Research Mode

Deep Research Mode (`-r`) is asky's workflow for multi-step retrieval-heavy questions. It is not "always better" than normal mode. It adds more preprocessing, more tools, and more latency in exchange for stronger source-grounded answers when the question needs it.

## Enabling Research Mode

You can enable research mode by passing the `-r` or `--research` flag:

```bash
asky -r "Compare the latest iPhone vs Samsung flagship specs and reviews"
```

```bash
asky -r "Compare the latest iPhone vs Samsung flagship specs and reviews"
```

## Standard Mode vs Research Mode

Both modes use the same `AskyClient.run_turn()` orchestration path, but they diverge in prompting, tool exposure, and session behavior.

| Area                          | Standard mode (default)                                                        | Research mode (`-r`)                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| System prompt                 | General assistant prompt                                                       | Research workflow prompt with retrieval/memory guidance                                                    |
| Toolset focus                 | Generic discovery + fetch (`web_search`, `get_url_content`, `get_url_details`) | Research RAG loop (`extract_links`, `get_relevant_content`, `save_finding`, `query_research_memory`, etc.) |
| Session behavior              | Session optional                                                               | Session auto-created if missing (for research-memory isolation)                                            |
| Memory behavior               | User memory (`save_memory`) for preferences/facts about user                   | Session-scoped research findings (`save_finding`) + semantic recall (`query_research_memory`)              |
| Pre-LLM preload               | Optional shortlist can still run                                               | Same shortlist pipeline plus optional local corpus ingestion and retrieval-only guidance                   |
| Typical output shape          | Faster, shorter direct answers; fewer intermediate citations                   | Slower, more evidence-heavy, often citation-rich synthesis                                                 |
| Failure mode on weaker models | May under-search and answer from priors                                        | May underuse `save_finding` / `query_research_memory` unless prompted tightly                              |

## Is Research Mode Actually Better?

Short answer: sometimes.

- Better fit:
  - Multi-source comparisons.
  - Long documents where targeted chunk retrieval beats full-page reads.
  - Local corpus + web cross-checking.
  - Work that benefits from session-scoped research memory across follow-up turns.
- Worse fit:
  - Simple factual questions answerable from one source.
  - Cases where tool overhead dominates answer time.
  - Small models that struggle with long, procedural prompts and skip memory-saving calls.

If you are evaluating value, run the same dataset in both modes using the eval harness (`docs/research_eval.md`) and compare pass rate, tool mix, and latency. Don't assume the mode is helping without this A/B check.

## The Research Workflow

Research mode fundamentally changes how asky approaches a query:

1. **Query Expansion:** If your query is complex, asky decomposes it into smaller, more focused sub-queries (e.g., separating "iPhone specs" from "Samsung reviews").
2. **Source Discovery:**
   - **Local Corpus:** If you provided local documents (via `-lc`), it indexes them.
   - **Web Search:** asky searches the web for the sub-queries.
3. **Source Ranking (Shortlisting):** Before reading any full pages, asky scores and ranks the discovered links based on relevance to your query, ensuring it only spends time on the most promising sources.
4. **Content Ingestion & RAG:** The top-ranked pages are fetched, stripped of HTML noise, and chunked into a local vector database.
5. **Investigation Loop:** The agent uses an iterative loop, utilizing its toolset to search within the vector database (`get_relevant_content`), extract specific evidence, or even discover more links from the pages it read (`extract_links`).
6. **Synthesis:** Once it has gathered enough evidence, it synthesizes a comprehensive final answer.

In retrieval-only runs (when corpus is already preloaded), asky hides acquisition tools so the model focuses on `query_research_memory` + `get_relevant_content` instead of re-discovering sources.

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

Then, use the `-r` flag followed by a corpus pointer. A corpus pointer can be a filename, a directory name, or a comma-separated list of names (resolved against your `local_document_roots`). Absolute paths are also supported.

```bash
# Reference a file under your corpus root
asky -r passwords.md "Summarize the password requirements"

# Reference multiple files
asky -r "passwords.md,mfa_policy.pdf" "List all authentication requirements"

# Reference a subdirectory
asky -r security/policies "Are there any gaps in our MFA coverage?"

# Use an absolute path
asky -r /Users/you/docs/engineering/specs.pdf "What are the specs?"
```

_Note: asky processes local files (.txt, .md, .pdf, .csv, EPUB, etc.) similar to web pages. It chunks them, embeds them, and uses RAG tools to query the content._

### Mixed Web & Local Research

You can combine both sources in a single query:

```bash
asky -r passwords.md "Verify whether NIST 800-63B guidance has changed on the web"
```

Asky will ingest your local policy document, then use web search to find current NIST guidance, and compare the two.

## Research Memory (Session-Scoped)

Research mode automatically creates a session for each run. Any findings the agent deems important can be explicitly saved to a "Research Memory".

- **Isolation:** Research findings are scoped strictly to the session they were created in.
- **Persistence:** Findings remain available until the session research data is explicitly deleted.
- **Usage:** This allows you to build knowledge incrementally. You can run one research query, let it save findings, and then ask follow-up questions in the same session, relying on the already-established research memory.
- **Not global by default:** Research findings are session-scoped; this is intentionally different from user memory (`save_memory`), which is about persistent user preferences/facts.

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

## Current Gaps and Inefficiencies

- Prompt/tool mismatch can happen:
  - The base research prompt describes full discovery workflow, while some runs expose retrieval-only tools after preload. This can confuse weaker models.
- Research-memory calls are model-sensitive:
  - On smaller models, `save_finding` and `query_research_memory` may be skipped unless instructions are explicit and short.
- Research vs normal comparison is easy to assume and hard to prove:
  - Without dual-mode eval runs, it is difficult to know if complexity improved quality or only increased latency.

## Prompt Tuning Notes (For Smaller Models)

If research-memory usage is low in your runs, tune `src/asky/data/config/prompts.toml`:

- Keep memory instructions concrete:
  - "Use `save_finding` for source-backed claims."
  - "Before final answer, run `query_research_memory` and synthesize from saved findings."
- Clarify tool intent:
  - `save_finding` is research evidence memory.
  - `save_memory` is user-profile memory.
- Keep steps short and procedural:
  - Smaller models tend to follow short operational checklists better than long narrative prompts.

## Architecture Overview

Research mode is built on a robust local RAG pipeline:

- **ResearchCache:** Caches fetched URL content and extracted links (with TTL) to avoid re-fetching.
- **VectorStore:** A hybrid search engine combining ChromaDB (dense cosine similarity) and SQLite FTS5 (lexical BM25).
- **EmbeddingClient:** Uses local Sentence-Transformers (`all-MiniLM-L6-v2`) to generate embeddings locally on your machine.
- **TextChunker:** Token-aware sentence chunker ensures logical context boundaries.
- **SourceShortlist:** Pre-LLM ranking pipeline to filter out low-value URLs.
- **QueryExpander:** Decomposes complex user queries into sub-queries.
- **EvidenceExtractor:** Post-retrieval step to turn noisy text chunks into structured facts.

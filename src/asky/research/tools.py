"""Research mode tool executors."""

import difflib
import logging
from typing import Any, Dict, List, Optional

from asky.config import (
    RESEARCH_MAX_LINKS_PER_URL,
    RESEARCH_MAX_RELEVANT_LINKS,
    RESEARCH_MEMORY_MAX_RESULTS,
)
from asky.retrieval import fetch_url_document
from asky.research.cache import ResearchCache
from asky.research.chunker import chunk_text
from asky.research.embeddings import get_embedding_client
from asky.research.vector_store import get_vector_store
from asky.research.adapters import fetch_source_via_adapter, has_source_adapter
from asky.url_utils import is_local_filesystem_target, sanitize_url

logger = logging.getLogger(__name__)
DEFAULT_HYBRID_DENSE_WEIGHT = 0.75
DEFAULT_MIN_CHUNK_RELEVANCE = 0.15
MAX_RAG_CANDIDATE_MULTIPLIER = 3
CHUNK_DIVERSITY_SIMILARITY_THRESHOLD = 0.92
CONTENT_PREVIEW_SHORT_CHARS = 2000
CONTENT_PREVIEW_LONG_CHARS = 3000
LOCAL_TARGET_UNSUPPORTED_ERROR = (
    "Local filesystem targets are not supported by this tool. "
    "Use an explicit local-source tool instead."
)


# Tool Schemas for LLM
RESEARCH_TOOL_SCHEMAS = [
    {
        "name": "extract_links",
        "description": """Extract and discover links from web pages for research exploration.
Returns ONLY link labels and URLs - the actual page content is cached for later retrieval.
Use this to explore what information is available before deciding what to read in depth.
Optionally provide a research query to rank links by semantic relevance (requires embedding model).

Example: extract_links(urls=["https://example.com"], query="machine learning applications")""",
        "system_prompt_guideline": "Run early to discover candidate links and cache page data before deeper reads.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to extract links from",
                },
                "url": {
                    "type": "string",
                    "description": "Single URL (alternative to urls array)",
                },
                "query": {
                    "type": "string",
                    "description": "Optional: research query to rank links by relevance",
                },
                "max_links": {
                    "type": "integer",
                    "default": 30,
                    "description": "Maximum links to return per URL",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_link_summaries",
        "description": """Get AI-generated summaries of previously cached pages.
Use after extract_links to preview page contents before requesting full content.
Summaries are generated in the background - status may show 'processing' if not ready yet.
This is efficient for deciding which pages are worth reading in full.""",
        "system_prompt_guideline": "Use to quickly triage cached pages before spending tokens on long content.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to get summaries for (must be previously cached via extract_links)",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "get_relevant_content",
        "description": """Retrieve only the most relevant content sections from cached pages using RAG.
Uses semantic search to find sections matching your specific query - much more efficient than full content.
Best for extracting specific information without loading entire pages.
Requires embedding model to be available.""",
        "system_prompt_guideline": "Prefer this over full-page reads when you need targeted facts for a specific question.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to retrieve content from (must be cached)",
                },
                "query": {
                    "type": "string",
                    "description": "What specific information are you looking for?",
                },
                "max_chunks": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum content sections to return per URL",
                },
                "dense_weight": {
                    "type": "number",
                    "default": DEFAULT_HYBRID_DENSE_WEIGHT,
                    "description": "Weight of semantic similarity in hybrid ranking (0 to 1)",
                },
                "min_relevance": {
                    "type": "number",
                    "default": DEFAULT_MIN_CHUNK_RELEVANCE,
                    "description": "Minimum hybrid relevance threshold to include a section",
                },
            },
            "required": ["urls", "query"],
        },
    },
    {
        "name": "get_full_content",
        "description": """Retrieve the complete cached content from pages.
Use when you need comprehensive understanding of a page, not just specific sections.
More token-intensive than get_relevant_content - use sparingly.
Content must have been cached previously via extract_links.""",
        "system_prompt_guideline": "Reserve for cases where targeted retrieval is insufficient and full context is required.",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to get full content from (must be cached)",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "save_finding",
        "description": """Save a discovered fact or insight to research memory for future reference.
Use this to persist important findings that may be useful in future research sessions.
Findings are stored with embeddings for semantic retrieval.
Include source URL and tags for better organization and retrieval.""",
        "system_prompt_guideline": "Persist high-value findings with source metadata as you validate them.",
        "parameters": {
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "The fact, insight, or piece of information to save",
                },
                "source_url": {
                    "type": "string",
                    "description": "URL where this information was found",
                },
                "source_title": {
                    "type": "string",
                    "description": "Title of the source page",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization (e.g., ['climate', 'statistics', '2024'])",
                },
            },
            "required": ["finding"],
        },
    },
    {
        "name": "query_research_memory",
        "description": """Search your research memory for previously saved findings.
Uses semantic search to find relevant information from past research sessions.
Useful for recalling facts, statistics, or insights you've discovered before.""",
        "system_prompt_guideline": "Use at the start of research to reuse prior findings before collecting new sources.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in research memory",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of findings to return",
                },
            },
            "required": ["query"],
        },
    },
]


# Tool names grouped by pipeline stage purpose.
ACQUISITION_TOOL_NAMES = frozenset(
    {
        "extract_links",
        "get_link_summaries",
        "get_full_content",
    }
)

RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "get_relevant_content",
        "save_finding",
        "query_research_memory",
    }
)


def _sanitize_url(url: str) -> str:
    """Remove artifacts from URLs."""
    return sanitize_url(url)


def _split_local_targets(
    urls: List[str],
) -> tuple[List[str], Dict[str, Dict[str, str]]]:
    """Separate local filesystem targets from eligible URLs."""
    eligible: List[str] = []
    rejected: Dict[str, Dict[str, str]] = {}
    for url in urls:
        if is_local_filesystem_target(url):
            rejected[url] = {"error": LOCAL_TARGET_UNSUPPORTED_ERROR}
            continue
        eligible.append(url)
    return eligible, rejected


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    """Deduplicate values while preserving first-seen order."""
    seen = set()
    deduped: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _normalize_session_id(raw_session_id: Any) -> Optional[str]:
    """Normalize optional session identifiers from tool arguments."""
    if raw_session_id is None:
        return None
    session_id = str(raw_session_id).strip()
    return session_id or None


def _select_diverse_chunks(
    ranked_chunks: List[Dict[str, Any]], max_chunks: int
) -> List[Dict[str, Any]]:
    """Select top chunks while avoiding near-duplicate snippets."""
    selected: List[Dict[str, Any]] = []
    for candidate in ranked_chunks:
        candidate_text = candidate.get("text", "")
        is_duplicate = any(
            difflib.SequenceMatcher(None, candidate_text, item.get("text", "")).ratio()
            >= CHUNK_DIVERSITY_SIMILARITY_THRESHOLD
            for item in selected
        )
        if is_duplicate:
            continue
        selected.append(candidate)
        if len(selected) >= max_chunks:
            break
    return selected


def _fetch_and_parse(
    url: str,
    query: Optional[str] = None,
    max_links: Optional[int] = None,
    operation: str = "discover",
) -> Dict[str, Any]:
    """Fetch URL and extract content + links."""
    url = _sanitize_url(url)

    adapter_result = fetch_source_via_adapter(
        url,
        query=query,
        max_links=max_links,
        operation=operation,
    )
    if adapter_result is not None:
        return adapter_result

    try:
        payload = fetch_url_document(
            url=url,
            output_format="markdown",
            include_links=True,
            max_links=max_links or RESEARCH_MAX_LINKS_PER_URL,
        )
        if payload.get("error"):
            return {
                "content": "",
                "title": "",
                "links": [],
                "error": str(payload["error"]),
            }

        return {
            "content": str(payload.get("content", "")),
            "title": str(payload.get("title", "") or url),
            "links": payload.get("links", []),
            "error": None,
        }
    except Exception as e:
        return {
            "content": "",
            "title": "",
            "links": [],
            "error": f"Unexpected error: {str(e)}",
        }


def _ensure_adapter_cached(
    cache: ResearchCache,
    url: str,
    query: Optional[str] = None,
    max_links: Optional[int] = None,
    require_content: bool = False,
    usage_tracker: Optional[Any] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Ensure adapter targets are cached and optionally hydrated with content."""
    cached = cache.get_cached(url)
    if cached and (not require_content or cached.get("content")):
        return cached, None

    if not has_source_adapter(url):
        return cached, None

    parsed = _fetch_and_parse(
        url,
        query=query,
        max_links=max_links,
        operation="read" if require_content else "discover",
    )
    if parsed.get("error"):
        return cached, parsed["error"]
    if require_content and not parsed.get("content"):
        return cached, "Adapter returned empty content."

    cache.cache_url(
        url=url,
        content=parsed.get("content", ""),
        title=parsed.get("title", url),
        links=parsed.get("links", []),
        trigger_summarization=bool(parsed.get("content", "")),
        usage_tracker=usage_tracker,
    )

    cached = cache.get_cached(url)
    if require_content and cached and not cached.get("content"):
        return cached, "Adapter returned empty content."
    return cached, None


def _get_cache() -> ResearchCache:
    """Get the research cache instance."""
    return ResearchCache()


def _try_embed_links(cache_id: int, links: List[Dict[str, str]]) -> bool:
    """Try to embed links for relevance filtering. Returns True if successful."""
    try:
        vector_store = get_vector_store()
        embedding_model = getattr(vector_store.embedding_client, "model", "")
        has_embeddings = vector_store.has_link_embeddings(cache_id)

        has_for_model_method = getattr(
            vector_store, "has_link_embeddings_for_model", None
        )
        if callable(has_for_model_method):
            model_result = has_for_model_method(cache_id, embedding_model)
            if isinstance(model_result, bool):
                has_embeddings = model_result

        if not has_embeddings:
            vector_store.store_link_embeddings(cache_id, links)
        return True
    except Exception as e:
        logger.warning(f"Link embedding failed (will use unranked links): {e}")
        return False


def _search_relevant_chunks(
    vector_store: Any,
    cache_id: int,
    query: str,
    max_chunks: int,
    dense_weight: float,
    min_relevance: float,
) -> List[Dict[str, Any]]:
    """Search chunks with hybrid ranking when available, otherwise dense fallback."""
    candidate_count = max_chunks * MAX_RAG_CANDIDATE_MULTIPLIER
    search_hybrid = getattr(vector_store, "search_chunks_hybrid", None)
    if callable(search_hybrid):
        hybrid_result = search_hybrid(
            cache_id=cache_id,
            query=query,
            top_k=candidate_count,
            dense_weight=dense_weight,
            min_score=min_relevance,
        )
        if isinstance(hybrid_result, list):
            if not hybrid_result or isinstance(hybrid_result[0], dict):
                return hybrid_result

    dense_results = vector_store.search_chunks(cache_id, query, top_k=max_chunks)
    return [
        {
            "text": text,
            "score": score,
            "dense_score": score,
            "lexical_score": 0.0,
        }
        for text, score in dense_results
    ]


def execute_extract_links(args: Dict[str, Any]) -> Dict[str, Any]:
    """Extract links from URLs, cache content, return only links.

    If 'query' is provided, ranks links by semantic relevance.
    """
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    # Also support single 'url' parameter
    single_url = args.get("url")
    if single_url:
        urls.append(single_url)

    # Deduplicate and filter
    urls = _dedupe_preserve_order([_sanitize_url(u) for u in urls if u])
    if not urls:
        return {"error": "No URLs provided. Please specify 'urls' or 'url' parameter."}

    urls, rejected_results = _split_local_targets(urls)
    if not urls:
        return rejected_results

    query = args.get("query")
    max_links = args.get("max_links", RESEARCH_MAX_LINKS_PER_URL)
    usage_tracker = args.get("summarization_tracker")

    cache = _get_cache()
    results = dict(rejected_results)

    for url in urls:
        # Check cache first
        cached = cache.get_cached(url)

        if cached:
            links = cached["links"]
            cache_id = cached["id"]
            from_cache = True
            logger.debug(f"Cache hit for {url}")
        else:
            # Fetch fresh
            logger.debug(f"Fetching {url}")
            parsed = _fetch_and_parse(
                url,
                query=query,
                max_links=max_links,
                operation="discover",
            )

            if parsed["error"]:
                results[url] = {"error": parsed["error"]}
                continue

            # Cache the content (triggers background summarization)
            cache_id = cache.cache_url(
                url=url,
                content=parsed["content"],
                title=parsed["title"],
                links=parsed["links"],
                trigger_summarization=bool(parsed["content"]),
                usage_tracker=usage_tracker,
            )

            links = parsed["links"]
            from_cache = False

        # Try to embed links for relevance filtering
        _try_embed_links(cache_id, links)

        # Apply relevance filtering if query provided
        if query and links:
            try:
                vector_store = get_vector_store()
                ranked = vector_store.rank_links_by_relevance(
                    cache_id, query, top_k=min(max_links, RESEARCH_MAX_RELEVANT_LINKS)
                )
                if ranked:
                    links = [
                        {
                            "text": link["text"],
                            "href": link["href"],
                            "relevance": round(score, 3),
                        }
                        for link, score in ranked
                    ]
                else:
                    # Fallback to unranked if ranking failed
                    links = links[:max_links]
            except Exception as e:
                logger.warning(f"Relevance ranking failed, using unranked: {e}")
                links = links[:max_links]
        else:
            links = links[:max_links]

        results[url] = {
            "links": links,
            "cached": from_cache,
            "link_count": len(links),
            "note": "Content cached. Use get_link_summaries or get_relevant_content to read.",
        }

    return results


def execute_get_link_summaries(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get summaries for cached URLs."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = _dedupe_preserve_order([_sanitize_url(u) for u in urls if u])
    if not urls:
        return {"error": "No URLs provided."}

    urls, rejected_results = _split_local_targets(urls)
    if not urls:
        return rejected_results

    cache = _get_cache()
    results = dict(rejected_results)
    usage_tracker = args.get("summarization_tracker")

    for url in urls:
        summary_info = cache.get_summary(url)
        if not summary_info and has_source_adapter(url):
            _, adapter_error = _ensure_adapter_cached(
                cache, url, require_content=True, usage_tracker=usage_tracker
            )
            if adapter_error:
                results[url] = {"error": f"Adapter fetch failed: {adapter_error}"}
                continue
            summary_info = cache.get_summary(url)

        if not summary_info:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        status = summary_info.get("summary_status", "unknown")
        summary = summary_info.get("summary")

        if status == "completed" and summary:
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": summary,
            }
        elif status == "processing":
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary is being generated... try again in a moment)",
                "status": "processing",
            }
        elif status == "failed":
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary generation failed)",
                "status": "failed",
            }
        else:
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary pending)",
                "status": status,
            }

    return results


def execute_get_relevant_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve relevant content chunks from cached URLs using RAG."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = _dedupe_preserve_order([_sanitize_url(u) for u in urls if u])
    query = args.get("query", "")
    max_chunks = args.get("max_chunks", 5)
    dense_weight = args.get("dense_weight", DEFAULT_HYBRID_DENSE_WEIGHT)
    min_relevance = args.get("min_relevance", DEFAULT_MIN_CHUNK_RELEVANCE)

    if not urls:
        return {"error": "No URLs provided."}
    if not query:
        return {"error": "Query is required for relevant content retrieval."}

    urls, rejected_results = _split_local_targets(urls)
    if not urls:
        return rejected_results

    cache = _get_cache()
    results = dict(rejected_results)
    usage_tracker = args.get("summarization_tracker")

    for url in urls:
        cached, adapter_error = _ensure_adapter_cached(
            cache=cache,
            url=url,
            query=query,
            max_links=max_chunks,
            require_content=True,
            usage_tracker=usage_tracker,
        )
        if adapter_error and not cached:
            results[url] = {"error": f"Adapter fetch failed: {adapter_error}"}
            continue

        if not cached:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        cache_id = cached["id"]
        content = cached["content"]

        if not content:
            if adapter_error:
                results[url] = {"error": f"Adapter fetch failed: {adapter_error}"}
                continue
            results[url] = {"error": "Cached content is empty."}
            continue

        try:
            vector_store = get_vector_store()
            embedding_model = vector_store.embedding_client.model

            # Ensure chunks are embedded
            has_embeddings = vector_store.has_chunk_embeddings(cache_id)
            has_for_model_method = getattr(
                vector_store, "has_chunk_embeddings_for_model", None
            )
            if callable(has_for_model_method):
                model_result = has_for_model_method(cache_id, embedding_model)
                if isinstance(model_result, bool):
                    has_embeddings = model_result

            if not has_embeddings:
                logger.debug(f"Generating chunk embeddings for {url}")
                chunks = chunk_text(content)
                stored = vector_store.store_chunk_embeddings(cache_id, chunks)
                if stored == 0:
                    raise Exception("Failed to store chunk embeddings")

            ranked_chunks = _search_relevant_chunks(
                vector_store=vector_store,
                cache_id=cache_id,
                query=query,
                max_chunks=max_chunks,
                dense_weight=dense_weight,
                min_relevance=min_relevance,
            )
            relevant = _select_diverse_chunks(ranked_chunks, max_chunks=max_chunks)

            if relevant:
                results[url] = {
                    "title": cached.get("title", ""),
                    "chunks": [
                        {
                            "text": chunk["text"],
                            "relevance": round(chunk["score"], 3),
                            "semantic_relevance": round(chunk["dense_score"], 3),
                            "lexical_relevance": round(chunk["lexical_score"], 3),
                        }
                        for chunk in relevant
                    ],
                    "chunk_count": len(relevant),
                }
            else:
                # No relevant chunks found - return truncated content as fallback
                results[url] = {
                    "title": cached.get("title", ""),
                    "note": "No highly relevant sections found. Returning content preview.",
                    "content_preview": content[:CONTENT_PREVIEW_SHORT_CHARS]
                    + ("..." if len(content) > CONTENT_PREVIEW_SHORT_CHARS else ""),
                }

        except Exception as e:
            logger.error(f"RAG retrieval failed for {url}: {e}")
            # Fallback: return truncated full content
            results[url] = {
                "title": cached.get("title", ""),
                "fallback": True,
                "note": f"Semantic search unavailable ({str(e)[:50]}). Returning content preview.",
                "content_preview": content[:CONTENT_PREVIEW_LONG_CHARS]
                + ("..." if len(content) > CONTENT_PREVIEW_LONG_CHARS else ""),
            }

    return results


def execute_get_full_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get full cached content for URLs."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = _dedupe_preserve_order([_sanitize_url(u) for u in urls if u])
    if not urls:
        return {"error": "No URLs provided."}

    urls, rejected_results = _split_local_targets(urls)
    if not urls:
        return rejected_results

    cache = _get_cache()
    results = dict(rejected_results)
    usage_tracker = args.get("summarization_tracker")

    for url in urls:
        cached, adapter_error = _ensure_adapter_cached(
            cache=cache, url=url, require_content=True, usage_tracker=usage_tracker
        )
        if adapter_error and not cached:
            results[url] = {"error": f"Adapter fetch failed: {adapter_error}"}
            continue

        if not cached:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        content = cached.get("content", "")
        if not content:
            if adapter_error:
                results[url] = {"error": f"Adapter fetch failed: {adapter_error}"}
                continue
            results[url] = {"error": "Cached content is empty."}
            continue

        results[url] = {
            "title": cached.get("title", ""),
            "content": content,
            "content_length": len(content),
        }

    return results


def execute_save_finding(args: Dict[str, Any]) -> Dict[str, Any]:
    """Save a research finding to persistent memory."""
    finding = args.get("finding", "").strip()
    if not finding:
        return {"error": "Finding text is required."}

    source_url = args.get("source_url")
    source_title = args.get("source_title")
    tags = args.get("tags", [])
    session_id = _normalize_session_id(args.get("session_id"))

    # Ensure tags is a list
    if isinstance(tags, str):
        tags = [tags]

    cache = _get_cache()
    finding_id = cache.save_finding(
        finding_text=finding,
        source_url=source_url,
        source_title=source_title,
        tags=tags,
        session_id=session_id,
    )

    # Try to embed for semantic search
    embedded = False
    try:
        vector_store = get_vector_store()
        embedded = vector_store.store_finding_embedding(finding_id, finding)
    except Exception as e:
        logger.warning(f"Finding embedding failed (will still be saved): {e}")

    return {
        "status": "saved",
        "finding_id": finding_id,
        "embedded": embedded,
        "note": "Finding saved to research memory"
        + (" with embedding" if embedded else " (without embedding - API unavailable)"),
    }


def execute_query_research_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search research memory for previously saved findings."""
    query = args.get("query", "").strip()
    if not query:
        return {"error": "Query is required."}

    limit = args.get("limit", RESEARCH_MEMORY_MAX_RESULTS)
    session_id = _normalize_session_id(args.get("session_id"))

    # Try semantic search first
    try:
        vector_store = get_vector_store()
        results = vector_store.search_findings(
            query,
            top_k=limit,
            session_id=session_id,
        )

        if results:
            return {
                "findings": [
                    {
                        "finding": finding["finding_text"],
                        "source_url": finding.get("source_url"),
                        "source_title": finding.get("source_title"),
                        "tags": finding.get("tags", []),
                        "relevance": round(score, 3),
                        "saved_at": finding.get("created_at"),
                    }
                    for finding, score in results
                ],
                "count": len(results),
                "search_type": "semantic",
            }
        else:
            # No results from semantic search, try returning recent findings
            cache = _get_cache()
            findings = cache.get_all_findings(limit=limit, session_id=session_id)

            if findings:
                return {
                    "findings": [
                        {
                            "finding": f["finding_text"],
                            "source_url": f.get("source_url"),
                            "source_title": f.get("source_title"),
                            "tags": f.get("tags", []),
                            "saved_at": f.get("created_at"),
                        }
                        for f in findings
                    ],
                    "count": len(findings),
                    "note": "No semantically relevant findings. Showing recent findings.",
                    "search_type": "recent",
                }
            else:
                no_results_note = (
                    "No findings in this session's research memory yet. "
                    "Use save_finding to store discoveries."
                    if session_id
                    else "No findings in research memory yet. Use save_finding to store discoveries."
                )
                return {
                    "findings": [],
                    "note": no_results_note,
                }

    except Exception as e:
        logger.warning(f"Semantic search unavailable: {e}")
        # Fallback to returning recent findings
        cache = _get_cache()
        findings = cache.get_all_findings(limit=limit, session_id=session_id)

        return {
            "findings": [
                {
                    "finding": f["finding_text"],
                    "source_url": f.get("source_url"),
                    "source_title": f.get("source_title"),
                    "tags": f.get("tags", []),
                    "saved_at": f.get("created_at"),
                }
                for f in findings
            ],
            "count": len(findings),
            "note": f"Semantic search unavailable ({str(e)[:30]}). Showing recent findings.",
            "search_type": "fallback",
        }

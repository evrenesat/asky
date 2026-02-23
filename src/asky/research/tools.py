"""Research mode tool executors."""

import difflib
import logging
import re
from typing import Any, Dict, List, Optional

from asky.config import (
    RESEARCH_MAX_LINKS_PER_URL,
    RESEARCH_MAX_RELEVANT_LINKS,
    RESEARCH_MEMORY_MAX_RESULTS,
)
from asky.retrieval import fetch_url_document
from asky.research.cache import ResearchCache
from asky.research.chunker import chunk_text
from asky.research.sections import (
    MIN_SUMMARIZE_SECTION_CHARS,
    build_section_index,
    get_listable_sections,
    match_section_strict,
    slice_section_content,
)
from asky.research.vector_store import get_vector_store
from asky.summarization import _summarize_content
from asky.url_utils import is_local_filesystem_target, sanitize_url

logger = logging.getLogger(__name__)
DEFAULT_HYBRID_DENSE_WEIGHT = 0.75
DEFAULT_MIN_CHUNK_RELEVANCE = 0.15
MAX_RAG_CANDIDATE_MULTIPLIER = 3
CHUNK_DIVERSITY_SIMILARITY_THRESHOLD = 0.92
CONTENT_PREVIEW_SHORT_CHARS = 2000
CONTENT_PREVIEW_LONG_CHARS = 3000
CORPUS_CACHE_HANDLE_PREFIX = "corpus://cache/"
SECTION_REF_FRAGMENT_PREFIX = "#section="
LOCAL_TARGET_UNSUPPORTED_ERROR = (
    "Local filesystem targets are not supported by this tool. "
    "Use an explicit local-source tool instead."
)
SECTION_DETAIL_DEFAULT = "balanced"
SECTION_DETAIL_OPTIONS = {"compact", "balanced", "max"}
SECTION_SUMMARY_PROMPTS: Dict[str, str] = {
    "compact": (
        "Summarize this section concisely with high signal bullets and key claims."
    ),
    "balanced": (
        "Produce a comprehensive section summary with argument flow, concrete examples, "
        "caveats, and implications."
    ),
    "max": (
        "Produce an exhaustive section summary with deep structural coverage, "
        "sub-arguments, evidence, caveats, and practical implications."
    ),
}
SECTION_SUMMARY_MAX_OUTPUT_CHARS: Dict[str, int] = {
    "compact": 2800,
    "balanced": 7200,
    "max": 12000,
}


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
                "section_id": {
                    "type": "string",
                    "description": "Optional section scope from list_sections output.",
                },
                "section_ref": {
                    "type": "string",
                    "description": "Optional section reference (corpus://cache/<id>#section=<section-id>).",
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
                "section_id": {
                    "type": "string",
                    "description": "Optional section scope from list_sections output.",
                },
                "section_ref": {
                    "type": "string",
                    "description": "Optional section reference (corpus://cache/<id>#section=<section-id>).",
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
    {
        "name": "list_sections",
        "description": """List detected section headings for local corpus sources.
Use this to inspect available section titles before requesting a deep section summary.
This tool only supports local corpus handles/sources, not web URLs.""",
        "system_prompt_guideline": "For local corpus research, call this first to discover exact section titles.",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Optional source selector (prefer corpus://cache/<id>).",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional source selectors for batch listing.",
                },
                "include_toc": {
                    "type": "boolean",
                    "description": "When true, include TOC/micro heading rows in addition to canonical body sections.",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "summarize_section",
        "description": """Summarize one specific section from a local corpus source.
Use exact section titles from list_sections for reliable matching.
This tool only supports local corpus handles/sources, not web URLs.""",
        "system_prompt_guideline": "Use after list_sections to produce deep section-bounded summaries from local corpus sources.",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source selector (prefer corpus://cache/<id>). Legacy /<section-id> suffix is accepted.",
                },
                "section_query": {
                    "type": "string",
                    "description": "Section title query to match strictly (fallback when section_id/section_ref is omitted).",
                },
                "section_id": {
                    "type": "string",
                    "description": "Exact section ID from list_sections output.",
                },
                "section_ref": {
                    "type": "string",
                    "description": "Section reference from list_sections output (corpus://cache/<id>#section=<section-id>).",
                },
                "detail": {
                    "type": "string",
                    "description": "Summary detail profile: balanced|max|compact.",
                    "default": SECTION_DETAIL_DEFAULT,
                },
                "max_chunks": {
                    "type": "integer",
                    "description": "Optional chunk limit for section slicing before summarization.",
                },
            },
            "required": [],
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
        "list_sections",
        "summarize_section",
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


def _extract_source_targets(
    args: Dict[str, Any],
    *,
    allow_corpus_urls: bool = False,
) -> List[str]:
    """Extract requested source identifiers from tool args."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        urls = []

    if urls:
        return _dedupe_preserve_order([_sanitize_url(u) for u in urls if u])

    if allow_corpus_urls:
        corpus_urls = args.get("corpus_urls", [])
        if isinstance(corpus_urls, str):
            corpus_urls = [corpus_urls]
        if isinstance(corpus_urls, list):
            return _dedupe_preserve_order(
                [_sanitize_url(u) for u in corpus_urls if u]
            )

    return []


def _format_corpus_handle(cache_id: int) -> str:
    return f"{CORPUS_CACHE_HANDLE_PREFIX}{int(cache_id)}"


def _format_section_ref(cache_id: int, section_id: str) -> str:
    return f"{_format_corpus_handle(cache_id)}{SECTION_REF_FRAGMENT_PREFIX}{section_id}"


def _parse_corpus_source_token(target: str) -> Dict[str, Any]:
    """Parse corpus source tokens with optional section scoping."""
    normalized = _sanitize_url(target)
    payload: Dict[str, Any] = {
        "source": normalized,
        "is_corpus": False,
        "cache_id": None,
        "section_id": None,
        "format_detected": None,
        "error": None,
    }
    if not normalized.startswith(CORPUS_CACHE_HANDLE_PREFIX):
        return payload

    payload["is_corpus"] = True
    suffix = normalized[len(CORPUS_CACHE_HANDLE_PREFIX) :].strip()
    if not suffix:
        payload["error"] = (
            "Invalid corpus handle format. Accepted formats: "
            "corpus://cache/<id>, corpus://cache/<id>#section=<section-id>, "
            "or legacy corpus://cache/<id>/<section-id>."
        )
        return payload

    section_token = ""
    if SECTION_REF_FRAGMENT_PREFIX in suffix:
        cache_token, section_token = suffix.split(SECTION_REF_FRAGMENT_PREFIX, 1)
        payload["format_detected"] = "section_ref"
    elif "/" in suffix:
        cache_token, section_token = suffix.split("/", 1)
        payload["format_detected"] = "legacy_path"
    else:
        cache_token = suffix
        payload["format_detected"] = "base"

    cache_token = cache_token.strip().strip("/")
    if not cache_token.isdigit():
        payload["error"] = (
            "Invalid corpus handle format. Accepted formats: "
            "corpus://cache/<id>, corpus://cache/<id>#section=<section-id>, "
            "or legacy corpus://cache/<id>/<section-id>."
        )
        return payload

    payload["cache_id"] = int(cache_token)
    clean_section = section_token.strip()
    if clean_section:
        clean_section = clean_section.lstrip("/").strip()
        if payload["format_detected"] == "legacy_path":
            if "#" in clean_section:
                clean_section = clean_section.split("#", 1)[0].strip()
            if "?" in clean_section:
                clean_section = clean_section.split("?", 1)[0].strip()
        if not clean_section:
            payload["error"] = (
                "Section identifier is empty. Use <id>#section=<section-id> "
                "or provide a non-empty legacy /<section-id> suffix."
            )
            return payload
        payload["section_id"] = clean_section

    return payload


def _resolve_cached_source(
    cache: ResearchCache,
    source: str,
) -> tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """Resolve a URL or corpus handle to a cached entry."""
    parsed_corpus = _parse_corpus_source_token(source)
    if parsed_corpus.get("is_corpus"):
        if parsed_corpus.get("error"):
            return None, str(parsed_corpus.get("error")), parsed_corpus

        handle_cache_id = int(parsed_corpus.get("cache_id") or 0)
        cached = cache.get_cached_by_id(handle_cache_id)
        if not cached:
            return (
                None,
                "Not cached. Use preload/ingestion before querying this handle.",
                parsed_corpus,
            )
        return cached, None, parsed_corpus

    if is_local_filesystem_target(source):
        return None, LOCAL_TARGET_UNSUPPORTED_ERROR, parsed_corpus

    cached = cache.get_cached(source)
    if not cached:
        return None, "Not cached. Use extract_links first to cache this URL.", parsed_corpus
    return cached, None, parsed_corpus


def _normalize_session_id(raw_session_id: Any) -> Optional[str]:
    """Normalize optional session identifiers from tool arguments."""
    if raw_session_id is None:
        return None
    session_id = str(raw_session_id).strip()
    return session_id or None


def _normalize_section_detail(raw_detail: Any) -> str:
    detail = str(raw_detail or SECTION_DETAIL_DEFAULT).strip().lower()
    if detail not in SECTION_DETAIL_OPTIONS:
        return SECTION_DETAIL_DEFAULT
    return detail


def _extract_section_sources(args: Dict[str, Any]) -> List[str]:
    """Extract section-source selectors with deterministic priority."""
    sources: List[str] = []

    single_source = args.get("source")
    if isinstance(single_source, str) and single_source.strip():
        sources.append(_sanitize_url(single_source))

    multi_sources = args.get("sources", [])
    if isinstance(multi_sources, str):
        multi_sources = [multi_sources]
    if isinstance(multi_sources, list):
        for item in multi_sources:
            token = str(item or "").strip()
            if token:
                sources.append(_sanitize_url(token))

    if sources:
        return _dedupe_preserve_order(sources)
    return _extract_source_targets(args, allow_corpus_urls=True)


def _looks_like_web_url(source: str) -> bool:
    lowered = source.lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _resolve_local_section_source(
    cache: ResearchCache,
    source: str,
    *,
    research_source_mode: Optional[str],
) -> tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    """Resolve local section source from handle/local target and enforce mode constraints."""
    if _looks_like_web_url(source):
        return (
            None,
            "Web URLs are not supported by this tool. Use local corpus handles (corpus://cache/<id>).",
            _parse_corpus_source_token(source),
        )

    parsed_corpus = _parse_corpus_source_token(source)
    if parsed_corpus.get("is_corpus"):
        if parsed_corpus.get("error"):
            return (
                None,
                str(parsed_corpus.get("error")),
                parsed_corpus,
            )
        handle_cache_id = int(parsed_corpus.get("cache_id") or 0)
        cached = cache.get_cached_by_id(handle_cache_id)
        if not cached:
            return (
                None,
                "Not cached. Ingest the local corpus first, then retry with this handle.",
                parsed_corpus,
            )
        return cached, None, parsed_corpus

    mode = str(research_source_mode or "").strip().lower()
    if mode == "mixed":
        return (
            None,
            "In mixed mode, only corpus handles are accepted for section tools (corpus://cache/<id>).",
            parsed_corpus,
        )

    if is_local_filesystem_target(source):
        cached = cache.get_cached(source)
        if not cached:
            return (
                None,
                "Local source not cached. Ingest this source first and use its corpus handle.",
                parsed_corpus,
            )
        return cached, None, parsed_corpus

    return (
        None,
        "Unsupported section source. Use corpus://cache/<id> from the local corpus cache.",
        parsed_corpus,
    )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    token = str(value).strip().lower()
    return token in {"1", "true", "yes", "on"}


def _normalize_section_id(raw_value: Any) -> Optional[str]:
    if raw_value is None:
        return None
    section_id = str(raw_value).strip()
    return section_id or None


def _resolve_section_scope(
    *,
    source: str,
    parsed_source: Dict[str, Any],
    section_id_arg: Any,
    section_ref_arg: Any,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve section scope from explicit args, section refs, or legacy source syntax."""
    explicit_section_ref = _normalize_section_id(section_ref_arg)
    explicit_section_id = _normalize_section_id(section_id_arg)

    if explicit_section_ref:
        parsed_ref = _parse_corpus_source_token(explicit_section_ref)
        if not parsed_ref.get("is_corpus"):
            return (
                None,
                "section_ref must use corpus format: corpus://cache/<id>#section=<section-id>.",
            )
        if parsed_ref.get("error"):
            return None, str(parsed_ref.get("error"))
        ref_section_id = _normalize_section_id(parsed_ref.get("section_id"))
        if not ref_section_id:
            return (
                None,
                "section_ref is missing section id. Use corpus://cache/<id>#section=<section-id>.",
            )
        if parsed_source.get("is_corpus"):
            source_cache_id = int(parsed_source.get("cache_id") or 0)
            ref_cache_id = int(parsed_ref.get("cache_id") or 0)
            if source_cache_id and ref_cache_id and source_cache_id != ref_cache_id:
                return (
                    None,
                    "section_ref cache ID does not match source cache ID.",
                )
        return ref_section_id, None

    if explicit_section_id:
        return explicit_section_id, None

    source_section_id = _normalize_section_id(parsed_source.get("section_id"))
    if source_section_id:
        return source_section_id, None
    return None, None


def _build_section_suggestions(
    section_index: Dict[str, Any],
    *,
    cache_id: Optional[int],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    for section in get_listable_sections(section_index, include_toc=False)[: max(1, int(limit))]:
        section_id = str(section.get("id", "") or "")
        entry: Dict[str, Any] = {
            "id": section_id,
            "title": str(section.get("title", "") or ""),
        }
        if cache_id is not None and section_id:
            entry["section_ref"] = _format_section_ref(cache_id, section_id)
        suggestions.append(entry)
    return suggestions


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
    del query
    del operation

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


def _simple_query_match_score(query: str, text: str) -> float:
    query_norm = str(query or "").strip().lower()
    text_norm = str(text or "").strip().lower()
    if not query_norm or not text_norm:
        return 0.0

    if query_norm in text_norm:
        return 1.0

    token_pattern = re.compile(r"[a-z0-9]+")
    query_tokens = set(token_pattern.findall(query_norm))
    text_tokens = set(token_pattern.findall(text_norm))
    overlap = (
        len(query_tokens & text_tokens) / len(query_tokens)
        if query_tokens
        else 0.0
    )
    sequence_similarity = difflib.SequenceMatcher(
        None,
        query_norm,
        text_norm[: max(len(query_norm) * 8, 256)],
    ).ratio()
    return min((0.62 * overlap) + (0.38 * sequence_similarity), 1.0)


def _rank_section_chunks_direct(
    *,
    content: str,
    query: str,
    max_chunks: int,
    min_relevance: float,
) -> List[Dict[str, Any]]:
    """Rank section-scoped chunks without relying on full-document vector indexes."""
    ranked: List[Dict[str, Any]] = []
    for _, chunk_text_value in chunk_text(content):
        score = _simple_query_match_score(query, chunk_text_value)
        if score < float(min_relevance):
            continue
        ranked.append(
            {
                "text": chunk_text_value,
                "score": score,
                "dense_score": score,
                "lexical_score": score,
            }
        )

    ranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return ranked[: max(1, int(max_chunks) * MAX_RAG_CANDIDATE_MULTIPLIER)]


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

    for url in urls:
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
    urls = _extract_source_targets(args, allow_corpus_urls=True)
    query = args.get("query", "")
    max_chunks = args.get("max_chunks", 5)
    dense_weight = args.get("dense_weight", DEFAULT_HYBRID_DENSE_WEIGHT)
    min_relevance = args.get("min_relevance", DEFAULT_MIN_CHUNK_RELEVANCE)
    section_id_arg = args.get("section_id")
    section_ref_arg = args.get("section_ref")

    if not urls:
        return {"error": "No sources provided. Specify 'urls' or 'corpus_urls'."}
    if not query:
        return {"error": "Query is required for relevant content retrieval."}

    cache = _get_cache()
    results: Dict[str, Any] = {}

    for source in urls:
        cached, lookup_error, parsed_source = _resolve_cached_source(
            cache=cache,
            source=source,
        )
        if lookup_error:
            results[source] = {"error": lookup_error}
            continue

        cache_id = int(cached.get("id", 0) or 0)
        content = str(cached.get("content", "") or "")

        if not content:
            results[source] = {"error": "Cached content is empty."}
            continue

        requested_section_id, scope_error = _resolve_section_scope(
            source=source,
            parsed_source=parsed_source,
            section_id_arg=section_id_arg,
            section_ref_arg=section_ref_arg,
        )
        if scope_error:
            results[source] = {"error": scope_error}
            continue

        content_for_retrieval = content
        scoped_section_payload: Optional[Dict[str, Any]] = None
        if requested_section_id:
            if not parsed_source.get("is_corpus"):
                results[source] = {
                    "error": (
                        "Section-scoped retrieval only supports local corpus handles. "
                        "Use corpus://cache/<id> with section_id or section_ref."
                    )
                }
                continue

            section_index = build_section_index(content)
            slice_payload = slice_section_content(
                content,
                section_index,
                requested_section_id,
            )
            if slice_payload.get("error"):
                results[source] = {
                    "error": str(slice_payload.get("error")),
                    "requested_section_id": requested_section_id,
                    "suggestions": _build_section_suggestions(
                        section_index,
                        cache_id=cache_id,
                    ),
                }
                continue

            content_for_retrieval = str(slice_payload.get("content", "") or "").strip()
            if not content_for_retrieval:
                results[source] = {
                    "error": "Matched section has no content.",
                    "requested_section_id": requested_section_id,
                }
                continue

            resolved_section = dict(slice_payload.get("section") or {})
            resolved_section_id = str(
                slice_payload.get("resolved_section_id", requested_section_id)
                or requested_section_id
            )
            scoped_section_payload = {
                "requested_section_id": str(
                    slice_payload.get("requested_section_id", requested_section_id)
                    or requested_section_id
                ),
                "resolved_section_id": resolved_section_id,
                "auto_promoted": bool(slice_payload.get("auto_promoted")),
                "section_ref": _format_section_ref(cache_id, resolved_section_id),
                "title": str(resolved_section.get("title", "") or ""),
                "char_count": int(resolved_section.get("char_count", 0) or 0),
            }

        try:
            if scoped_section_payload:
                ranked_chunks = _rank_section_chunks_direct(
                    content=content_for_retrieval,
                    query=query,
                    max_chunks=max_chunks,
                    min_relevance=min_relevance,
                )
            else:
                vector_store = get_vector_store()
                embedding_model = vector_store.embedding_client.model

                has_embeddings = vector_store.has_chunk_embeddings(cache_id)
                has_for_model_method = getattr(
                    vector_store, "has_chunk_embeddings_for_model", None
                )
                if callable(has_for_model_method):
                    model_result = has_for_model_method(cache_id, embedding_model)
                    if isinstance(model_result, bool):
                        has_embeddings = model_result

                if not has_embeddings:
                    logger.debug(f"Generating chunk embeddings for {source}")
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
                payload: Dict[str, Any] = {
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
                if scoped_section_payload:
                    payload["section"] = scoped_section_payload
                results[source] = payload
            else:
                payload = {
                    "title": cached.get("title", ""),
                    "note": "No highly relevant sections found. Returning content preview.",
                    "content_preview": content_for_retrieval[:CONTENT_PREVIEW_SHORT_CHARS]
                    + (
                        "..."
                        if len(content_for_retrieval) > CONTENT_PREVIEW_SHORT_CHARS
                        else ""
                    ),
                }
                if scoped_section_payload:
                    payload["section"] = scoped_section_payload
                results[source] = payload

        except Exception as e:
            logger.error(f"RAG retrieval failed for {source}: {e}")
            payload = {
                "title": cached.get("title", ""),
                "fallback": True,
                "note": f"Semantic search unavailable ({str(e)[:50]}). Returning content preview.",
                "content_preview": content_for_retrieval[:CONTENT_PREVIEW_LONG_CHARS]
                + (
                    "..."
                    if len(content_for_retrieval) > CONTENT_PREVIEW_LONG_CHARS
                    else ""
                ),
            }
            if scoped_section_payload:
                payload["section"] = scoped_section_payload
            results[source] = payload

    return results


def execute_get_full_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get full cached content for URLs."""
    urls = _extract_source_targets(args, allow_corpus_urls=True)
    section_id_arg = args.get("section_id")
    section_ref_arg = args.get("section_ref")
    if not urls:
        return {"error": "No sources provided. Specify 'urls' or 'corpus_urls'."}

    cache = _get_cache()
    results: Dict[str, Any] = {}

    for source in urls:
        cached, lookup_error, parsed_source = _resolve_cached_source(
            cache=cache,
            source=source,
        )
        if lookup_error:
            results[source] = {"error": lookup_error}
            continue

        cache_id = int(cached.get("id", 0) or 0)
        content = str(cached.get("content", "") or "")
        if not content:
            results[source] = {"error": "Cached content is empty."}
            continue

        requested_section_id, scope_error = _resolve_section_scope(
            source=source,
            parsed_source=parsed_source,
            section_id_arg=section_id_arg,
            section_ref_arg=section_ref_arg,
        )
        if scope_error:
            results[source] = {"error": scope_error}
            continue

        payload: Dict[str, Any] = {
            "title": cached.get("title", ""),
            "content": content,
            "content_length": len(content),
        }
        if requested_section_id:
            if not parsed_source.get("is_corpus"):
                results[source] = {
                    "error": (
                        "Section-scoped full content only supports local corpus handles. "
                        "Use corpus://cache/<id> with section_id or section_ref."
                    )
                }
                continue

            section_index = build_section_index(content)
            slice_payload = slice_section_content(
                content,
                section_index,
                requested_section_id,
            )
            if slice_payload.get("error"):
                results[source] = {
                    "error": str(slice_payload.get("error")),
                    "requested_section_id": requested_section_id,
                    "suggestions": _build_section_suggestions(
                        section_index,
                        cache_id=cache_id,
                    ),
                }
                continue

            section_text = str(slice_payload.get("content", "") or "").strip()
            if not section_text:
                results[source] = {
                    "error": "Matched section has no content.",
                    "requested_section_id": requested_section_id,
                }
                continue

            resolved_section = dict(slice_payload.get("section") or {})
            resolved_section_id = str(
                slice_payload.get("resolved_section_id", requested_section_id)
                or requested_section_id
            )
            payload["content"] = section_text
            payload["content_length"] = len(section_text)
            payload["section"] = {
                "requested_section_id": str(
                    slice_payload.get("requested_section_id", requested_section_id)
                    or requested_section_id
                ),
                "resolved_section_id": resolved_section_id,
                "auto_promoted": bool(slice_payload.get("auto_promoted")),
                "section_ref": _format_section_ref(cache_id, resolved_section_id),
                "title": str(resolved_section.get("title", "") or ""),
                "char_count": int(resolved_section.get("char_count", 0) or 0),
            }

        results[source] = payload

    return results


def execute_list_sections(args: Dict[str, Any]) -> Dict[str, Any]:
    """List detected section headings for local corpus sources."""
    sources = _extract_section_sources(args)
    if not sources:
        return {"error": "No sources provided. Specify 'source', 'sources', or 'corpus_urls'."}

    cache = _get_cache()
    source_mode = str(args.get("research_source_mode", "") or "").strip().lower()
    include_toc = _coerce_bool(args.get("include_toc"))
    results: Dict[str, Any] = {}

    for source in sources:
        cached, lookup_error, _parsed_source = _resolve_local_section_source(
            cache=cache,
            source=source,
            research_source_mode=source_mode,
        )
        if lookup_error:
            results[source] = {"error": lookup_error}
            continue

        content = str(cached.get("content", "") or "")
        if not content.strip():
            results[source] = {"error": "Cached content is empty."}
            continue

        section_index = build_section_index(content)
        sections = get_listable_sections(section_index, include_toc=include_toc)
        cache_id = int(cached["id"])
        rows: List[Dict[str, Any]] = []
        for section in sections:
            section_id = str(section.get("id", "") or "")
            row: Dict[str, Any] = {
                "id": section_id,
                "title": str(section.get("title", "") or ""),
                "char_count": int(section.get("char_count", 0) or 0),
                "section_ref": _format_section_ref(cache_id, section_id),
            }
            if include_toc:
                row["is_toc"] = bool(section.get("is_toc"))
            rows.append(row)

        results[source] = {
            "title": str(cached.get("title", "") or ""),
            "section_count": len(rows),
            "all_section_count": len(list(section_index.get("sections") or [])),
            "sections": rows,
        }

    return results


def execute_summarize_section(args: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize a strict-matched section from one local corpus source."""
    sources = _extract_section_sources(args)
    explicit_section_ref = _normalize_section_id(args.get("section_ref"))
    if not sources and explicit_section_ref:
        parsed_ref = _parse_corpus_source_token(explicit_section_ref)
        if parsed_ref.get("is_corpus") and not parsed_ref.get("error") and parsed_ref.get("cache_id"):
            sources = [_format_corpus_handle(int(parsed_ref["cache_id"]))]
        else:
            return {
                "error": (
                    "section_ref must use corpus format: "
                    "corpus://cache/<id>#section=<section-id>."
                )
            }

    if not sources:
        return {"error": "No source provided. Specify 'source' or 'corpus_urls'."}
    if len(sources) > 1:
        return {
            "error": (
                "summarize_section requires exactly one source. "
                "Call list_sections first and pass one corpus://cache/<id> source."
            )
        }

    source = sources[0]
    cache = _get_cache()
    source_mode = str(args.get("research_source_mode", "") or "").strip().lower()
    cached, lookup_error, parsed_source = _resolve_local_section_source(
        cache=cache,
        source=source,
        research_source_mode=source_mode,
    )
    if lookup_error:
        return {"error": lookup_error, "source": source}

    content = str(cached.get("content", "") or "")
    if not content.strip():
        return {"error": "Cached content is empty.", "source": source}

    cache_id = int(cached["id"])
    canonical_source = _format_corpus_handle(cache_id)
    section_index = build_section_index(content)
    sections = get_listable_sections(section_index, include_toc=False)
    if not sections:
        return {"error": "No sections detected for this source.", "source": source}

    requested_section_id, scope_error = _resolve_section_scope(
        source=source,
        parsed_source=parsed_source,
        section_id_arg=args.get("section_id"),
        section_ref_arg=args.get("section_ref"),
    )
    if scope_error:
        return {"error": scope_error, "source": source}
    section_query = str(args.get("section_query", "") or "").strip()

    confidence = 1.0
    suggestions = _build_section_suggestions(section_index, cache_id=cache_id)

    if not requested_section_id:
        if not section_query:
            return {
                "error": "section_ref, section_id, or section_query is required.",
                "source": source,
                "suggestions": suggestions,
            }
        match_payload = match_section_strict(section_query, section_index)
        if not match_payload.get("matched"):
            raw_suggestions = list(match_payload.get("suggestions") or [])
            enriched_suggestions: List[Dict[str, Any]] = []
            for item in raw_suggestions:
                section_id = str(item.get("id", "") or "")
                row = dict(item)
                if section_id:
                    row["section_ref"] = _format_section_ref(cache_id, section_id)
                enriched_suggestions.append(row)
            return {
                "error": "No strict section match found.",
                "source": source,
                "confidence": float(match_payload.get("confidence", 0.0) or 0.0),
                "reason": str(match_payload.get("reason", "") or ""),
                "suggestions": enriched_suggestions,
            }
        matched_section = dict(match_payload.get("section") or {})
        requested_section_id = str(matched_section.get("id", "") or "")
        confidence = float(match_payload.get("confidence", 0.0) or 0.0)

    detail = _normalize_section_detail(args.get("detail"))
    max_chunks_raw = args.get("max_chunks")
    try:
        max_chunks = int(max_chunks_raw) if max_chunks_raw is not None else None
    except (TypeError, ValueError):
        return {
            "error": "max_chunks must be an integer.",
            "source": source,
        }
    slice_payload = slice_section_content(
        content,
        section_index,
        str(requested_section_id or ""),
        max_chunks=max_chunks,
    )
    if slice_payload.get("error"):
        return {
            "error": str(slice_payload["error"]),
            "source": source,
            "requested_section_id": requested_section_id,
            "suggestions": suggestions,
        }

    section_text = str(slice_payload.get("content", "") or "").strip()
    if not section_text:
        return {"error": "Matched section has no content.", "source": source}

    if len(section_text) < MIN_SUMMARIZE_SECTION_CHARS:
        resolved_section = dict(slice_payload.get("section") or {})
        resolved_section_id = str(
            slice_payload.get("resolved_section_id", requested_section_id)
            or requested_section_id
        )
        return {
            "error": (
                "Resolved section is too small to summarize reliably "
                f"({len(section_text)} chars)."
            ),
            "source": canonical_source,
            "requested_section_id": requested_section_id,
            "resolved_section_id": resolved_section_id,
            "auto_promoted": bool(slice_payload.get("auto_promoted")),
            "section": {
                "id": resolved_section_id,
                "title": str(resolved_section.get("title", "") or ""),
                "char_count": int(resolved_section.get("char_count", 0) or 0),
                "section_ref": _format_section_ref(cache_id, resolved_section_id),
            },
            "min_required_chars": MIN_SUMMARIZE_SECTION_CHARS,
            "suggestions": suggestions,
        }

    resolved_section = dict(slice_payload.get("section") or {})
    resolved_section_id = str(
        slice_payload.get("resolved_section_id", requested_section_id)
        or requested_section_id
    )
    requested_section_id = str(
        slice_payload.get("requested_section_id", requested_section_id)
        or requested_section_id
    )
    auto_promoted = bool(slice_payload.get("auto_promoted"))

    summary_prompt = (
        f"{SECTION_SUMMARY_PROMPTS[detail]}\n"
        f"Focus section title: {resolved_section.get('title', '')}\n"
        "Do not include unrelated section material."
    )
    summary = _summarize_content(
        content=section_text,
        prompt_template=summary_prompt,
        max_output_chars=SECTION_SUMMARY_MAX_OUTPUT_CHARS[detail],
        usage_tracker=args.get("summarization_tracker"),
    )

    return {
        "source": canonical_source,
        "title": str(cached.get("title", "") or ""),
        "section": {
            "id": resolved_section_id,
            "title": str(resolved_section.get("title", "")),
            "char_count": int(resolved_section.get("char_count", 0) or 0),
            "confidence": round(confidence, 3),
            "section_ref": _format_section_ref(cache_id, resolved_section_id),
        },
        "requested_section_id": requested_section_id,
        "resolved_section_id": resolved_section_id,
        "auto_promoted": auto_promoted,
        "detail": detail,
        "summary": summary,
        "section_text_chars": len(section_text),
        "truncated": bool(slice_payload.get("truncated")),
        "available_chunks": int(slice_payload.get("available_chunks", 0) or 0),
        "suggestions": suggestions,
    }


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

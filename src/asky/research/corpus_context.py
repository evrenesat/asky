"""Corpus-aware context extraction for shortlist query enrichment."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from asky.config import (
    SOURCE_SHORTLIST_CORPUS_LEAD_CHARS,
    SOURCE_SHORTLIST_CORPUS_MAX_KEYPHRASES,
    SOURCE_SHORTLIST_CORPUS_MAX_QUERY_TITLES,
    SOURCE_SHORTLIST_SNIPPET_CHARS,
)
from asky.research.shortlist_types import CandidateRecord, CorpusContext

logger = logging.getLogger(__name__)

KEYPHRASE_MIN_CHARS_FOR_CORPUS = 50

_FILENAME_EXTENSIONS = re.compile(
    r"\.(pdf|epub|txt|md|html|htm|json|csv)$", re.IGNORECASE
)
_PUNCTUATION_RUN = re.compile(r"[_\-]+")
_PAREN_SUFFIX = re.compile(r"\s*[\(\[].{0,60}[\)\]]$")


def _clean_document_title(title: str) -> str:
    """Convert a raw filename-style title into a readable title string.

    Strips file extensions, replaces underscores/hyphens with spaces,
    trims trailing parenthetical suffixes (e.g., author names, site names),
    and normalizes whitespace.
    """
    if not title:
        return title
    cleaned = _FILENAME_EXTENSIONS.sub("", title)
    cleaned = _PUNCTUATION_RUN.sub(" ", cleaned)
    cleaned = _PAREN_SUFFIX.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


def extract_corpus_context(
    local_payload: Dict[str, Any],
    cache: Any = None,
) -> Optional[CorpusContext]:
    """Extract corpus metadata from preloaded local documents.

    Reads titles and lead text from cached documents, extracts keyphrases
    using YAKE, and returns a CorpusContext for shortlist query enrichment.

    Args:
        local_payload: Output of preload_local_research_sources().
        cache: ResearchCache instance. If None, uses the singleton.

    Returns:
        CorpusContext with titles, keyphrases, and lead texts, or None
        if no documents were ingested.
    """
    if cache is None:
        from asky.research.cache import ResearchCache

        cache = ResearchCache()
    ingested = local_payload.get("ingested") or []
    if not ingested:
        return None

    titles: List[str] = []
    keyphrases: List[str] = []
    lead_texts: Dict[str, str] = {}
    source_handles: List[str] = []
    cache_ids: List[int] = []

    combined_lead = []

    for item in ingested:
        if not isinstance(item, dict):
            continue

        title = _clean_document_title(str(item.get("title", "") or "").strip())
        target = str(item.get("target", "") or "").strip()
        handle = str(item.get("source_handle", "") or "").strip()
        cache_id = item.get("source_id")

        if not target:
            continue

        content = None
        try:
            content = cache.get_content(target)
        except Exception:
            logger.debug("Failed to read cached content for %s", target, exc_info=True)

        if not content:
            if title:
                titles.append(title)
            if handle:
                source_handles.append(handle)
            if cache_id is not None:
                cache_ids.append(int(cache_id))
            continue

        lead = content[:SOURCE_SHORTLIST_CORPUS_LEAD_CHARS]
        lead_texts[target] = lead
        combined_lead.append(lead)

        if title:
            titles.append(title)
        if handle:
            source_handles.append(handle)
        if cache_id is not None:
            cache_ids.append(int(cache_id))

    if not titles and not combined_lead:
        return None

    if combined_lead:
        merged_text = "\n".join(combined_lead)
        if len(merged_text) >= KEYPHRASE_MIN_CHARS_FOR_CORPUS:
            from asky.research.source_shortlist import extract_keyphrases

            keyphrases = extract_keyphrases(merged_text)[
                :SOURCE_SHORTLIST_CORPUS_MAX_KEYPHRASES
            ]

    return CorpusContext(
        titles=titles,
        keyphrases=keyphrases,
        lead_texts=lead_texts,
        source_handles=source_handles,
        cache_ids=cache_ids,
    )


def build_corpus_enriched_queries(
    corpus_context: CorpusContext,
    user_query: str,
    user_keyphrases: Optional[List[str]] = None,
) -> List[str]:
    """Build search queries enriched with corpus metadata.

    Combines document titles and corpus-derived keyphrases with the user's
    query to produce more targeted search queries.

    Args:
        corpus_context: Extracted corpus metadata.
        user_query: The user's original query text.
        user_keyphrases: Keyphrases extracted from the user query.

    Returns:
        List of enriched search queries. Falls back to [user_query] if
        corpus provides no useful enrichment.
    """
    queries: List[str] = []
    top_corpus_kps = corpus_context.keyphrases[:5]
    kp_fragment = " ".join(top_corpus_kps) if top_corpus_kps else ""

    for title in corpus_context.titles[:SOURCE_SHORTLIST_CORPUS_MAX_QUERY_TITLES]:
        parts = [f'"{title}"']
        if kp_fragment:
            parts.append(kp_fragment)
        queries.append(" ".join(parts))

    if user_query and user_query.strip():
        enriched_parts = [user_query.strip()]
        if kp_fragment:
            enriched_parts.append(kp_fragment)
        queries.append(" ".join(enriched_parts))

    if not queries:
        return [user_query] if user_query else []

    return queries


def build_corpus_candidates(
    corpus_context: CorpusContext,
) -> List[CandidateRecord]:
    """Create CandidateRecord objects from corpus documents.

    Used in corpus-only mode (no web search) to inject local documents
    directly into the shortlist scoring pipeline.

    Args:
        corpus_context: Extracted corpus metadata.

    Returns:
        List of CandidateRecord with source_type="corpus" and pre-filled
        content from lead texts.
    """
    candidates: List[CandidateRecord] = []

    handles_by_target: Dict[str, str] = {}
    for idx, handle in enumerate(corpus_context.source_handles):
        targets = list(corpus_context.lead_texts.keys())
        if idx < len(targets):
            handles_by_target[targets[idx]] = handle

    for target, lead_text in corpus_context.lead_texts.items():
        handle = handles_by_target.get(target, target)
        title_idx = list(corpus_context.lead_texts.keys()).index(target)
        title = (
            corpus_context.titles[title_idx]
            if title_idx < len(corpus_context.titles)
            else ""
        )
        snippet = lead_text[:SOURCE_SHORTLIST_SNIPPET_CHARS]

        candidates.append(
            CandidateRecord(
                url=handle,
                source_type="corpus",
                normalized_url=handle,
                hostname="local",
                title=title,
                text=lead_text,
                snippet=snippet,
                fetched_content=lead_text,
            )
        )

    return candidates

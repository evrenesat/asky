"""Pre-LLM source shortlisting shared across chat modes."""

from __future__ import annotations

import inspect
import logging
import re
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)
from urllib.parse import urlsplit

import requests

from asky.config import (
    FETCH_TIMEOUT,
    SOURCE_SHORTLIST_DOC_LEAD_CHARS,
    SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE,
    SOURCE_SHORTLIST_ENABLE_STANDARD_MODE,
    SOURCE_SHORTLIST_ENABLED,
    SOURCE_SHORTLIST_KEYPHRASE_MIN_QUERY_CHARS,
    SOURCE_SHORTLIST_KEYPHRASE_TOP_K,
    SOURCE_SHORTLIST_MAX_CANDIDATES,
    SOURCE_SHORTLIST_MAX_FETCH_URLS,
    SOURCE_SHORTLIST_MAX_SCORING_CHARS,
    SOURCE_SHORTLIST_MIN_CONTENT_CHARS,
    SOURCE_SHORTLIST_NOISE_PATH_PENALTY,
    SOURCE_SHORTLIST_OVERLAP_BONUS_WEIGHT,
    SOURCE_SHORTLIST_QUERY_FALLBACK_CHARS,
    SOURCE_SHORTLIST_SAME_DOMAIN_BONUS,
    SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED,
    SOURCE_SHORTLIST_SEED_LINK_MAX_PAGES,
    SOURCE_SHORTLIST_SEED_LINKS_PER_PAGE,
    SOURCE_SHORTLIST_SEARCH_PHRASE_COUNT,
    SOURCE_SHORTLIST_SEARCH_RESULT_COUNT,
    SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS,
    SOURCE_SHORTLIST_SHORT_TEXT_PENALTY,
    SOURCE_SHORTLIST_SHORT_TEXT_THRESHOLD,
    SOURCE_SHORTLIST_SNIPPET_CHARS,
    SOURCE_SHORTLIST_TOP_K,
    USER_AGENT,
)
from asky.html import HTMLStripper
from asky.retrieval import fetch_url_document
from asky.research.shortlist_collect import collect_candidates
from asky.research.shortlist_score import resolve_scoring_queries, score_candidates
from asky.research.shortlist_types import (
    CandidateRecord,
    FetchExecutor,
    SearchExecutor,
    SeedLinkExtractor,
    ShortlistMetrics,
    StatusCallback,
    TraceCallback,
)
from asky.url_utils import normalize_url

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asky.research.embeddings import EmbeddingClient

_YAKE_MODULE: Optional[Any] = None
_YAKE_MODULE_LOADED = False

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
BARE_URL_PATTERN = re.compile(
    r"(?<![@\w])(?:www\.)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>\"']*)?"
)
TRAILING_URL_PUNCTUATION = ".,;:!?)]}>\"'"
WHITESPACE_PATTERN = re.compile(r"\s+")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
PATH_TOKEN_SPLIT_PATTERN = re.compile(r"[/._\-]+")
TRACKING_QUERY_KEYS = {
    "gclid",
    "fbclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "igshid",
    "intcmp",
    "abcmp",
    "componenteventparams",
    "acquisitiondata",
    "reftype",
}
NOISE_PATH_MARKERS = {
    "/tag/",
    "/category/",
    "/login",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/privacy",
    "/terms",
    "/cookie",
    "/subscribe",
    "/preference/",
    "/preferences/",
    "/account/",
    "/accounts/",
    "/edition/",
}
SEED_LINK_BLOCKED_HOST_PREFIXES = {
    "profile.",
    "support.",
    "accounts.",
    "account.",
    "id.",
}
SEED_LINK_BLOCKED_PATH_MARKERS = {
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/login",
    "/logout",
    "/account",
    "/accounts",
    "/preferences",
    "/preference",
    "/privacy",
    "/terms",
    "/cookie",
    "/subscribe",
}
IGNORED_SEED_LINK_CONTAINER_TAGS = {"header", "nav", "footer", "aside"}
REDIRECT_PROBE_PATH_MARKERS = {
    "/preference/edition/",
    "/signin",
    "/sign-in",
    "/login",
    "/accounts/",
    "/account/",
}
SAME_DOMAIN_BONUS_MIN_SIGNAL = 0.05
REDIRECT_LOOKUP_TIMEOUT_SECONDS = 6
MAX_REASON_COUNT = 4
MAX_SHORTLIST_CONTEXT_ITEMS = 5
MAX_SHORTLIST_CONTEXT_SNIPPET_CHARS = 420
MAX_TITLE_CHARS = 180
MAX_SEED_URL_ERROR_CHARS = 500


def extract_prompt_urls_and_query_text(user_prompt: str) -> Tuple[List[str], str]:
    """Extract URLs from prompt and return the remaining query text."""
    if not user_prompt:
        return [], ""

    seed_urls: List[str] = []
    for raw_url in URL_PATTERN.findall(user_prompt):
        cleaned_url = _normalize_seed_url(raw_url.rstrip(TRAILING_URL_PUNCTUATION))
        if cleaned_url:
            seed_urls.append(cleaned_url)

    prompt_without_http_urls = URL_PATTERN.sub(" ", user_prompt)
    for raw_url in BARE_URL_PATTERN.findall(prompt_without_http_urls):
        cleaned_url = _normalize_seed_url(raw_url.rstrip(TRAILING_URL_PUNCTUATION))
        if cleaned_url:
            seed_urls.append(cleaned_url)

    deduped_urls = _dedupe_preserve_order(seed_urls)
    query_without_http_urls = URL_PATTERN.sub(" ", user_prompt)
    query_text = _normalize_whitespace(BARE_URL_PATTERN.sub(" ", query_without_http_urls))
    return deduped_urls, query_text


def normalize_source_url(url: str) -> str:
    """Normalize URL to collapse duplicate variants and strip tracking params."""
    return normalize_url(url, tracking_query_keys=TRACKING_QUERY_KEYS)


def extract_keyphrases(query_text: str) -> List[str]:
    """Extract keyphrases with YAKE (fallbacks to token terms if unavailable)."""
    if not query_text:
        return []

    normalized_query = _normalize_whitespace(query_text)
    if len(normalized_query) < SOURCE_SHORTLIST_KEYPHRASE_MIN_QUERY_CHARS:
        return []

    yake_module = _get_yake_module()
    if yake_module is not None:
        try:
            extractor = yake_module.KeywordExtractor(
                n=3,
                top=SOURCE_SHORTLIST_KEYPHRASE_TOP_K,
            )
            keywords = extractor.extract_keywords(normalized_query)
            return _dedupe_preserve_order(
                [
                    _normalize_whitespace(keyword)
                    for keyword, _score in keywords
                    if keyword and keyword.strip()
                ]
            )[:SOURCE_SHORTLIST_KEYPHRASE_TOP_K]
        except Exception as exc:
            logger.debug("YAKE extraction failed, using fallback keyphrases: %s", exc)

    fallback = _dedupe_preserve_order(
        token.lower() for token in TOKEN_PATTERN.findall(normalized_query)
    )
    return fallback[:SOURCE_SHORTLIST_KEYPHRASE_TOP_K]


def build_search_query(query_text: str, keyphrases: Sequence[str]) -> str:
    """Build a compact search query from prompt text and keyphrases."""
    normalized_query = _normalize_whitespace(query_text)
    if keyphrases:
        selected = list(keyphrases[:SOURCE_SHORTLIST_SEARCH_PHRASE_COUNT])
        if selected:
            return " ".join(selected)
    return normalized_query


def shortlist_prompt_sources(
    user_prompt: str,
    research_mode: bool,
    search_executor: Optional[SearchExecutor] = None,
    fetch_executor: Optional[FetchExecutor] = None,
    embedding_client: Optional["EmbeddingClient"] = None,
    seed_link_extractor: Optional[SeedLinkExtractor] = None,
    status_callback: Optional[StatusCallback] = None,
    queries: Optional[List[str]] = None,
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    """Build a ranked shortlist of relevant sources without using an LLM."""
    total_start = time.perf_counter()
    metrics: ShortlistMetrics = {
        "search_calls": 0,
        "search_results": 0,
        "candidate_inputs": 0,
        "candidate_deduped": 0,
        "fetch_calls": 0,
        "fetch_success": 0,
        "fetch_short_text_skips": 0,
        "fetch_failures": 0,
        "fetch_canonical_dedupe_skips": 0,
        "seed_link_pages_attempted": 0,
        "seed_link_pages_success": 0,
        "seed_link_extractor_calls": 0,
        "seed_link_discovered": 0,
        "seed_link_added": 0,
        "seed_link_failures": 0,
        "embedding_query_calls": 0,
        "embedding_doc_calls": 0,
        "embedding_doc_count": 0,
    }

    if not _shortlist_enabled_for_mode(research_mode):
        logger.debug(
            "source_shortlist disabled for mode=%s in %.2fms",
            "research" if research_mode else "standard",
            _elapsed_ms(total_start),
        )
        return {
            "enabled": False,
            "seed_urls": [],
            "seed_url_documents": [],
            "fetched_count": 0,
            "query_text": "",
            "search_query": "",
            "search_queries": [],
            "keyphrases": [],
            "candidates": [],
            "warnings": [],
            "stats": {
                "metrics": metrics,
                "timings_ms": {
                    "parse": 0.0,
                    "collect": 0.0,
                    "fetch": 0.0,
                    "score": 0.0,
                    "total": _elapsed_ms(total_start),
                },
            },
            "trace": {
                "processed_candidates": [],
                "selected_candidates": [],
            },
        }

    _notify_status(status_callback, "Shortlist: parsing prompt")
    parse_start = time.perf_counter()
    seed_urls, query_text = extract_prompt_urls_and_query_text(user_prompt)
    keyphrases = extract_keyphrases(query_text)

    # If explicit queries provided (expansion), use them for search.
    # Otherwise fallback to single build_search_query.
    if queries:
        search_queries = queries
    else:
        search_queries = [build_search_query(query_text, keyphrases)]

    parse_ms = _elapsed_ms(parse_start)

    active_search_executor = search_executor or _default_search_executor
    active_fetch_executor = fetch_executor or _default_fetch_executor
    active_seed_link_extractor = seed_link_extractor or _default_seed_link_extractor

    search_executor_with_trace = _with_optional_trace_callback(
        executor=active_search_executor,
        trace_callback=trace_callback,
    )
    fetch_executor_with_trace = _with_optional_trace_callback(
        executor=active_fetch_executor,
        trace_callback=trace_callback,
    )
    seed_link_extractor_with_trace = _with_optional_trace_callback(
        executor=active_seed_link_extractor,
        trace_callback=trace_callback,
    )

    warnings: List[str] = []
    _notify_status(status_callback, "Shortlist: collecting candidates")
    collect_start = time.perf_counter()
    candidates = collect_candidates(
        seed_urls=seed_urls,
        search_queries=search_queries,
        search_executor=search_executor_with_trace,
        seed_link_extractor=seed_link_extractor_with_trace,
        warnings=warnings,
        metrics=metrics,
        seed_link_expansion_enabled=SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED,
        seed_link_max_pages=SOURCE_SHORTLIST_SEED_LINK_MAX_PAGES,
        seed_links_per_page=SOURCE_SHORTLIST_SEED_LINKS_PER_PAGE,
        search_with_seed_urls=SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS,
        search_result_count=SOURCE_SHORTLIST_SEARCH_RESULT_COUNT,
        max_candidates=SOURCE_SHORTLIST_MAX_CANDIDATES,
        max_title_chars=MAX_TITLE_CHARS,
        normalize_source_url=normalize_source_url,
        extract_path_tokens=_extract_path_tokens,
        normalize_whitespace=_normalize_whitespace,
        is_http_url=_is_http_url,
        is_blocked_seed_link=_is_blocked_seed_link,
        elapsed_ms=_elapsed_ms,
        logger=logger,
    )
    collect_ms = _elapsed_ms(collect_start)
    processed_candidates = [
        {
            "url": candidate.url,
            "normalized_url": candidate.normalized_url,
            "source_type": candidate.source_type,
            "hostname": candidate.hostname,
        }
        for candidate in candidates[:SOURCE_SHORTLIST_MAX_FETCH_URLS]
    ]

    if not candidates:
        _notify_status(status_callback, "Shortlist: no candidates found")
        logger.debug(
            "source_shortlist completed with no candidates mode=%s parse=%.2fms collect=%.2fms total=%.2fms metrics=%s warnings=%d",
            "research" if research_mode else "standard",
            parse_ms,
            collect_ms,
            _elapsed_ms(total_start),
            metrics,
            len(warnings),
        )
        return {
            "enabled": True,
            "seed_urls": seed_urls,
            "seed_url_documents": [],
            "fetched_count": 0,
            "query_text": query_text,
            "search_query": search_queries[0] if search_queries else "",
            "search_queries": search_queries,
            "keyphrases": keyphrases,
            "candidates": [],
            "warnings": warnings,
            "stats": {
                "metrics": metrics,
                "timings_ms": {
                    "parse": parse_ms,
                    "collect": collect_ms,
                    "fetch": 0.0,
                    "score": 0.0,
                    "total": _elapsed_ms(total_start),
                },
            },
            "trace": {
                "processed_candidates": processed_candidates,
                "selected_candidates": [],
            },
        }

    _notify_status(status_callback, "Shortlist: fetching source content")
    fetch_start = time.perf_counter()
    fetched_candidates = _fetch_candidate_content(
        candidates=candidates,
        seed_urls=seed_urls,
        fetch_executor=fetch_executor_with_trace,
        warnings=warnings,
        metrics=metrics,
    )
    seed_url_documents = _build_seed_url_documents(
        seed_urls=seed_urls,
        candidates=candidates,
    )
    fetch_ms = _elapsed_ms(fetch_start)

    if not fetched_candidates:
        _notify_status(status_callback, "Shortlist: no usable page content")
        logger.debug(
            "source_shortlist completed with no fetched candidates mode=%s parse=%.2fms collect=%.2fms fetch=%.2fms total=%.2fms metrics=%s warnings=%d",
            "research" if research_mode else "standard",
            parse_ms,
            collect_ms,
            fetch_ms,
            _elapsed_ms(total_start),
            metrics,
            len(warnings),
        )
        return {
            "enabled": True,
            "seed_urls": seed_urls,
            "seed_url_documents": seed_url_documents,
            "fetched_count": len(fetched_candidates),
            "query_text": query_text,
            "search_query": search_queries[0] if search_queries else "",
            "search_queries": search_queries,
            "keyphrases": keyphrases,
            "candidates": [],
            "warnings": warnings,
            "stats": {
                "metrics": metrics,
                "timings_ms": {
                    "parse": parse_ms,
                    "collect": collect_ms,
                    "fetch": fetch_ms,
                    "score": 0.0,
                    "total": _elapsed_ms(total_start),
                },
            },
            "trace": {
                "processed_candidates": processed_candidates,
                "selected_candidates": [],
            },
        }

    scoring_queries = resolve_scoring_queries(
        queries=queries,
        query_text=query_text,
        keyphrases=keyphrases,
        candidates=fetched_candidates,
        search_phrase_count=SOURCE_SHORTLIST_SEARCH_PHRASE_COUNT,
        query_fallback_chars=SOURCE_SHORTLIST_QUERY_FALLBACK_CHARS,
        normalize_whitespace=_normalize_whitespace,
    )
    _notify_status(status_callback, "Shortlist: ranking candidates")
    score_start = time.perf_counter()
    scored_candidates = score_candidates(
        candidates=fetched_candidates,
        scoring_queries=scoring_queries,
        keyphrases=keyphrases,
        seed_urls=seed_urls,
        embedding_client=embedding_client,
        warnings=warnings,
        metrics=metrics,
        normalize_source_url=normalize_source_url,
        is_noise_path=_is_noise_path,
        cosine_similarity=_cosine_similarity,
        get_embedding_client=_get_embedding_client,
        overlap_bonus_weight=SOURCE_SHORTLIST_OVERLAP_BONUS_WEIGHT,
        same_domain_bonus=SOURCE_SHORTLIST_SAME_DOMAIN_BONUS,
        same_domain_bonus_min_signal=SAME_DOMAIN_BONUS_MIN_SIGNAL,
        short_text_threshold=SOURCE_SHORTLIST_SHORT_TEXT_THRESHOLD,
        short_text_penalty=SOURCE_SHORTLIST_SHORT_TEXT_PENALTY,
        noise_path_penalty=SOURCE_SHORTLIST_NOISE_PATH_PENALTY,
        doc_lead_chars=SOURCE_SHORTLIST_DOC_LEAD_CHARS,
        max_reason_count=MAX_REASON_COUNT,
        logger=logger,
    )
    score_ms = _elapsed_ms(score_start)

    ranked = sorted(scored_candidates, key=lambda item: item.final_score, reverse=True)
    ranked = ranked[:SOURCE_SHORTLIST_TOP_K]

    shortlisted = []
    selected_candidates = []
    for rank, record in enumerate(ranked, start=1):
        shortlisted.append(
            {
                "rank": rank,
                "final_score": round(record.final_score, 4),
                "semantic_score": round(record.semantic_score, 4),
                "url": record.url,
                "normalized_url": record.normalized_url,
                "hostname": record.hostname,
                "title": record.title,
                "why_selected": record.why_selected[:MAX_REASON_COUNT],
                "snippet": record.snippet,
                "date": record.date,
                "source_type": record.source_type,
            }
        )
        selected_candidates.append(
            {
                "rank": rank,
                "final_score": round(record.final_score, 4),
                "url": record.url,
                "normalized_url": record.normalized_url,
                "source_type": record.source_type,
            }
        )

    _notify_status(
        status_callback,
        f"Shortlist: selected {len(shortlisted)} source(s)",
    )

    logger.debug(
        "source_shortlist completed mode=%s parse=%.2fms collect=%.2fms fetch=%.2fms score=%.2fms total=%.2fms seeds=%d query_len=%d keyphrases=%d shortlisted=%d metrics=%s warnings=%d",
        "research" if research_mode else "standard",
        parse_ms,
        collect_ms,
        fetch_ms,
        score_ms,
        _elapsed_ms(total_start),
        len(seed_urls),
        len(query_text),
        len(keyphrases),
        len(shortlisted),
        metrics,
        len(warnings),
    )

    return {
        "enabled": True,
        "seed_urls": seed_urls,
        "seed_url_documents": seed_url_documents,
        "fetched_count": len(fetched_candidates),
        "query_text": query_text,
        "search_query": search_queries[0] if search_queries else "",
        "search_queries": search_queries,
        "keyphrases": keyphrases,
        "candidates": shortlisted,
        "warnings": warnings,
        "stats": {
            "metrics": metrics,
            "timings_ms": {
                "parse": parse_ms,
                "collect": collect_ms,
                "fetch": fetch_ms,
                "score": score_ms,
                "total": _elapsed_ms(total_start),
            },
        },
        "trace": {
            "processed_candidates": processed_candidates,
            "selected_candidates": selected_candidates,
        },
    }


def format_shortlist_context(shortlist_payload: Dict[str, Any]) -> str:
    """Format shortlist payload into compact text suitable for prompt context."""
    candidates = shortlist_payload.get("candidates", [])
    if not candidates:
        return ""

    seed_urls = shortlist_payload.get("seed_urls", []) or []
    explicit_seed_url_set = {
        normalize_source_url(str(url))
        for url in seed_urls
        if normalize_source_url(str(url))
    }
    preferred_candidates: List[Dict[str, Any]] = []
    seen_candidate_urls = set()

    for item in candidates:
        normalized_item_url = normalize_source_url(str(item.get("url", "")))
        if not normalized_item_url:
            continue
        if normalized_item_url in explicit_seed_url_set:
            preferred_candidates.append(item)
            seen_candidate_urls.add(normalized_item_url)

    selected_candidates = preferred_candidates[:]
    for item in candidates[:MAX_SHORTLIST_CONTEXT_ITEMS]:
        normalized_item_url = normalize_source_url(str(item.get("url", "")))
        if normalized_item_url and normalized_item_url in seen_candidate_urls:
            continue
        selected_candidates.append(item)
        if normalized_item_url:
            seen_candidate_urls.add(normalized_item_url)

    lines: List[str] = []
    for item in selected_candidates:
        title = item.get("title") or item.get("url", "")
        score = item.get("final_score", 0.0)
        reasons = item.get("why_selected", [])
        snippet = _normalize_whitespace(item.get("snippet", ""))
        snippet = snippet[:MAX_SHORTLIST_CONTEXT_SNIPPET_CHARS]
        lines.append(
            "\n".join(
                [
                    f"{item.get('rank', '?')}. {title} (score={score:.3f})",
                    f"URL: {item.get('url', '')}",
                    f"Why: {'; '.join(reasons) if reasons else 'ranked by semantic relevance'}",
                    f"Snippet: {snippet}",
                ]
            )
        )
    return "\n\n".join(lines)


def _normalize_seed_url(raw_url: str) -> str:
    """Normalize raw URL-like prompt tokens into fetchable HTTP targets."""
    cleaned = _normalize_whitespace(raw_url)
    if not cleaned:
        return ""
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned
    return f"https://{cleaned}"


def _shortlist_enabled_for_mode(research_mode: bool) -> bool:
    """Return whether source shortlisting is enabled for the current chat mode."""
    if not SOURCE_SHORTLIST_ENABLED:
        return False
    if research_mode:
        return bool(SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE)
    return bool(SOURCE_SHORTLIST_ENABLE_STANDARD_MODE)


def _fetch_candidate_content(
    candidates: Sequence[CandidateRecord],
    seed_urls: Sequence[str],
    fetch_executor: FetchExecutor,
    warnings: List[str],
    metrics: Optional[ShortlistMetrics] = None,
) -> List[CandidateRecord]:
    """Fetch and extract main text for candidate URLs."""
    extracted: List[CandidateRecord] = []
    seen_canonical_urls = set()
    seed_url_set = set(seed_urls)
    for index, candidate in enumerate(candidates):
        should_fetch_for_scoring = index < SOURCE_SHORTLIST_MAX_FETCH_URLS
        should_fetch_seed_document = (
            candidate.source_type == "seed" and candidate.requested_url in seed_url_set
        )
        if not should_fetch_for_scoring and not should_fetch_seed_document:
            continue

        fetch_start = time.perf_counter()
        if metrics is not None:
            metrics["fetch_calls"] += 1

        payload = fetch_executor(candidate.url)
        fetch_elapsed = _elapsed_ms(fetch_start)
        warning_text = str(payload.get("warning", "") or "")
        candidate.fetch_warning = warning_text
        candidate.fetch_error = _extract_fetch_error(payload)
        candidate.fetched_content = _normalize_whitespace(str(payload.get("text", "")))
        candidate.final_url = str(payload.get("final_url", "") or "")

        fetched_title = _normalize_whitespace(str(payload.get("title", "")))
        if fetched_title:
            candidate.title = fetched_title[:MAX_TITLE_CHARS]
        if payload.get("date"):
            candidate.date = payload.get("date")
        if warning_text:
            warnings.append(warning_text)

        if not should_fetch_for_scoring:
            if metrics is not None and not candidate.fetched_content:
                metrics["fetch_failures"] += 1
            logger.debug(
                "source_shortlist seed fetch-only success url=%s text_len=%d elapsed=%.2fms",
                candidate.url,
                len(candidate.fetched_content),
                fetch_elapsed,
            )
            continue

        text = candidate.fetched_content
        if len(text) < SOURCE_SHORTLIST_MIN_CONTENT_CHARS:
            if metrics is not None:
                if text:
                    metrics["fetch_short_text_skips"] += 1
                else:
                    metrics["fetch_failures"] += 1
            logger.debug(
                "source_shortlist fetch skipped url=%s text_len=%d min_chars=%d elapsed=%.2fms warning=%s",
                candidate.url,
                len(text),
                SOURCE_SHORTLIST_MIN_CONTENT_CHARS,
                fetch_elapsed,
                warning_text,
            )
            continue

        candidate.title = candidate.title or _derive_title_from_url(candidate.url)
        _apply_canonical_url(candidate, payload)
        if candidate.normalized_url and candidate.normalized_url in seen_canonical_urls:
            if metrics is not None:
                metrics["fetch_canonical_dedupe_skips"] += 1
            logger.debug(
                "source_shortlist fetch canonical dedupe skip url=%s canonical=%s",
                candidate.url,
                candidate.normalized_url,
            )
            continue

        candidate.text = text[:SOURCE_SHORTLIST_MAX_SCORING_CHARS]
        candidate.snippet = candidate.text[:SOURCE_SHORTLIST_SNIPPET_CHARS]
        if metrics is not None:
            metrics["fetch_success"] += 1
        if candidate.normalized_url:
            seen_canonical_urls.add(candidate.normalized_url)
        logger.debug(
            "source_shortlist fetch success url=%s text_len=%d title_len=%d elapsed=%.2fms source_type=%s",
            candidate.url,
            len(candidate.text),
            len(candidate.title),
            fetch_elapsed,
            candidate.source_type,
        )
        extracted.append(candidate)

    logger.debug(
        "source_shortlist fetch stage done input_candidates=%d attempted=%d extracted=%d max_fetch=%d",
        len(candidates),
        min(len(candidates), SOURCE_SHORTLIST_MAX_FETCH_URLS),
        len(extracted),
        SOURCE_SHORTLIST_MAX_FETCH_URLS,
    )
    return extracted


def _extract_fetch_error(payload: Dict[str, Any]) -> str:
    """Extract fetch error from payload warnings, if present."""
    warning_text = str(payload.get("warning", "") or "")
    fetch_error_prefix = "fetch_error:"
    if warning_text.startswith(fetch_error_prefix):
        return warning_text[len(fetch_error_prefix) :].strip()[:MAX_SEED_URL_ERROR_CHARS]
    return ""


def _build_seed_url_documents(
    *,
    seed_urls: Sequence[str],
    candidates: Sequence[CandidateRecord],
) -> List[Dict[str, Any]]:
    """Build deterministic seed URL document payloads in prompt order."""
    seed_candidates = [
        candidate for candidate in candidates if candidate.source_type == "seed"
    ]
    by_requested_url = {
        candidate.requested_url: candidate
        for candidate in seed_candidates
        if candidate.requested_url
    }
    documents: List[Dict[str, Any]] = []
    for seed_url in seed_urls:
        candidate = by_requested_url.get(seed_url)
        if candidate is None:
            documents.append(
                {
                    "url": seed_url,
                    "resolved_url": seed_url,
                    "title": "",
                    "content": "",
                    "error": "Seed URL was not fetched by shortlist pipeline.",
                    "warning": "",
                }
            )
            continue
        documents.append(
            {
                "url": seed_url,
                "resolved_url": candidate.final_url or candidate.url or seed_url,
                "title": candidate.title,
                "content": candidate.fetched_content,
                "error": candidate.fetch_error,
                "warning": candidate.fetch_warning,
            }
        )
    return documents


def _emit_trace_event(
    trace_callback: Optional[TraceCallback],
    payload: Dict[str, Any],
) -> None:
    """Emit a shortlist transport trace event without interrupting execution."""
    if trace_callback is None:
        return
    try:
        trace_callback(payload)
    except Exception:
        logger.debug(
            "source_shortlist trace callback failed for kind=%s",
            payload.get("kind"),
        )


def _with_optional_trace_callback(
    executor: Any,
    trace_callback: Optional[TraceCallback],
) -> Any:
    """Wrap an executor so trace_callback is passed when supported."""
    if trace_callback is None:
        return executor
    try:
        signature = inspect.signature(executor)
        supports_trace = "trace_callback" in signature.parameters or any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
    except (TypeError, ValueError):
        supports_trace = False
    if not supports_trace:
        return executor

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        if "trace_callback" not in kwargs:
            kwargs["trace_callback"] = trace_callback
        return executor(*args, **kwargs)

    return _wrapped


def _default_fetch_executor(
    url: str,
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    """Fetch and extract URL content using the shared retrieval pipeline."""
    fetch_start = time.perf_counter()

    # --- Cache Check ---
    try:
        from asky.research.cache import ResearchCache

        cache = ResearchCache()
        cached = cache.get_cached(url)
        if cached and cached.get("content"):
            logger.debug(
                "source_shortlist fetch executor CACHE HIT url=%s elapsed=%.2fms",
                url,
                _elapsed_ms(fetch_start),
            )
            return {
                "text": cached["content"],
                "title": cached.get("title") or "",
                "date": None,  # SQLite ResearchCache doesn't store date currently
                "final_url": cached.get("url") or url,
                "source": "cache",
            }
    except Exception as e:
        logger.debug("Failed to check cache for shortlist candidate url=%s err=%s", url, e)

    redirect_target = _resolve_redirect_target_if_needed(url)
    payload = fetch_url_document(
        url=url,
        output_format="txt",
        include_links=False,
        trace_callback=trace_callback,
        trace_context={
            "tool_name": "shortlist",
            "operation": "shortlist_fetch",
        },
    )
    try:
        from asky.research.cache import ResearchCache

        cache = ResearchCache()

        content_to_cache = str(payload.get("text") or payload.get("content") or "")
        if content_to_cache and not payload.get("error"):
            # Only cache successfully extracted content
            cache.cache_url(
                url=str(payload.get("final_url", "") or url),
                content=content_to_cache,
                title=str(payload.get("title", "")),
                links=[],
                trigger_summarization=False,
            )
    except Exception as e:
        logger.debug("Failed to cache shortlist candidate url=%s err=%s", url, e)
        
    if payload.get("error"):
        logger.debug(
            "source_shortlist fetch executor error url=%s elapsed=%.2fms error=%s",
            url,
            _elapsed_ms(fetch_start),
            payload.get("error"),
        )
        return {
            "text": "",
            "title": "",
            "date": None,
            "warning": f"fetch_error:{payload['error']}",
        }

    result: Dict[str, Any] = {
        "text": payload.get("content", ""),
        "title": payload.get("title", ""),
        "date": payload.get("date"),
        "final_url": payload.get("final_url", ""),
    }
    if redirect_target and not result.get("final_url"):
        result["final_url"] = redirect_target
    if payload.get("warning"):
        result["warning"] = payload["warning"]

    logger.debug(
        "source_shortlist fetch executor used shared retrieval url=%s elapsed=%.2fms source=%s warning=%s",
        url,
        _elapsed_ms(fetch_start),
        payload.get("source"),
        result.get("warning"),
    )
    return result


def _default_seed_link_extractor(
    url: str,
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    """Fetch one seed page and extract outbound links for shortlist expansion."""
    extract_start = time.perf_counter()
    _emit_trace_event(
        trace_callback,
        {
            "kind": "transport_request",
            "transport": "http",
            "source": "shortlist",
            "operation": "seed_link_extract",
            "method": "GET",
            "url": url,
        },
    )
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        response.raise_for_status()
        _emit_trace_event(
            trace_callback,
            {
                "kind": "transport_response",
                "transport": "http",
                "source": "shortlist",
                "operation": "seed_link_extract",
                "method": "GET",
                "url": url,
                "status_code": response.status_code,
                "content_type": response.headers.get("Content-Type", ""),
                "response_type": "html",
                "response_bytes": len(response.content or b""),
                "response_chars": len(response.text or ""),
                "elapsed_ms": _elapsed_ms(extract_start),
            },
        )

        stripper = HTMLStripper(
            base_url=url,
            excluded_link_container_tags=IGNORED_SEED_LINK_CONTAINER_TAGS,
        )
        stripper.feed(response.text)
        links = stripper.get_links()

        logger.debug(
            "source_shortlist seed link extractor success url=%s status=%s links=%d elapsed=%.2fms",
            url,
            response.status_code,
            len(links),
            _elapsed_ms(extract_start),
        )
        return {"links": links}
    except Exception as exc:
        status_code = None
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
            status_code = exc.response.status_code
        _emit_trace_event(
            trace_callback,
            {
                "kind": "transport_error",
                "transport": "http",
                "source": "shortlist",
                "operation": "seed_link_extract",
                "method": "GET",
                "url": url,
                "error_type": "request_exception",
                "error": str(exc),
                "status_code": status_code,
                "elapsed_ms": _elapsed_ms(extract_start),
            },
        )
        logger.debug(
            "source_shortlist seed link extractor failed url=%s elapsed=%.2fms error=%s",
            url,
            _elapsed_ms(extract_start),
            exc,
        )
        return {"links": [], "warning": f"seed_link_extract_error:{exc}"}


def _default_search_executor(
    args: Dict[str, Any],
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    """Lazy-load web search executor to avoid shortlist import overhead."""
    from asky.tools import execute_web_search as execute_web_search_impl

    return execute_web_search_impl(args, trace_callback=trace_callback)


def _get_embedding_client() -> "EmbeddingClient":
    """Lazy-load embedding client factory only when scoring needs embeddings."""
    from asky.research.embeddings import (
        get_embedding_client as get_embedding_client_impl,
    )

    return get_embedding_client_impl()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Lazy-load cosine similarity helper when embeddings are available."""
    from asky.research.vector_store import cosine_similarity as cosine_similarity_impl

    return cosine_similarity_impl(a, b)


def _get_yake_module() -> Optional[Any]:
    """Import YAKE lazily on first use."""
    global _YAKE_MODULE, _YAKE_MODULE_LOADED
    if _YAKE_MODULE_LOADED:
        return _YAKE_MODULE

    try:
        import yake as yake_module  # type: ignore

        _YAKE_MODULE = yake_module
    except ImportError:
        _YAKE_MODULE = None
    _YAKE_MODULE_LOADED = True
    return _YAKE_MODULE


def _extract_path_tokens(path: str) -> str:
    """Extract lexical tokens from URL path."""
    raw_tokens = PATH_TOKEN_SPLIT_PATTERN.split(path or "")
    filtered_tokens = [
        token.lower() for token in raw_tokens if token and len(token) > 1
    ]
    return " ".join(filtered_tokens)


def _is_http_url(url: str) -> bool:
    """Return whether URL uses HTTP(S) scheme."""
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_blocked_seed_link(url: str) -> bool:
    """Filter known low-value utility/auth links during seed-link expansion."""
    normalized_url = normalize_source_url(url)
    if not normalized_url:
        return True

    parsed = urlsplit(normalized_url)
    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if any(hostname.startswith(prefix) for prefix in SEED_LINK_BLOCKED_HOST_PREFIXES):
        return True
    return any(marker in path for marker in SEED_LINK_BLOCKED_PATH_MARKERS)


def _apply_canonical_url(candidate: CandidateRecord, payload: Dict[str, Any]) -> None:
    """Apply canonical/redirect final URL returned by fetch layer."""
    final_url = _normalize_whitespace(str(payload.get("final_url", "")))
    if not final_url:
        return
    normalized_final = normalize_source_url(final_url)
    if not normalized_final:
        return

    candidate.url = final_url
    candidate.normalized_url = normalized_final
    parsed = urlsplit(normalized_final)
    candidate.hostname = (parsed.hostname or "").lower()
    candidate.path_tokens = _extract_path_tokens(parsed.path)


def _should_probe_redirect_target(url: str) -> bool:
    """Return whether URL matches redirect-prone utility patterns."""
    lowered = normalize_source_url(url).lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in REDIRECT_PROBE_PATH_MARKERS)


def _resolve_redirect_target_if_needed(url: str) -> str:
    """Resolve final URL for known redirect-prone links."""
    if not _should_probe_redirect_target(url):
        return ""
    response = None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=min(FETCH_TIMEOUT, REDIRECT_LOOKUP_TIMEOUT_SECONDS),
            allow_redirects=True,
            stream=True,
        )
        response.raise_for_status()
        return _normalize_whitespace(response.url)
    except Exception:
        return ""
    finally:
        if response is not None:
            response.close()


def _is_noise_path(url: str) -> bool:
    """Flag obvious low-value URL paths."""
    lowered = url.lower()
    return any(marker in lowered for marker in NOISE_PATH_MARKERS)


def _derive_title_from_url(url: str) -> str:
    """Create a readable fallback title from URL path."""
    parsed = urlsplit(url)
    path_title = parsed.path.strip("/").replace("-", " ").replace("_", " ")
    if path_title:
        return _normalize_whitespace(path_title)[:MAX_TITLE_CHARS]
    return parsed.netloc[:MAX_TITLE_CHARS]


def _normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace for stable matching and snippets."""
    return WHITESPACE_PATTERN.sub(" ", value or "").strip()


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    """Deduplicate while preserving first-seen ordering."""
    seen = set()
    output: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _elapsed_ms(start: float) -> float:
    """Return elapsed milliseconds from a perf_counter start value."""
    return (time.perf_counter() - start) * 1000


def _notify_status(status_callback: Optional[StatusCallback], message: str) -> None:
    """Emit shortlist status update when callback is configured."""
    if not status_callback:
        return
    try:
        status_callback(message)
    except Exception:
        logger.debug("source_shortlist status callback failed: %s", message)

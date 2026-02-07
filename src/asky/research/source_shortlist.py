"""Pre-LLM source shortlisting shared across chat modes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
from asky.research.embeddings import EmbeddingClient, get_embedding_client
from asky.research.vector_store import cosine_similarity
from asky.tools import execute_web_search

logger = logging.getLogger(__name__)

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

try:
    import yake
except ImportError:
    yake = None  # type: ignore[assignment]

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
TRAILING_URL_PUNCTUATION = ".,;:!?)]}>\"'"
REPEATED_SLASHES_PATTERN = re.compile(r"/{2,}")
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
}
NOISE_PATH_MARKERS = {
    "/tag/",
    "/category/",
    "/login",
    "/privacy",
    "/terms",
    "/cookie",
    "/subscribe",
}
MAX_REASON_COUNT = 4
MAX_SHORTLIST_CONTEXT_ITEMS = 5
MAX_SHORTLIST_CONTEXT_SNIPPET_CHARS = 420
MAX_TITLE_CHARS = 180

SearchExecutor = Callable[[Dict[str, Any]], Dict[str, Any]]
FetchExecutor = Callable[[str], Dict[str, Any]]


@dataclass
class CandidateRecord:
    """Candidate source record used throughout the shortlist pipeline."""

    url: str
    source_type: str
    normalized_url: str = ""
    hostname: str = ""
    title: str = ""
    text: str = ""
    snippet: str = ""
    date: Optional[str] = None
    search_snippet: str = ""
    path_tokens: str = ""
    semantic_score: float = 0.0
    overlap_ratio: float = 0.0
    bonus_score: float = 0.0
    penalty_score: float = 0.0
    final_score: float = 0.0
    why_selected: List[str] = field(default_factory=list)


def extract_prompt_urls_and_query_text(user_prompt: str) -> Tuple[List[str], str]:
    """Extract URLs from prompt and return the remaining query text."""
    if not user_prompt:
        return [], ""

    seed_urls: List[str] = []
    for raw_url in URL_PATTERN.findall(user_prompt):
        cleaned_url = raw_url.rstrip(TRAILING_URL_PUNCTUATION)
        if cleaned_url:
            seed_urls.append(cleaned_url)

    deduped_urls = _dedupe_preserve_order(seed_urls)
    query_text = _normalize_whitespace(URL_PATTERN.sub(" ", user_prompt))
    return deduped_urls, query_text


def normalize_source_url(url: str) -> str:
    """Normalize URL to collapse duplicate variants and strip tracking params."""
    if not url:
        return ""

    parsed = urlsplit(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""

    port = parsed.port
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"{hostname}:{port}" if include_port else hostname

    normalized_path = REPEATED_SLASHES_PATTERN.sub("/", parsed.path or "/")
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_pairs = []
    for key, value in query_pairs:
        lowered = key.lower()
        if lowered.startswith("utm_"):
            continue
        if lowered in TRACKING_QUERY_KEYS:
            continue
        filtered_pairs.append((key, value))
    filtered_pairs.sort(key=lambda pair: pair[0])
    normalized_query = urlencode(filtered_pairs, doseq=True)

    return urlunsplit((scheme, netloc, normalized_path, normalized_query, ""))


def extract_keyphrases(query_text: str) -> List[str]:
    """Extract keyphrases with YAKE (fallbacks to token terms if unavailable)."""
    if not query_text:
        return []

    normalized_query = _normalize_whitespace(query_text)
    if len(normalized_query) < SOURCE_SHORTLIST_KEYPHRASE_MIN_QUERY_CHARS:
        return []

    if yake is not None:
        try:
            extractor = yake.KeywordExtractor(
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
    embedding_client: Optional[EmbeddingClient] = None,
) -> Dict[str, Any]:
    """Build a ranked shortlist of relevant sources without using an LLM."""
    if not _shortlist_enabled_for_mode(research_mode):
        return {
            "enabled": False,
            "seed_urls": [],
            "query_text": "",
            "search_query": "",
            "keyphrases": [],
            "candidates": [],
            "warnings": [],
        }

    seed_urls, query_text = extract_prompt_urls_and_query_text(user_prompt)
    keyphrases = extract_keyphrases(query_text)
    search_query = build_search_query(query_text, keyphrases)

    active_search_executor = search_executor or execute_web_search
    active_fetch_executor = fetch_executor or _default_fetch_executor

    warnings: List[str] = []
    candidates = _collect_candidates(
        seed_urls=seed_urls,
        search_query=search_query,
        search_executor=active_search_executor,
        warnings=warnings,
    )

    if not candidates:
        return {
            "enabled": True,
            "seed_urls": seed_urls,
            "query_text": query_text,
            "search_query": search_query,
            "keyphrases": keyphrases,
            "candidates": [],
            "warnings": warnings,
        }

    fetched_candidates = _fetch_candidate_content(
        candidates=candidates,
        fetch_executor=active_fetch_executor,
        warnings=warnings,
    )

    if not fetched_candidates:
        return {
            "enabled": True,
            "seed_urls": seed_urls,
            "query_text": query_text,
            "search_query": search_query,
            "keyphrases": keyphrases,
            "candidates": [],
            "warnings": warnings,
        }

    scoring_query = _resolve_scoring_query(query_text, keyphrases, fetched_candidates)
    scored_candidates = _score_candidates(
        candidates=fetched_candidates,
        scoring_query=scoring_query,
        keyphrases=keyphrases,
        seed_urls=seed_urls,
        embedding_client=embedding_client,
        warnings=warnings,
    )

    ranked = sorted(scored_candidates, key=lambda item: item.final_score, reverse=True)
    ranked = ranked[:SOURCE_SHORTLIST_TOP_K]

    shortlisted = []
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

    return {
        "enabled": True,
        "seed_urls": seed_urls,
        "query_text": query_text,
        "search_query": search_query,
        "keyphrases": keyphrases,
        "candidates": shortlisted,
        "warnings": warnings,
    }


def format_shortlist_context(shortlist_payload: Dict[str, Any]) -> str:
    """Format shortlist payload into compact text suitable for prompt context."""
    candidates = shortlist_payload.get("candidates", [])
    if not candidates:
        return ""

    lines: List[str] = []
    for item in candidates[:MAX_SHORTLIST_CONTEXT_ITEMS]:
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


def _shortlist_enabled_for_mode(research_mode: bool) -> bool:
    """Return whether source shortlisting is enabled for the current chat mode."""
    if not SOURCE_SHORTLIST_ENABLED:
        return False
    if research_mode:
        return bool(SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE)
    return bool(SOURCE_SHORTLIST_ENABLE_STANDARD_MODE)


def _collect_candidates(
    seed_urls: Sequence[str],
    search_query: str,
    search_executor: SearchExecutor,
    warnings: List[str],
) -> List[CandidateRecord]:
    """Collect candidates from prompt seed URLs and optional web search."""
    collected: List[CandidateRecord] = [
        CandidateRecord(url=url, source_type="seed") for url in seed_urls if url
    ]

    should_search = bool(search_query) and (
        not seed_urls or SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS
    )

    if should_search:
        try:
            search_payload = search_executor(
                {"q": search_query, "count": SOURCE_SHORTLIST_SEARCH_RESULT_COUNT}
            )
        except Exception as exc:
            warnings.append(f"search_error:{exc}")
            search_payload = {"results": []}

        if isinstance(search_payload, dict):
            if search_payload.get("error"):
                warnings.append(f"search_error:{search_payload['error']}")
            for result in search_payload.get("results", []):
                url = _normalize_whitespace(str(result.get("url", "")))
                if not url:
                    continue
                title = _normalize_whitespace(str(result.get("title", "")))
                snippet = _normalize_whitespace(str(result.get("snippet", "")))
                collected.append(
                    CandidateRecord(
                        url=url,
                        source_type="search",
                        title=title[:MAX_TITLE_CHARS],
                        search_snippet=snippet,
                    )
                )

    deduped: List[CandidateRecord] = []
    seen = set()
    for candidate in collected:
        normalized_url = normalize_source_url(candidate.url)
        if not normalized_url or normalized_url in seen:
            continue
        seen.add(normalized_url)
        candidate.normalized_url = normalized_url
        parsed = urlsplit(normalized_url)
        candidate.hostname = (parsed.hostname or "").lower()
        candidate.path_tokens = _extract_path_tokens(parsed.path)
        deduped.append(candidate)
        if len(deduped) >= SOURCE_SHORTLIST_MAX_CANDIDATES:
            break
    return deduped


def _fetch_candidate_content(
    candidates: Sequence[CandidateRecord],
    fetch_executor: FetchExecutor,
    warnings: List[str],
) -> List[CandidateRecord]:
    """Fetch and extract main text for candidate URLs."""
    extracted: List[CandidateRecord] = []
    for candidate in candidates[:SOURCE_SHORTLIST_MAX_FETCH_URLS]:
        payload = fetch_executor(candidate.url)
        text = _normalize_whitespace(str(payload.get("text", "")))
        if len(text) < SOURCE_SHORTLIST_MIN_CONTENT_CHARS:
            continue

        candidate.title = (
            _normalize_whitespace(str(payload.get("title", "")))[:MAX_TITLE_CHARS]
            or candidate.title
            or _derive_title_from_url(candidate.url)
        )
        candidate.text = text[:SOURCE_SHORTLIST_MAX_SCORING_CHARS]
        candidate.snippet = candidate.text[:SOURCE_SHORTLIST_SNIPPET_CHARS]
        candidate.date = payload.get("date")
        if payload.get("warning"):
            warnings.append(str(payload["warning"]))
        extracted.append(candidate)
    return extracted


def _score_candidates(
    candidates: Sequence[CandidateRecord],
    scoring_query: str,
    keyphrases: Sequence[str],
    seed_urls: Sequence[str],
    embedding_client: Optional[EmbeddingClient],
    warnings: List[str],
) -> List[CandidateRecord]:
    """Score candidates with semantic relevance and lightweight heuristics."""
    if not candidates:
        return []

    query_embedding: Optional[List[float]] = None
    doc_embeddings: List[List[float]] = []
    doc_strings: List[str] = [
        _build_document_string(candidate) for candidate in candidates
    ]

    if scoring_query:
        client = embedding_client or get_embedding_client()
        try:
            query_embedding = client.embed_single(scoring_query)
            doc_embeddings = client.embed(doc_strings)
        except Exception as exc:
            warnings.append(f"embedding_error:{exc}")
            query_embedding = None
            doc_embeddings = []

    if query_embedding and len(doc_embeddings) != len(candidates):
        warnings.append("embedding_warning:mismatched_doc_embeddings")
        doc_embeddings = []

    seed_domains = {
        (urlsplit(normalize_source_url(url)).hostname or "").lower()
        for url in seed_urls
        if normalize_source_url(url)
    }
    lowered_keyphrases = [phrase.lower() for phrase in keyphrases if phrase]

    for idx, candidate in enumerate(candidates):
        document = doc_strings[idx].lower()
        semantic_score = 0.0
        if query_embedding and doc_embeddings:
            semantic_score = max(
                0.0,
                cosine_similarity(query_embedding, doc_embeddings[idx]),
            )

        overlap_ratio = _keyphrase_overlap_ratio(lowered_keyphrases, document)
        bonus = SOURCE_SHORTLIST_OVERLAP_BONUS_WEIGHT * overlap_ratio
        if seed_domains and candidate.hostname and candidate.hostname in seed_domains:
            bonus += SOURCE_SHORTLIST_SAME_DOMAIN_BONUS

        penalty = 0.0
        if len(candidate.text) < SOURCE_SHORTLIST_SHORT_TEXT_THRESHOLD:
            penalty += SOURCE_SHORTLIST_SHORT_TEXT_PENALTY
        if _is_noise_path(candidate.normalized_url):
            penalty += SOURCE_SHORTLIST_NOISE_PATH_PENALTY

        candidate.semantic_score = semantic_score
        candidate.overlap_ratio = overlap_ratio
        candidate.bonus_score = bonus
        candidate.penalty_score = penalty
        candidate.final_score = semantic_score + bonus - penalty

        candidate.why_selected = _build_selection_reasons(
            candidate=candidate,
            seed_domains=seed_domains,
            has_keyphrases=bool(lowered_keyphrases),
        )

    return list(candidates)


def _build_selection_reasons(
    candidate: CandidateRecord,
    seed_domains: set[str],
    has_keyphrases: bool,
) -> List[str]:
    """Build concise reasons attached to a ranked result."""
    reasons = [f"semantic_similarity={candidate.semantic_score:.2f}"]
    if has_keyphrases and candidate.overlap_ratio > 0:
        reasons.append(f"keyphrase_overlap={candidate.overlap_ratio:.2f}")
    if seed_domains and candidate.hostname in seed_domains:
        reasons.append("same_domain_as_seed")
    if candidate.penalty_score > 0 and _is_noise_path(candidate.normalized_url):
        reasons.append("noise_path_penalty")
    return reasons[:MAX_REASON_COUNT]


def _resolve_scoring_query(
    query_text: str,
    keyphrases: Sequence[str],
    candidates: Sequence[CandidateRecord],
) -> str:
    """Resolve best-effort scoring query when the prompt has mostly URLs."""
    normalized_query = _normalize_whitespace(query_text)
    if normalized_query:
        return normalized_query

    if keyphrases:
        return " ".join(keyphrases[:SOURCE_SHORTLIST_SEARCH_PHRASE_COUNT])

    fallback_parts: List[str] = []
    for candidate in candidates[:2]:
        if candidate.title:
            fallback_parts.append(candidate.title)
        if candidate.text:
            fallback_parts.append(candidate.text[:SOURCE_SHORTLIST_QUERY_FALLBACK_CHARS])
    return _normalize_whitespace(" ".join(fallback_parts))


def _keyphrase_overlap_ratio(keyphrases: Sequence[str], lowered_document: str) -> float:
    """Compute normalized keyphrase overlap ratio."""
    if not keyphrases:
        return 0.0
    matches = sum(1 for phrase in keyphrases if phrase in lowered_document)
    return matches / len(keyphrases)


def _build_document_string(candidate: CandidateRecord) -> str:
    """Build candidate document string used for embedding similarity."""
    lead_text = candidate.text[:SOURCE_SHORTLIST_DOC_LEAD_CHARS]
    return "\n".join(
        [
            candidate.title,
            lead_text,
            candidate.path_tokens,
        ]
    )


def _default_fetch_executor(url: str) -> Dict[str, Any]:
    """Fetch and extract URL content using trafilatura with HTML fallback."""
    trafilatura_result = _fetch_with_trafilatura(url)
    if trafilatura_result.get("text"):
        return trafilatura_result

    fallback_result = _fetch_with_html_stripper(url)
    if trafilatura_result.get("warning") and not fallback_result.get("warning"):
        fallback_result["warning"] = trafilatura_result["warning"]
    return fallback_result


def _fetch_with_trafilatura(url: str) -> Dict[str, Any]:
    """Fetch and extract content via trafilatura."""
    if trafilatura is None:
        return {"text": "", "title": "", "date": None, "warning": "trafilatura_unavailable"}

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"text": "", "title": "", "date": None, "warning": "trafilatura_empty_download"}

        extracted = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_comments=False,
            include_tables=False,
        )
        if not extracted:
            return {"text": "", "title": "", "date": None, "warning": "trafilatura_empty_extract"}

        text = _normalize_whitespace(extracted)
        first_line = text.split("\n", 1)[0] if text else ""
        title = first_line[:MAX_TITLE_CHARS] if first_line else ""
        return {"text": text, "title": title, "date": None}
    except Exception as exc:
        return {"text": "", "title": "", "date": None, "warning": f"trafilatura_error:{exc}"}


def _fetch_with_html_stripper(url: str) -> Dict[str, Any]:
    """Fetch URL via requests and extract text with HTMLStripper."""
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        response.raise_for_status()

        stripper = HTMLStripper(base_url=url)
        stripper.feed(response.text)
        text = _normalize_whitespace(stripper.get_data())
        title = (text.split("\n", 1)[0] if text else "")[:MAX_TITLE_CHARS]
        return {
            "text": text,
            "title": title,
            "date": None,
        }
    except Exception as exc:
        logger.debug("HTML fallback fetch failed for %s: %s", url, exc)
        return {"text": "", "title": "", "date": None, "warning": f"fetch_error:{exc}"}


def _extract_path_tokens(path: str) -> str:
    """Extract lexical tokens from URL path."""
    raw_tokens = PATH_TOKEN_SPLIT_PATTERN.split(path or "")
    filtered_tokens = [token.lower() for token in raw_tokens if token and len(token) > 1]
    return " ".join(filtered_tokens)


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

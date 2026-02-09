"""Candidate scoring stage for source shortlisting."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from asky.research.shortlist_types import CandidateRecord, ShortlistMetrics

NormalizeSourceUrl = Callable[[str], str]
IsNoisePath = Callable[[str], bool]
CosineSimilarity = Callable[[List[float], List[float]], float]
GetEmbeddingClient = Callable[[], Any]
NormalizeWhitespace = Callable[[str], str]


def resolve_scoring_query(
    *,
    query_text: str,
    keyphrases: Sequence[str],
    candidates: Sequence[CandidateRecord],
    search_phrase_count: int,
    query_fallback_chars: int,
    normalize_whitespace: NormalizeWhitespace,
) -> str:
    """Resolve best-effort scoring query when prompt text is sparse."""
    normalized_query = normalize_whitespace(query_text)
    if normalized_query:
        return normalized_query

    if keyphrases:
        return " ".join(keyphrases[:search_phrase_count])

    fallback_parts: List[str] = []
    for candidate in candidates[:2]:
        if candidate.title:
            fallback_parts.append(candidate.title)
        if candidate.text:
            fallback_parts.append(candidate.text[:query_fallback_chars])
    return normalize_whitespace(" ".join(fallback_parts))


def _keyphrase_overlap_ratio(keyphrases: Sequence[str], lowered_document: str) -> float:
    if not keyphrases:
        return 0.0
    matches = sum(1 for phrase in keyphrases if phrase in lowered_document)
    return matches / len(keyphrases)


def _build_document_string(candidate: CandidateRecord, doc_lead_chars: int) -> str:
    lead_text = candidate.text[:doc_lead_chars]
    return "\n".join([candidate.title, lead_text, candidate.path_tokens])


def _same_domain_bonus_applies(
    *,
    candidate: CandidateRecord,
    seed_domains: set[str],
    semantic_score: float,
    overlap_ratio: float,
    same_domain_bonus_min_signal: float,
    is_noise_path: IsNoisePath,
) -> bool:
    if not seed_domains or not candidate.hostname:
        return False
    if candidate.hostname not in seed_domains:
        return False
    if is_noise_path(candidate.normalized_url):
        return False
    return semantic_score >= same_domain_bonus_min_signal or overlap_ratio > 0


def _build_selection_reasons(
    *,
    candidate: CandidateRecord,
    seed_domains: set[str],
    has_keyphrases: bool,
    same_domain_bonus_min_signal: float,
    is_noise_path: IsNoisePath,
    max_reason_count: int,
) -> List[str]:
    reasons = [f"semantic_similarity={candidate.semantic_score:.2f}"]
    if has_keyphrases and candidate.overlap_ratio > 0:
        reasons.append(f"keyphrase_overlap={candidate.overlap_ratio:.2f}")
    if _same_domain_bonus_applies(
        candidate=candidate,
        seed_domains=seed_domains,
        semantic_score=candidate.semantic_score,
        overlap_ratio=candidate.overlap_ratio,
        same_domain_bonus_min_signal=same_domain_bonus_min_signal,
        is_noise_path=is_noise_path,
    ):
        reasons.append("same_domain_as_seed")
    if candidate.penalty_score > 0 and is_noise_path(candidate.normalized_url):
        reasons.append("noise_path_penalty")
    return reasons[:max_reason_count]


def score_candidates(
    *,
    candidates: Sequence[CandidateRecord],
    scoring_query: str,
    keyphrases: Sequence[str],
    seed_urls: Sequence[str],
    embedding_client: Optional[Any],
    warnings: List[str],
    metrics: Optional[ShortlistMetrics],
    normalize_source_url: NormalizeSourceUrl,
    is_noise_path: IsNoisePath,
    cosine_similarity: CosineSimilarity,
    get_embedding_client: GetEmbeddingClient,
    overlap_bonus_weight: float,
    same_domain_bonus: float,
    same_domain_bonus_min_signal: float,
    short_text_threshold: int,
    short_text_penalty: float,
    noise_path_penalty: float,
    doc_lead_chars: int,
    max_reason_count: int,
    logger: Any,
) -> List[CandidateRecord]:
    """Score candidates with semantic relevance and lightweight heuristics."""
    if not candidates:
        return []

    query_embedding: Optional[List[float]] = None
    doc_embeddings: List[List[float]] = []
    doc_strings: List[str] = [
        _build_document_string(candidate, doc_lead_chars) for candidate in candidates
    ]

    if scoring_query:
        client = embedding_client or get_embedding_client()
        has_cached_failure = getattr(client, "has_model_load_failure", None)
        if callable(has_cached_failure) and has_cached_failure():
            warnings.append("embedding_skipped:cached_model_load_failure")
            logger.debug(
                "source_shortlist embedding skipped due to cached model load failure query_len=%d docs=%d",
                len(scoring_query),
                len(doc_strings),
            )
        else:
            try:
                embed_query_start = time.perf_counter()
                query_embedding = client.embed_single(scoring_query)
                query_elapsed = (time.perf_counter() - embed_query_start) * 1000
                if metrics is not None:
                    metrics["embedding_query_calls"] += 1

                embed_docs_start = time.perf_counter()
                doc_embeddings = client.embed(doc_strings)
                docs_elapsed = (time.perf_counter() - embed_docs_start) * 1000
                if metrics is not None:
                    metrics["embedding_doc_calls"] += 1
                    metrics["embedding_doc_count"] += len(doc_strings)

                logger.debug(
                    "source_shortlist embeddings complete query_len=%d docs=%d query_embed_ms=%.2f docs_embed_ms=%.2f",
                    len(scoring_query),
                    len(doc_strings),
                    query_elapsed,
                    docs_elapsed,
                )
            except Exception as exc:
                warnings.append(f"embedding_error:{exc}")
                query_embedding = None
                doc_embeddings = []
                logger.debug(
                    "source_shortlist embedding failed query_len=%d docs=%d error=%s",
                    len(scoring_query),
                    len(doc_strings),
                    exc,
                )

    if query_embedding and len(doc_embeddings) != len(candidates):
        warnings.append("embedding_warning:mismatched_doc_embeddings")
        doc_embeddings = []
        logger.debug(
            "source_shortlist embedding mismatch query_embedding=%s doc_embeddings=%d candidates=%d",
            bool(query_embedding),
            len(doc_embeddings),
            len(candidates),
        )

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
        bonus = overlap_bonus_weight * overlap_ratio
        if _same_domain_bonus_applies(
            candidate=candidate,
            seed_domains=seed_domains,
            semantic_score=semantic_score,
            overlap_ratio=overlap_ratio,
            same_domain_bonus_min_signal=same_domain_bonus_min_signal,
            is_noise_path=is_noise_path,
        ):
            bonus += same_domain_bonus

        penalty = 0.0
        if len(candidate.text) < short_text_threshold:
            penalty += short_text_penalty
        if is_noise_path(candidate.normalized_url):
            penalty += noise_path_penalty

        candidate.semantic_score = semantic_score
        candidate.overlap_ratio = overlap_ratio
        candidate.bonus_score = bonus
        candidate.penalty_score = penalty
        candidate.final_score = semantic_score + bonus - penalty
        candidate.why_selected = _build_selection_reasons(
            candidate=candidate,
            seed_domains=seed_domains,
            has_keyphrases=bool(lowered_keyphrases),
            same_domain_bonus_min_signal=same_domain_bonus_min_signal,
            is_noise_path=is_noise_path,
            max_reason_count=max_reason_count,
        )

        logger.debug(
            "source_shortlist score url=%s semantic=%.4f overlap=%.4f bonus=%.4f penalty=%.4f final=%.4f",
            candidate.url,
            candidate.semantic_score,
            candidate.overlap_ratio,
            candidate.bonus_score,
            candidate.penalty_score,
            candidate.final_score,
        )

    return list(candidates)

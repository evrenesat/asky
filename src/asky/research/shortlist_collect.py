"""Candidate collection stage for source shortlisting."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from asky.research.shortlist_types import (
    CandidateRecord,
    SearchExecutor,
    SeedLinkExtractor,
    ShortlistMetrics,
)

NormalizeSourceUrl = Callable[[str], str]
ExtractPathTokens = Callable[[str], str]
NormalizeWhitespace = Callable[[str], str]
IsHttpUrl = Callable[[str], bool]
IsBlockedSeedLink = Callable[[str], bool]
ElapsedMs = Callable[[float], float]


def collect_seed_link_candidates(
    *,
    seed_urls: Sequence[str],
    seed_link_extractor: SeedLinkExtractor,
    warnings: List[str],
    metrics: Optional[ShortlistMetrics],
    seed_link_max_pages: int,
    seed_links_per_page: int,
    max_title_chars: int,
    normalize_whitespace: NormalizeWhitespace,
    is_http_url: IsHttpUrl,
    is_blocked_seed_link: IsBlockedSeedLink,
    elapsed_ms: ElapsedMs,
    logger: Any,
) -> List[CandidateRecord]:
    """Collect candidate URLs by extracting links from seed pages."""
    import time

    output: List[CandidateRecord] = []

    for seed_url in seed_urls[:seed_link_max_pages]:
        page_start = time.perf_counter()
        if metrics is not None:
            metrics["seed_link_pages_attempted"] += 1
            metrics["seed_link_extractor_calls"] += 1

        payload = seed_link_extractor(seed_url)
        warning = payload.get("warning")
        if warning:
            warnings.append(str(warning))
            if metrics is not None:
                metrics["seed_link_failures"] += 1

        raw_links = payload.get("links", [])
        if not isinstance(raw_links, list):
            raw_links = []

        discovered = len(raw_links)
        selected_links = raw_links[:seed_links_per_page]
        added = 0

        for item in selected_links:
            if not isinstance(item, dict):
                continue
            href = normalize_whitespace(str(item.get("href", "")))
            if not href or not is_http_url(href):
                continue
            if is_blocked_seed_link(href):
                continue

            anchor_text = normalize_whitespace(str(item.get("text", "")))
            output.append(
                CandidateRecord(
                    url=href,
                    source_type="seed_link",
                    title=anchor_text[:max_title_chars],
                    search_snippet=anchor_text,
                )
            )
            added += 1

        if metrics is not None:
            metrics["seed_link_discovered"] += discovered
            metrics["seed_link_added"] += added
            if not warning:
                metrics["seed_link_pages_success"] += 1

        logger.debug(
            "source_shortlist seed link extract url=%s discovered=%d selected=%d added=%d elapsed=%.2fms warning=%s",
            seed_url,
            discovered,
            len(selected_links),
            added,
            elapsed_ms(page_start),
            warning,
        )

    return output


def collect_candidates(
    *,
    seed_urls: Sequence[str],
    search_queries: Sequence[str],
    search_executor: SearchExecutor,
    seed_link_extractor: SeedLinkExtractor,
    warnings: List[str],
    metrics: Optional[ShortlistMetrics],
    seed_link_expansion_enabled: bool,
    seed_link_max_pages: int,
    seed_links_per_page: int,
    search_with_seed_urls: bool,
    search_result_count: int,
    max_candidates: int,
    max_title_chars: int,
    normalize_source_url: NormalizeSourceUrl,
    extract_path_tokens: ExtractPathTokens,
    normalize_whitespace: NormalizeWhitespace,
    is_http_url: IsHttpUrl,
    is_blocked_seed_link: IsBlockedSeedLink,
    elapsed_ms: ElapsedMs,
    logger: Any,
) -> List[CandidateRecord]:
    """Collect candidates from prompt seed URLs and optional web searches."""
    import time

    collected: List[CandidateRecord] = [
        CandidateRecord(url=url, source_type="seed") for url in seed_urls if url
    ]

    if seed_urls and seed_link_expansion_enabled:
        seed_link_start = time.perf_counter()
        seed_link_candidates = collect_seed_link_candidates(
            seed_urls=seed_urls,
            seed_link_extractor=seed_link_extractor,
            warnings=warnings,
            metrics=metrics,
            seed_link_max_pages=seed_link_max_pages,
            seed_links_per_page=seed_links_per_page,
            max_title_chars=max_title_chars,
            normalize_whitespace=normalize_whitespace,
            is_http_url=is_http_url,
            is_blocked_seed_link=is_blocked_seed_link,
            elapsed_ms=elapsed_ms,
            logger=logger,
        )
        collected.extend(seed_link_candidates)
        logger.debug(
            "source_shortlist seed link expansion done seeds=%d expanded=%d elapsed=%.2fms max_pages=%d per_page=%d",
            len(seed_urls),
            len(seed_link_candidates),
            elapsed_ms(seed_link_start),
            seed_link_max_pages,
            seed_links_per_page,
        )
    else:
        logger.debug(
            "source_shortlist seed link expansion skipped seed_urls=%d enabled=%s",
            len(seed_urls),
            seed_link_expansion_enabled,
        )

    if metrics is not None:
        metrics["candidate_inputs"] = len(collected)

    should_search = bool(search_queries) and (not seed_urls or search_with_seed_urls)

    if should_search:
        # Distribute search_result_count across queries with weighting.
        # Original query (first) gets 50% of budget, rest split evenly.
        query_count = len(search_queries)
        if query_count == 1:
            budget_allocation = [search_result_count]
        else:
            original_budget = max(1, search_result_count // 2)
            remaining_budget = search_result_count - original_budget
            sub_query_budget = max(1, remaining_budget // (query_count - 1))
            budget_allocation = [original_budget] + [sub_query_budget] * (
                query_count - 1
            )

        for idx, q in enumerate(search_queries):
            if not q:
                continue

            search_start = time.perf_counter()
            try:
                if metrics is not None:
                    metrics["search_calls"] += 1
                search_payload = search_executor({"q": q, "count": budget_allocation[idx]})
            except Exception as exc:
                warnings.append(f"search_error:{exc}")
                logger.debug(
                    "source_shortlist search failed query_len=%d elapsed=%.2fms error=%s",
                    len(q),
                    elapsed_ms(search_start),
                    exc,
                )
                search_payload = {"results": []}

            if isinstance(search_payload, dict):
                if search_payload.get("error"):
                    warnings.append(f"search_error:{search_payload['error']}")
                    logger.debug(
                        "source_shortlist search error payload query_len=%d elapsed=%.2fms error=%s",
                        len(q),
                        elapsed_ms(search_start),
                        search_payload.get("error"),
                    )
                results_count = len(search_payload.get("results", []))
                if metrics is not None:
                    metrics["search_results"] += results_count
                logger.debug(
                    "source_shortlist search completed query_len=%d results=%d elapsed=%.2fms",
                    len(q),
                    results_count,
                    elapsed_ms(search_start),
                )
                for result in search_payload.get("results", []):
                    url = normalize_whitespace(str(result.get("url", "")))
                    if not url:
                        continue
                    title = normalize_whitespace(str(result.get("title", "")))
                    snippet = normalize_whitespace(str(result.get("snippet", "")))
                    collected.append(
                        CandidateRecord(
                            url=url,
                            source_type="search",
                            title=title[:max_title_chars],
                            search_snippet=snippet,
                        )
                    )
    else:
        logger.debug(
            "source_shortlist skipping search seed_urls=%d search_queries=%d config_search_with_seed=%s",
            len(seed_urls),
            len(search_queries),
            search_with_seed_urls,
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
        candidate.path_tokens = extract_path_tokens(parsed.path)
        deduped.append(candidate)
        if len(deduped) >= max_candidates:
            break

    if metrics is not None:
        metrics["candidate_inputs"] = len(collected)
        metrics["candidate_deduped"] = len(deduped)
    logger.debug(
        "source_shortlist candidate collection done seeds=%d collected=%d deduped=%d max_candidates=%d",
        len(seed_urls),
        len(collected),
        len(deduped),
        max_candidates,
    )
    return deduped

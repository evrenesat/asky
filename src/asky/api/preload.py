"""Pre-LLM corpus preload orchestration for API callers."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional

from asky.config import (
    SOURCE_SHORTLIST_ENABLED,
    SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE,
    SOURCE_SHORTLIST_ENABLE_STANDARD_MODE,
    QUERY_EXPANSION_ENABLED,
    QUERY_EXPANSION_MODE,
    QUERY_EXPANSION_MAX_SUB_QUERIES,
    RESEARCH_EVIDENCE_EXTRACTION_ENABLED,
    RESEARCH_EVIDENCE_EXTRACTION_MAX_CHUNKS,
)
from asky.lazy_imports import call_attr

from .types import PreloadResolution

StatusCallback = Callable[[str], None]


def shortlist_prompt_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy import shortlist orchestration to keep non-research startup light."""
    return call_attr(
        "asky.research.source_shortlist",
        "shortlist_prompt_sources",
        *args,
        **kwargs,
    )


def expand_query(*args: Any, **kwargs: Any) -> List[str]:
    """Lazy import query expansion."""
    mode = kwargs.pop("mode", "deterministic")
    query = kwargs.pop("query", "")

    if mode == "llm":
        # LLM mode accepts llm_client, model, max_sub_queries
        return call_attr(
            "asky.research.query_expansion",
            "expand_query_with_llm",
            query,
            **kwargs,
        )
    # Deterministic mode only accepts query (positional)
    return call_attr(
        "asky.research.query_expansion",
        "expand_query_deterministic",
        query,
    )


def format_shortlist_context(shortlist_payload: Dict[str, Any]) -> str:
    """Lazy import shortlist formatter."""
    return call_attr(
        "asky.research.source_shortlist",
        "format_shortlist_context",
        shortlist_payload,
    )


def preload_local_research_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy import local ingestion flow."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "preload_local_research_sources",
        *args,
        **kwargs,
    )


def format_local_ingestion_context(local_payload: Dict[str, Any]) -> Optional[str]:
    """Lazy import local-ingestion context formatter."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "format_local_ingestion_context",
        local_payload,
    )


def extract_evidence(*args: Any, **kwargs: Any) -> Any:
    """Lazy import evidence extraction."""
    return call_attr(
        "asky.research.evidence_extraction",
        "extract_evidence_from_chunks",
        *args,
        **kwargs,
    )


def format_evidence_context(evidence: List[Any]) -> Optional[str]:
    """Lazy import evidence formatter."""
    return call_attr(
        "asky.research.evidence_extraction",
        "format_evidence_context",
        evidence,
    )


def get_relevant_content(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy import research retrieval tool."""
    return call_attr(
        "asky.research.tools",
        "execute_get_relevant_content",
        *args,
        **kwargs,
    )


def shortlist_enabled_for_request(
    *,
    lean: bool,
    model_config: Dict[str, Any],
    research_mode: bool,
) -> tuple[bool, str]:
    """Resolve shortlist enablement with precedence: lean > model > global flags."""
    if lean:
        return False, "lean_flag"

    model_override = model_config.get("source_shortlist_enabled")
    if isinstance(model_override, bool):
        return model_override, "model_override"

    if not SOURCE_SHORTLIST_ENABLED:
        return False, "global_disabled"

    if research_mode:
        return bool(SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE), "global_research_mode"
    return bool(SOURCE_SHORTLIST_ENABLE_STANDARD_MODE), "global_standard_mode"


def build_shortlist_stats(
    shortlist_payload: Dict[str, Any],
    shortlist_elapsed_ms: float,
) -> Dict[str, Any]:
    """Extract compact shortlist stats for UI/banners."""
    stats = shortlist_payload.get("stats", {})
    metrics = stats.get("metrics", {}) if isinstance(stats, dict) else {}
    return {
        "enabled": bool(shortlist_payload.get("enabled")),
        "collected": int(metrics.get("candidate_deduped", 0) or 0),
        "processed": int(metrics.get("fetch_calls", 0) or 0),
        "selected": len(shortlist_payload.get("candidates", []) or []),
        "warnings": len(shortlist_payload.get("warnings", []) or []),
        "elapsed_ms": float(shortlist_elapsed_ms),
    }


def combine_preloaded_source_context(*context_blocks: Optional[str]) -> Optional[str]:
    """Merge multiple preloaded-source context blocks into one section."""
    merged = [block.strip() for block in context_blocks if block and block.strip()]
    if not merged:
        return None
    return "\n\n".join(merged)


def run_preload_pipeline(
    *,
    query_text: str,
    research_mode: bool,
    model_config: Dict[str, Any],
    lean: bool,
    preload_local_sources: bool = True,
    preload_shortlist: bool = True,
    additional_source_context: Optional[str] = None,
    local_corpus_paths: Optional[List[str]] = None,
    status_callback: Optional[StatusCallback] = None,
    shortlist_executor: Callable[..., Dict[str, Any]] = shortlist_prompt_sources,
    shortlist_formatter: Callable[[Dict[str, Any]], str] = format_shortlist_context,
    shortlist_stats_builder: Callable[
        [Dict[str, Any], float], Dict[str, Any]
    ] = build_shortlist_stats,
    local_ingestion_executor: Callable[
        ..., Dict[str, Any]
    ] = preload_local_research_sources,
    local_ingestion_formatter: Callable[
        [Dict[str, Any]], Optional[str]
    ] = format_local_ingestion_context,
    llm_client: Any = None,
    expansion_executor: Callable[..., List[str]] = expand_query,
) -> PreloadResolution:
    """Run local+shortlist preloads and return their combined context payload."""
    preload = PreloadResolution()

    # Decompose query if expansion is enabled
    sub_queries = [query_text]
    if research_mode and QUERY_EXPANSION_ENABLED:
        if status_callback:
            status_callback(f"Query expansion: mode={QUERY_EXPANSION_MODE}")

        expansion_kwargs = {
            "query": query_text,
            "mode": QUERY_EXPANSION_MODE,
            "max_sub_queries": QUERY_EXPANSION_MAX_SUB_QUERIES,
        }
        if QUERY_EXPANSION_MODE == "llm" and llm_client:
            expansion_kwargs["llm_client"] = llm_client
            expansion_kwargs["model"] = model_config.get(
                "model", ""
            )  # Use current model for expansion if not specified

        sub_queries = expansion_executor(**expansion_kwargs)
        preload.sub_queries = sub_queries
        if status_callback and len(sub_queries) > 1:
            status_callback(f"Query expanded into {len(sub_queries)} sub-queries")

    if research_mode and preload_local_sources:
        if status_callback:
            status_callback("Local corpus: starting pre-LLM ingestion")
        local_start = time.perf_counter()
        local_payload = local_ingestion_executor(
            user_prompt=query_text,
            explicit_targets=local_corpus_paths,
        )
        local_elapsed_ms = (time.perf_counter() - local_start) * 1000
        preload.local_payload = local_payload
        preload.local_elapsed_ms = local_elapsed_ms
        preload.local_context = local_ingestion_formatter(local_payload)
        if status_callback:
            ingested_count = len(local_payload.get("ingested", []) or [])
            status_callback(
                f"Local corpus ready: {ingested_count} document(s) in {local_elapsed_ms:.0f}ms"
            )
    else:
        preload.local_payload = {"enabled": False, "ingested": []}

    shortlist_enabled, shortlist_reason = shortlist_enabled_for_request(
        lean=lean,
        model_config=model_config,
        research_mode=research_mode,
    )
    if not preload_shortlist:
        shortlist_enabled = False
        shortlist_reason = "request_disabled"
    preload.shortlist_enabled = shortlist_enabled
    preload.shortlist_reason = shortlist_reason

    shortlist_payload: Dict[str, Any] = {
        "enabled": False,
        "candidates": [],
        "warnings": [],
        "stats": {},
        "trace": {
            "processed_candidates": [],
            "selected_candidates": [],
        },
    }
    shortlist_context: Optional[str] = None
    shortlist_elapsed_ms = 0.0
    if shortlist_enabled:
        if status_callback:
            status_callback("Shortlist: starting pre-LLM retrieval")
        shortlist_start = time.perf_counter()
        shortlist_payload = shortlist_executor(
            user_prompt=query_text,
            research_mode=research_mode,
            status_callback=status_callback,
            queries=sub_queries if len(sub_queries) > 1 else None,
        )
        shortlist_elapsed_ms = (time.perf_counter() - shortlist_start) * 1000
        if shortlist_payload.get("enabled"):
            shortlist_context = shortlist_formatter(shortlist_payload)
        if status_callback:
            status_callback(
                f"Shortlist ready: {len(shortlist_payload.get('candidates', []) or [])} "
                f"selected in {shortlist_elapsed_ms:.0f}ms"
            )
    elif status_callback:
        status_callback(f"Shortlist disabled ({shortlist_reason})")

    preload.shortlist_payload = shortlist_payload
    preload.shortlist_context = shortlist_context
    preload.shortlist_elapsed_ms = shortlist_elapsed_ms
    preload.shortlist_stats = shortlist_stats_builder(
        shortlist_payload,
        shortlist_elapsed_ms,
    )

    # Post-retrieval evidence extraction (optional)
    if (
        research_mode
        and RESEARCH_EVIDENCE_EXTRACTION_ENABLED
        and preload.is_corpus_preloaded
        and sub_queries  # Skip if no sub-queries available
    ):
        if status_callback:
            status_callback("Evidence extraction: processing retrieved chunks")
        evidence_start = time.perf_counter()

        # 1. Collect candidate chunks for each sub-query
        all_candidate_chunks: List[Dict[str, Any]] = []
        all_urls = []
        if preload.local_payload.get("ingested"):
            all_urls.extend([ing["url"] for ing in preload.local_payload["ingested"]])
        if preload.shortlist_payload.get("candidates"):
            all_urls.extend([c["url"] for c in preload.shortlist_payload["candidates"]])

        if all_urls:
            unique_urls = list(dict.fromkeys(all_urls))
            for sq in sub_queries:
                rag_results = get_relevant_content({"urls": unique_urls, "query": sq})
                for url, res in rag_results.items():
                    if isinstance(res, dict) and "chunks" in res:
                        all_candidate_chunks.extend(res["chunks"])

        # 2. Extract structured evidence facts
        if all_candidate_chunks:
            # Dedupe chunks by text to avoid redundant extraction calls
            seen_texts = set()
            unique_chunks = []
            for chunk in all_candidate_chunks:
                if chunk["text"] not in seen_texts:
                    seen_texts.add(chunk["text"])
                    unique_chunks.append(chunk)

            evidence_list = extract_evidence(
                chunks=unique_chunks,
                query=query_text,
                llm_client=llm_client,
                model=model_config.get("model", ""),
                max_chunks=RESEARCH_EVIDENCE_EXTRACTION_MAX_CHUNKS,
            )

            # extract_evidence always returns List[EvidenceFact] dataclasses
            preload.evidence_payload = {"facts": [asdict(f) for f in evidence_list]}

            preload.evidence_context = format_evidence_context(evidence_list)
            preload.evidence_elapsed_ms = (time.perf_counter() - evidence_start) * 1000

            if status_callback:
                status_callback(
                    f"Evidence extraction ready: {len(evidence_list)} facts extracted "
                    f"in {preload.evidence_elapsed_ms:.0f}ms"
                )

    preload.combined_context = combine_preloaded_source_context(
        preload.local_context,
        shortlist_context,
        preload.evidence_context,
        additional_source_context,
    )
    return preload

"""Pre-LLM corpus preload orchestration for API callers."""

from __future__ import annotations

import time
import inspect
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional

from asky.config import (
    DEFAULT_CONTEXT_SIZE,
    SOURCE_SHORTLIST_ENABLED,
    SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE,
    SOURCE_SHORTLIST_ENABLE_STANDARD_MODE,
    QUERY_EXPANSION_ENABLED,
    QUERY_EXPANSION_MODE,
    QUERY_EXPANSION_MAX_SUB_QUERIES,
    RESEARCH_EVIDENCE_EXTRACTION_ENABLED,
    RESEARCH_EVIDENCE_EXTRACTION_MAX_CHUNKS,
    USER_MEMORY_ENABLED,
    USER_MEMORY_RECALL_TOP_K,
    USER_MEMORY_RECALL_MIN_SIMILARITY,
    SUMMARIZE_PAGE_PROMPT,
)
from asky.lazy_imports import call_attr

from .types import PreloadResolution

StatusCallback = Callable[[str], None]
SEED_URL_CONTEXT_BUDGET_RATIO = 0.8
MODEL_CHARS_PER_TOKEN_ESTIMATE = 4
SUMMARY_TRUNCATION_SUFFIX = "..."
SUMMARY_TRUNCATION_SUFFIX_LENGTH = len(SUMMARY_TRUNCATION_SUFFIX)


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


def recall_memories(*args: Any, **kwargs: Any) -> Any:
    """Lazy import memory recall pipeline."""
    return call_attr(
        "asky.memory.recall",
        "recall_memories_for_query",
        *args,
        **kwargs,
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
    shortlist_override: Optional[str] = None,
) -> tuple[bool, str]:
    """Resolve shortlist enablement with precedence: lean > request > model > global."""
    if lean:
        return False, "lean_flag"

    normalized_override = (
        str(shortlist_override).strip().lower() if shortlist_override else "auto"
    )
    if normalized_override == "on":
        return True, "request_override_on"
    if normalized_override == "off":
        return False, "request_override_off"

    model_override = model_config.get("source_shortlist_enabled")
    if model_override in (True, False):
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


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    """Deduplicate strings while preserving first-seen order."""
    seen = set()
    deduped: List[str] = []
    for value in values:
        token = str(value).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _collect_preloaded_source_urls(
    *,
    local_payload: Dict[str, Any],
    shortlist_payload: Dict[str, Any],
) -> List[str]:
    """Collect corpus source URLs cached during preload."""
    urls: List[str] = []
    for item in local_payload.get("ingested", []) or []:
        if not isinstance(item, dict):
            continue
        source_handle = str(item.get("source_handle", "") or "").strip()
        if source_handle:
            urls.append(source_handle)
            continue
        target = str(item.get("target", "") or "").strip()
        if target:
            urls.append(target)
    for item in shortlist_payload.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if url:
            urls.append(url)
    for item in shortlist_payload.get("seed_url_documents", []) or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("resolved_url") or item.get("url") or "").strip()
        if url:
            urls.append(url)
    return _dedupe_preserve_order(urls)


def _collect_source_handles(local_payload: Dict[str, Any]) -> Dict[str, str]:
    """Build URL->safe-handle mapping for local corpus sources."""
    handle_map: Dict[str, str] = {}
    for item in local_payload.get("ingested", []) or []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "") or "").strip()
        handle = str(item.get("source_handle", "") or "").strip()
        if not handle:
            continue
        handle_map[handle] = handle
        if target:
            handle_map[target] = handle
    return handle_map


def summarize_seed_content(content: str, max_output_chars: int) -> str:
    """Summarize seed URL content using the existing summarization pipeline."""
    if not content:
        return ""
    return call_attr(
        "asky.summarization",
        "_summarize_content",
        content=content,
        prompt_template=SUMMARIZE_PAGE_PROMPT,
        max_output_chars=max_output_chars,
    )


def _truncate_with_ellipsis(text: str, max_chars: int) -> str:
    """Truncate text to max chars while preserving explicit truncation signal."""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= SUMMARY_TRUNCATION_SUFFIX_LENGTH:
        return SUMMARY_TRUNCATION_SUFFIX[:max_chars]
    return (
        text[: max_chars - SUMMARY_TRUNCATION_SUFFIX_LENGTH] + SUMMARY_TRUNCATION_SUFFIX
    )


def _compute_seed_url_budget_chars(model_config: Dict[str, Any]) -> int:
    """Compute combined seed URL budget in characters from model context size."""
    context_tokens = int(model_config.get("context_size", DEFAULT_CONTEXT_SIZE))
    context_chars = context_tokens * MODEL_CHARS_PER_TOKEN_ESTIMATE
    return max(0, int(context_chars * SEED_URL_CONTEXT_BUDGET_RATIO))


def format_seed_url_context(
    *,
    shortlist_payload: Dict[str, Any],
    model_config: Dict[str, Any],
    research_mode: bool,
) -> Optional[str]:
    """Build seed URL preload context with explicit delivery status labels."""
    if research_mode:
        return None

    seed_docs = shortlist_payload.get("seed_url_documents", []) or []
    if not seed_docs:
        return None

    combined_budget_chars = _compute_seed_url_budget_chars(model_config)
    raw_contents = [str(doc.get("content", "") or "") for doc in seed_docs]
    raw_total_chars = sum(len(content) for content in raw_contents)
    should_summarize = (
        raw_total_chars > combined_budget_chars and combined_budget_chars > 0
    )

    rendered_docs: List[Dict[str, str]] = []
    for doc in seed_docs:
        doc_content = str(doc.get("content", "") or "")
        doc_error = str(doc.get("error", "") or "")
        if doc_error:
            rendered_docs.append(
                {
                    "url": str(doc.get("url", "") or ""),
                    "resolved_url": str(doc.get("resolved_url", "") or ""),
                    "title": str(doc.get("title", "") or ""),
                    "status": "fetch_error",
                    "content": _truncate_with_ellipsis(
                        doc_error, combined_budget_chars
                    ),
                }
            )
            continue

        if should_summarize:
            summary_text = summarize_seed_content(
                content=doc_content,
                max_output_chars=combined_budget_chars,
            )
            rendered_docs.append(
                {
                    "url": str(doc.get("url", "") or ""),
                    "resolved_url": str(doc.get("resolved_url", "") or ""),
                    "title": str(doc.get("title", "") or ""),
                    "status": "summarized_due_budget",
                    "content": summary_text,
                }
            )
            continue

        rendered_docs.append(
            {
                "url": str(doc.get("url", "") or ""),
                "resolved_url": str(doc.get("resolved_url", "") or ""),
                "title": str(doc.get("title", "") or ""),
                "status": "full_content",
                "content": doc_content,
            }
        )

    remaining_chars = combined_budget_chars
    for item in rendered_docs:
        if item["status"] == "fetch_error":
            continue
        if len(item["content"]) <= remaining_chars:
            remaining_chars -= len(item["content"])
            continue

        item["content"] = _truncate_with_ellipsis(item["content"], remaining_chars)
        item["status"] = "summary_truncated_due_budget"
        remaining_chars = 0

    lines = ["Seed URL Content from Query:"]
    for index, item in enumerate(rendered_docs, start=1):
        header = f"{index}. URL: {item['url']}"
        if item["resolved_url"] and item["resolved_url"] != item["url"]:
            header += f" (resolved: {item['resolved_url']})"
        lines.extend(
            [
                header,
                f"   Delivery status: {item['status']}",
            ]
        )
        if item["title"]:
            lines.append(f"   Title: {item['title']}")
        lines.append("   Content:")
        lines.append(item["content"] if item["content"] else "[empty]")
        lines.append("")

    return "\n".join(lines).strip()


def seed_url_context_allows_direct_answer(
    *,
    shortlist_payload: Dict[str, Any],
    model_config: Dict[str, Any],
    research_mode: bool,
) -> bool:
    """Return True when seed URL preload is sufficient to answer without refetch."""
    if research_mode:
        return False

    seed_docs = shortlist_payload.get("seed_url_documents", []) or []
    if not seed_docs:
        return False

    combined_budget_chars = _compute_seed_url_budget_chars(model_config)
    if combined_budget_chars <= 0:
        return False

    raw_total_chars = 0
    for doc in seed_docs:
        if str(doc.get("error", "") or "").strip():
            return False
        raw_total_chars += len(str(doc.get("content", "") or ""))

    return raw_total_chars <= combined_budget_chars


def run_preload_pipeline(
    *,
    query_text: str,
    research_mode: bool,
    model_config: Dict[str, Any],
    lean: bool,
    preload_local_sources: bool = True,
    preload_shortlist: bool = True,
    shortlist_override: Optional[str] = None,
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
    trace_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> PreloadResolution:
    """Run local+shortlist preloads and return their combined context payload."""
    preload = PreloadResolution()

    # Memory recall — runs in all modes except lean
    if USER_MEMORY_ENABLED and not lean:
        preload.memory_context = recall_memories(
            query_text=query_text,
            top_k=USER_MEMORY_RECALL_TOP_K,
            min_similarity=USER_MEMORY_RECALL_MIN_SIMILARITY,
        )

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
        shortlist_override=shortlist_override,
    )
    if not preload_shortlist:
        shortlist_enabled = False
        shortlist_reason = "request_disabled"
    preload.shortlist_enabled = shortlist_enabled
    preload.shortlist_reason = shortlist_reason

    shortlist_payload: Dict[str, Any] = {
        "enabled": False,
        "seed_url_documents": [],
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
        shortlist_kwargs: Dict[str, Any] = {
            "user_prompt": query_text,
            "research_mode": research_mode,
            "status_callback": status_callback,
            "queries": sub_queries if len(sub_queries) > 1 else None,
        }
        try:
            signature = inspect.signature(shortlist_executor)
            supports_trace = "trace_callback" in signature.parameters or any(
                param.kind is inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
        except (TypeError, ValueError):
            supports_trace = False
        if supports_trace:
            shortlist_kwargs["trace_callback"] = trace_callback
        shortlist_payload = shortlist_executor(**shortlist_kwargs)
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
    preload.seed_url_context = format_seed_url_context(
        shortlist_payload=shortlist_payload,
        model_config=model_config,
        research_mode=research_mode,
    )
    preload.seed_url_direct_answer_ready = seed_url_context_allows_direct_answer(
        shortlist_payload=shortlist_payload,
        model_config=model_config,
        research_mode=research_mode,
    )
    preload.shortlist_context = shortlist_context
    preload.shortlist_elapsed_ms = shortlist_elapsed_ms
    preload.shortlist_stats = shortlist_stats_builder(
        shortlist_payload,
        shortlist_elapsed_ms,
    )
    preload.preloaded_source_urls = _collect_preloaded_source_urls(
        local_payload=preload.local_payload,
        shortlist_payload=preload.shortlist_payload,
    )
    preload.preloaded_source_handles = _collect_source_handles(preload.local_payload)

    # Post-retrieval evidence extraction (optional)
    #
    # HEURISTIC: In Research Mode, if we have a high-quality shortlist (>= 3 sources),
    # we SKIP bootstrap evidence extraction. This prevents the LLM from feeling
    # "finished" too early and forces it to use its RAG tools for deeper reading.
    has_good_shortlist = len(preload.shortlist_payload.get("candidates", []) or []) >= 3
    should_run_evidence = (
        research_mode
        and RESEARCH_EVIDENCE_EXTRACTION_ENABLED
        and preload.is_corpus_preloaded
        and sub_queries
        and not has_good_shortlist
    )

    if should_run_evidence:
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
        preload.seed_url_context,
        shortlist_context,
        preload.evidence_context,
        additional_source_context,
    )
    return preload

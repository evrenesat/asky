"""Pre-LLM local-source ingestion helpers for research mode."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from asky.research.adapters import (
    extract_local_source_targets,
    fetch_source_via_adapter,
)
from asky.research.cache import ResearchCache
from asky.research.chunker import chunk_text
from asky.research.vector_store import get_vector_store

logger = logging.getLogger(__name__)

DEFAULT_MAX_LOCAL_TARGETS = 20
DEFAULT_MAX_DISCOVERED_LINKS_PER_TARGET = 40
LOCAL_CONTENT_INDEXING_MIN_CHARS = 1
MAX_CONTEXT_SOURCE_HANDLES = 6

StatusCallback = Callable[[str], None]


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _notify_status(callback: Optional[StatusCallback], message: str) -> None:
    if callback is None:
        return
    try:
        callback(message)
    except Exception:
        logger.debug("local ingestion status callback failed", exc_info=True)


def _cache_key_for_target(target: str) -> str:
    """Normalize direct file paths so cache keys stay stable across sessions."""
    if not target:
        return target
    if target.startswith("local://") or target.startswith("file://"):
        return target

    path = Path(target).expanduser()
    if path.exists():
        try:
            return f"local://{path.resolve().as_posix()}"
        except Exception:
            return str(path)
    return target


def _ensure_chunk_embeddings(
    cache_id: int,
    content: str,
    vector_store: Any,
) -> int:
    """Embed chunk vectors when missing for current embedding model."""
    if len(content) < LOCAL_CONTENT_INDEXING_MIN_CHARS:
        return 0

    has_embeddings = vector_store.has_chunk_embeddings(cache_id)
    embedding_model = getattr(vector_store.embedding_client, "model", "")
    model_check = getattr(vector_store, "has_chunk_embeddings_for_model", None)
    if callable(model_check):
        model_result = model_check(cache_id, embedding_model)
        if model_result in (True, False):
            has_embeddings = model_result

    if has_embeddings:
        return 0

    chunks = chunk_text(content)
    if not chunks:
        return 0
    return int(vector_store.store_chunk_embeddings(cache_id, chunks))


def preload_local_research_sources(
    user_prompt: str,
    status_callback: Optional[StatusCallback] = None,
    max_targets: int = DEFAULT_MAX_LOCAL_TARGETS,
    max_discovered_links_per_target: int = DEFAULT_MAX_DISCOVERED_LINKS_PER_TARGET,
    explicit_targets: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Preload local sources into research cache/vector store before first LLM call."""
    if explicit_targets:
        discovered_targets = explicit_targets
    else:
        discovered_targets = extract_local_source_targets(user_prompt)

    if explicit_targets and len(explicit_targets) > max_targets:
        # Warn about truncation
        logger.warning(
            f"{len(explicit_targets)} local corpus paths provided, but max is {max_targets}. Truncating."
        )

    targets = _dedupe_preserve_order(discovered_targets)[:max_targets]
    payload: Dict[str, Any] = {
        "enabled": bool(targets),
        "targets": targets,
        "ingested": [],
        "warnings": [],
        "stats": {
            "targets": len(targets),
            "processed_targets": 0,
            "processed_documents": 0,
            "indexed_chunks": 0,
            "elapsed_ms": 0.0,
        },
    }
    if not targets:
        return payload

    started = time.perf_counter()
    cache = ResearchCache()
    vector_store = get_vector_store()
    processed_urls = set()

    for index, target in enumerate(targets, start=1):
        _notify_status(
            status_callback,
            f"Local corpus: ingesting source {index}/{len(targets)}",
        )
        seed_payload = fetch_source_via_adapter(
            target=target,
            operation="discover",
            max_links=max_discovered_links_per_target,
        )
        if seed_payload is None:
            payload["warnings"].append(
                f"No local adapter available for target: {target}"
            )
            continue
        if seed_payload.get("error"):
            payload["warnings"].append(
                f"Failed to ingest local target {target}: {seed_payload['error']}"
            )
            continue

        candidate_documents: List[tuple[str, Dict[str, Any], str]] = [
            (target, seed_payload, "seed"),
        ]
        for link in (seed_payload.get("links") or [])[:max_discovered_links_per_target]:
            link_target = str(link.get("href", "")).strip()
            if not link_target:
                continue
            doc_payload = fetch_source_via_adapter(
                target=link_target,
                operation="read",
                max_links=0,
            )
            if doc_payload is None:
                continue
            if doc_payload.get("error"):
                payload["warnings"].append(
                    f"Failed to read discovered local source {link_target}: {doc_payload['error']}"
                )
                continue
            candidate_documents.append((link_target, doc_payload, "discovered"))

        for document_target, document_payload, source_type in candidate_documents:
            if document_payload.get("is_directory_discovery"):
                continue

            canonical_target = str(
                document_payload.get("resolved_target") or document_target
            )
            cache_key = _cache_key_for_target(canonical_target)
            if cache_key in processed_urls:
                continue
            processed_urls.add(cache_key)

            content = str(document_payload.get("content", "") or "")
            title = str(document_payload.get("title", "") or document_target)
            links = document_payload.get("links") or []
            cache_id = cache.cache_url(
                url=cache_key,
                content=content,
                title=title,
                links=links,
                trigger_summarization=bool(content),
            )
            indexed_chunks = _ensure_chunk_embeddings(
                cache_id=cache_id,
                content=content,
                vector_store=vector_store,
            )
            if content:
                payload["ingested"].append(
                    {
                        "target": cache_key,
                        "source_id": cache_id,
                        "source_handle": f"corpus://cache/{cache_id}",
                        "title": title,
                        "source_type": source_type,
                        "content_chars": len(content),
                        "indexed_chunks": indexed_chunks,
                    }
                )
                payload["stats"]["processed_documents"] += 1
                payload["stats"]["indexed_chunks"] += indexed_chunks

        payload["stats"]["processed_targets"] += 1

    payload["stats"]["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return payload


def format_local_ingestion_context(local_payload: Dict[str, Any]) -> Optional[str]:
    """Format local-ingestion results into a path-redacted context block."""
    ingested = local_payload.get("ingested") or []
    if not ingested:
        return None

    total_chars = sum(int(item.get("content_chars", 0) or 0) for item in ingested)
    total_chunks = sum(int(item.get("indexed_chunks", 0) or 0) for item in ingested)
    lines = [
        "Local knowledge base preloaded before tool calls:",
        f"- Documents indexed: {len(ingested)}",
        f"- Chunk embeddings added: {total_chunks}",
        f"- Total indexed characters: {total_chars}",
    ]
    handles = [
        str(item.get("source_handle", "")).strip()
        for item in ingested
        if str(item.get("source_handle", "")).strip()
    ]
    if handles:
        shown = ", ".join(handles[:MAX_CONTEXT_SOURCE_HANDLES])
        if len(handles) > MAX_CONTEXT_SOURCE_HANDLES:
            shown += ", ..."
        lines.append(f"- Source handles: {shown}")

    warnings = local_payload.get("warnings") or []
    if warnings:
        lines.append(f"- Warnings: {len(warnings)} (see logs/verbose output).")

    return "\n".join(lines)

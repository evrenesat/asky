"""Source ingestion for manual persona creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from asky.research.chunker import chunk_text
from asky.research.adapters import fetch_source_via_adapter

MAX_INGEST_SOURCES = 32
MAX_CHUNKS_PER_SOURCE = 128
MIN_CHUNK_CHARS = 24
SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
}


def ingest_persona_sources(
    *,
    sources: Sequence[str],
    max_sources: int = MAX_INGEST_SOURCES,
    max_chunks_per_source: int = MAX_CHUNKS_PER_SOURCE,
    min_chunk_chars: int = MIN_CHUNK_CHARS,
) -> Dict[str, Any]:
    """Ingest local sources into normalized chunk/provenance records."""
    normalized_sources = _expand_sources(sources)[: int(max_sources)]
    chunks: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for source_index, source in enumerate(normalized_sources, start=1):
        source_payload, warning = _load_source_payload(source)
        if warning:
            warnings.append(warning)
        if not source_payload:
            continue

        text = str(source_payload.get("content", "") or "").strip()
        if not text:
            warnings.append(f"source '{source}' has no usable content")
            continue

        title = str(source_payload.get("title", "") or _source_label(source))
        source_chunks = chunk_text(text)
        if not source_chunks:
            warnings.append(f"source '{source}' produced zero chunks")
            continue

        selected_chunks = source_chunks[: int(max_chunks_per_source)]
        for chunk_index, chunk in enumerate(selected_chunks, start=1):
            chunk_text_value = str(chunk or "").strip()
            if len(chunk_text_value) < int(min_chunk_chars):
                continue
            chunks.append(
                {
                    "chunk_id": f"{source_index}:{chunk_index}",
                    "chunk_index": chunk_index,
                    "text": chunk_text_value,
                    "source": _source_label(source),
                    "title": title,
                }
            )

    return {
        "sources": list(normalized_sources),
        "chunks": chunks,
        "warnings": warnings,
        "stats": {
            "requested_sources": len(list(sources)),
            "processed_sources": len(normalized_sources),
            "normalized_chunks": len(chunks),
            "warning_count": len(warnings),
        },
    }


def _expand_sources(sources: Sequence[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for raw_source in sources:
        source = str(raw_source or "").strip()
        if not source:
            continue
        path = Path(source).expanduser()
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                if child.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
                    continue
                child_str = str(child)
                if child_str in seen:
                    continue
                seen.add(child_str)
                deduped.append(child_str)
            continue

        if source in seen:
            continue
        seen.add(source)
        deduped.append(source)

    return deduped


def _load_source_payload(source: str) -> Tuple[Dict[str, Any], str]:
    adapter_payload: Dict[str, Any] = {}
    warning = ""
    try:
        payload = fetch_source_via_adapter(
            target=source,
            operation="discover",
            max_links=0,
        )
        if isinstance(payload, dict) and not payload.get("error"):
            adapter_payload = payload
        elif isinstance(payload, dict) and payload.get("error"):
            warning = f"source '{source}' adapter error: {payload.get('error')}"
    except Exception as exc:
        warning = f"source '{source}' adapter failed: {exc}"

    if adapter_payload.get("content"):
        return adapter_payload, warning

    path = Path(source).expanduser()
    if path.exists() and path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return {
                "content": text,
                "title": path.name,
            }, warning
        except Exception as exc:
            return {}, f"source '{source}' read failed: {exc}"

    if not warning:
        warning = f"source '{source}' could not be read"
    return {}, warning


def _source_label(source: str) -> str:
    path = Path(source).expanduser()
    if path.exists():
        return path.name
    return str(source or "").strip()

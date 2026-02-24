"""Tool registration for manual persona creator plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.ingestion import ingest_persona_sources
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    list_persona_names,
    persona_exists,
    read_chunks,
    read_metadata,
    touch_updated_at,
    validate_persona_name,
    write_chunks,
    write_metadata,
)

TOOL_CREATE_PERSONA = "manual_persona_create"
TOOL_ADD_SOURCES = "manual_persona_add_sources"
TOOL_LIST_PERSONAS = "manual_persona_list"
TOOL_EXPORT_PERSONA = "manual_persona_export"

DEFAULT_MAX_INGEST_SOURCES = 32
DEFAULT_MAX_CHUNKS_PER_SOURCE = 128
DEFAULT_MIN_CHUNK_CHARS = 24


def register_manual_persona_tools(
    *,
    registry: Any,
    data_dir: Path,
    plugin_config: Dict[str, Any],
) -> None:
    """Register manual persona creator tool set."""
    registry.register(
        TOOL_CREATE_PERSONA,
        {
            "name": TOOL_CREATE_PERSONA,
            "description": "Create a persona from a manual prompt and optional local sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "behavior_prompt": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "behavior_prompt"],
            },
        },
        lambda args: create_manual_persona(args, data_dir=data_dir, plugin_config=plugin_config),
    )

    registry.register(
        TOOL_ADD_SOURCES,
        {
            "name": TOOL_ADD_SOURCES,
            "description": "Ingest more local sources for an existing manual persona.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name", "sources"],
            },
        },
        lambda args: add_persona_sources(args, data_dir=data_dir, plugin_config=plugin_config),
    )

    registry.register(
        TOOL_LIST_PERSONAS,
        {
            "name": TOOL_LIST_PERSONAS,
            "description": "List locally available manual personas.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        lambda _args: {"personas": list_persona_names(data_dir)},
    )

    registry.register(
        TOOL_EXPORT_PERSONA,
        {
            "name": TOOL_EXPORT_PERSONA,
            "description": "Export a persona package ZIP with prompt, metadata, and normalized chunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "output_path": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        lambda args: export_manual_persona(args, data_dir=data_dir),
    )


def create_manual_persona(
    args: Dict[str, Any],
    *,
    data_dir: Path,
    plugin_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Tool executor for manual persona creation."""
    try:
        name = validate_persona_name(str(args.get("name", "") or ""))
    except ValueError as exc:
        return {"error": str(exc)}

    if persona_exists(data_dir, name):
        return {"error": f"persona '{name}' already exists"}

    behavior_prompt = str(args.get("behavior_prompt", "") or "").strip()
    if not behavior_prompt:
        return {"error": "behavior_prompt is required"}

    description = str(args.get("description", "") or "").strip()
    sources = _normalize_sources(args.get("sources"))

    paths = create_persona(
        data_dir=data_dir,
        persona_name=name,
        description=description,
        behavior_prompt=behavior_prompt,
    )

    ingestion = ingest_persona_sources(
        sources=sources,
        max_sources=int(plugin_config.get("max_ingest_sources", DEFAULT_MAX_INGEST_SOURCES)),
        max_chunks_per_source=int(
            plugin_config.get("max_chunks_per_source", DEFAULT_MAX_CHUNKS_PER_SOURCE)
        ),
        min_chunk_chars=int(plugin_config.get("min_chunk_chars", DEFAULT_MIN_CHUNK_CHARS)),
    )

    chunks = ingestion.get("chunks", []) or []
    write_chunks(paths.chunks_path, chunks)
    metadata = read_metadata(paths.metadata_path)
    persona_block = metadata.setdefault("persona", {})
    persona_block["sources"] = ingestion.get("sources", [])
    persona_block["source_warning_count"] = int(
        len(ingestion.get("warnings", []) or [])
    )
    write_metadata(paths.metadata_path, metadata)
    touch_updated_at(paths.metadata_path)

    return {
        "ok": True,
        "name": name,
        "chunks": len(chunks),
        "warnings": ingestion.get("warnings", []),
        "stats": ingestion.get("stats", {}),
    }


def add_persona_sources(
    args: Dict[str, Any],
    *,
    data_dir: Path,
    plugin_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Tool executor to add persona source documents."""
    try:
        name = validate_persona_name(str(args.get("name", "") or ""))
    except ValueError as exc:
        return {"error": str(exc)}

    if not persona_exists(data_dir, name):
        return {"error": f"persona '{name}' does not exist"}

    sources = _normalize_sources(args.get("sources"))
    if not sources:
        return {"error": "sources must include at least one entry"}

    paths = get_persona_paths(data_dir, name)
    existing_chunks = read_chunks(paths.chunks_path)
    ingestion = ingest_persona_sources(
        sources=sources,
        max_sources=int(plugin_config.get("max_ingest_sources", DEFAULT_MAX_INGEST_SOURCES)),
        max_chunks_per_source=int(
            plugin_config.get("max_chunks_per_source", DEFAULT_MAX_CHUNKS_PER_SOURCE)
        ),
        min_chunk_chars=int(plugin_config.get("min_chunk_chars", DEFAULT_MIN_CHUNK_CHARS)),
    )
    new_chunks = ingestion.get("chunks", []) or []
    write_chunks(paths.chunks_path, list(existing_chunks) + list(new_chunks))

    metadata = read_metadata(paths.metadata_path)
    persona_block = metadata.setdefault("persona", {})
    old_sources = list(persona_block.get("sources", []) or [])
    combined_sources = _dedupe_preserve_order(old_sources + list(ingestion.get("sources", []) or []))
    persona_block["sources"] = combined_sources
    persona_block["source_warning_count"] = int(
        len(ingestion.get("warnings", []) or [])
    )
    write_metadata(paths.metadata_path, metadata)
    touch_updated_at(paths.metadata_path)

    return {
        "ok": True,
        "name": name,
        "added_chunks": len(new_chunks),
        "total_chunks": len(existing_chunks) + len(new_chunks),
        "warnings": ingestion.get("warnings", []),
    }


def export_manual_persona(args: Dict[str, Any], *, data_dir: Path) -> Dict[str, Any]:
    """Tool executor to export a persona package ZIP."""
    try:
        name = validate_persona_name(str(args.get("name", "") or ""))
    except ValueError as exc:
        return {"error": str(exc)}
    if not persona_exists(data_dir, name):
        return {"error": f"persona '{name}' does not exist"}

    output_path = args.get("output_path")
    try:
        archive_path = export_persona_package(
            data_dir=data_dir,
            persona_name=name,
            output_path=str(output_path) if output_path else None,
        )
    except Exception as exc:
        return {"error": f"export failed: {exc}"}

    return {"ok": True, "name": name, "archive_path": str(archive_path)}


def _normalize_sources(raw_sources: Any) -> List[str]:
    if raw_sources is None:
        return []
    if isinstance(raw_sources, str):
        candidate = raw_sources.strip()
        return [candidate] if candidate else []
    if not isinstance(raw_sources, Sequence):
        return []

    normalized: List[str] = []
    for item in raw_sources:
        value = str(item or "").strip()
        if value:
            normalized.append(value)
    return _dedupe_preserve_order(normalized)


def _dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped

"""Persona package export helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZIP_DEFLATED, ZipFile

import tomlkit

from asky.plugins.manual_persona_creator.storage import (
    PERSONA_SCHEMA_VERSION,
    get_persona_paths,
    read_chunks,
    read_metadata,
    read_prompt,
)

EXPORTS_DIR_NAME = "exports"
EXPORT_METADATA_FILENAME = "metadata.toml"
EXPORT_PROMPT_FILENAME = "behavior_prompt.md"
EXPORT_CHUNKS_FILENAME = "chunks.json"


def export_persona_package(
    *,
    data_dir: Path,
    persona_name: str,
    output_path: Optional[str] = None,
) -> Path:
    """Export persona into portable ZIP package."""
    paths = get_persona_paths(data_dir, persona_name)
    metadata = read_metadata(paths.metadata_path)
    prompt_text = read_prompt(paths.prompt_path)
    chunks = _sanitize_chunks(read_chunks(paths.chunks_path))

    chunks_payload = json.dumps(chunks, ensure_ascii=True, indent=2)
    checksums = {
        EXPORT_PROMPT_FILENAME: _sha256_hex(prompt_text.encode("utf-8")),
        EXPORT_CHUNKS_FILENAME: _sha256_hex(chunks_payload.encode("utf-8")),
    }

    metadata_payload = _build_export_metadata(metadata, checksums)
    metadata_rendered = tomlkit.dumps(metadata_payload)

    destination = _resolve_output_path(
        data_dir=data_dir,
        persona_name=persona_name,
        output_path=output_path,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)

    temp_destination = destination.with_suffix(destination.suffix + ".tmp")
    with ZipFile(temp_destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(EXPORT_METADATA_FILENAME, metadata_rendered)
        archive.writestr(EXPORT_PROMPT_FILENAME, prompt_text)
        archive.writestr(EXPORT_CHUNKS_FILENAME, chunks_payload)
    temp_destination.replace(destination)

    return destination


def _resolve_output_path(
    *,
    data_dir: Path,
    persona_name: str,
    output_path: Optional[str],
) -> Path:
    if output_path:
        return Path(output_path).expanduser()
    exports_dir = data_dir / EXPORTS_DIR_NAME
    filename = f"{persona_name}-schema{PERSONA_SCHEMA_VERSION}.zip"
    return exports_dir / filename


def _build_export_metadata(
    metadata: Dict[str, Any],
    checksums: Dict[str, str],
):
    document = tomlkit.document()
    persona_block = dict(metadata.get("persona", {}))
    persona_block["schema_version"] = PERSONA_SCHEMA_VERSION
    persona_block["exported_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    document["persona"] = persona_block
    document["checksums"] = dict(checksums)
    return document


def _sanitize_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for chunk in chunks:
        source_value = str(chunk.get("source", "") or "").strip()
        source_label = Path(source_value).name if Path(source_value).is_absolute() else source_value
        sanitized.append(
            {
                "chunk_id": str(chunk.get("chunk_id", "") or "").strip(),
                "chunk_index": int(chunk.get("chunk_index", 0) or 0),
                "text": str(chunk.get("text", "") or ""),
                "source": source_label,
                "title": str(chunk.get("title", "") or "").strip(),
            }
        )
    return sanitized


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

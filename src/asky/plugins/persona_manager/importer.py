"""Persona package import helpers."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Dict
from zipfile import ZipFile

from asky.plugins.manual_persona_creator.storage import (
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PERSONA_SCHEMA_VERSION,
    PERSONAS_DIR_NAME,
    PROMPT_FILENAME,
    get_persona_paths,
    validate_persona_name,
    write_chunks,
    write_metadata,
    write_prompt,
)
from asky.plugins.persona_manager.knowledge import rebuild_embeddings

REQUIRED_ARCHIVE_MEMBERS = {
    METADATA_FILENAME,
    PROMPT_FILENAME,
    CHUNKS_FILENAME,
}


def import_persona_archive(*, data_dir: Path, archive_path: str) -> Dict[str, Any]:
    """Import persona ZIP package and rebuild embeddings."""
    path = Path(archive_path).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"persona archive not found: {path}")

    with ZipFile(path, "r") as archive:
        members = set(archive.namelist())
        missing = sorted(REQUIRED_ARCHIVE_MEMBERS - members)
        if missing:
            raise ValueError(f"persona archive missing required file(s): {', '.join(missing)}")

        for member_name in members:
            _validate_archive_member(member_name)

        metadata = tomllib.loads(
            archive.read(METADATA_FILENAME).decode("utf-8")
        )
        prompt_text = archive.read(PROMPT_FILENAME).decode("utf-8")
        chunks = json.loads(archive.read(CHUNKS_FILENAME).decode("utf-8"))

    if not isinstance(metadata, dict):
        raise ValueError("persona metadata is invalid")
    persona_block = metadata.get("persona", {})
    if not isinstance(persona_block, dict):
        raise ValueError("persona metadata missing [persona] section")

    schema_version = int(persona_block.get("schema_version", 0) or 0)
    if schema_version != PERSONA_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported persona schema version {schema_version}; expected {PERSONA_SCHEMA_VERSION}"
        )

    persona_name = validate_persona_name(str(persona_block.get("name", "") or ""))
    if not isinstance(chunks, list):
        raise ValueError("persona chunks file must be a JSON array")

    personas_root = data_dir / PERSONAS_DIR_NAME
    personas_root.mkdir(parents=True, exist_ok=True)
    paths = get_persona_paths(data_dir, persona_name)
    paths.root_dir.mkdir(parents=True, exist_ok=True)

    write_metadata(paths.metadata_path, metadata)
    write_prompt(paths.prompt_path, prompt_text)
    write_chunks(paths.chunks_path, chunks)

    embedding_stats = rebuild_embeddings(persona_dir=paths.root_dir, chunks=chunks)

    return {
        "ok": True,
        "name": persona_name,
        "path": str(paths.root_dir),
        "chunks": len(chunks),
        "embedding_stats": embedding_stats,
    }


def _validate_archive_member(member_name: str) -> None:
    normalized = PurePosixPath(str(member_name or ""))
    if normalized.is_absolute():
        raise ValueError("persona archive contains absolute path")
    if any(part == ".." for part in normalized.parts):
        raise ValueError("persona archive contains path traversal entry")

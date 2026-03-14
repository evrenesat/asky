"""Persona package import helpers."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Dict
from zipfile import ZipFile

from asky.plugins.manual_persona_creator.knowledge_catalog import (
    KNOWLEDGE_DIR_NAME,
    get_knowledge_paths,
    rebuild_catalog_from_legacy,
)
from asky.plugins.manual_persona_creator.runtime_index import rebuild_runtime_index
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PERSONAS_DIR_NAME,
    PROMPT_FILENAME,
    SUPPORTED_SCHEMA_VERSIONS,
    get_persona_paths,
    validate_persona_name,
    write_chunks,
    write_metadata,
    write_prompt,
)
from asky.plugins.persona_manager.errors import InvalidPersonaPackageError
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
        raise InvalidPersonaPackageError(
            str(path),
            "archive file not found"
        )

    with ZipFile(path, "r") as archive:
        members = set(archive.namelist())
        missing = sorted(REQUIRED_ARCHIVE_MEMBERS - members)
        if missing:
            raise InvalidPersonaPackageError(
                str(path),
                f"missing required file(s): {', '.join(missing)}"
            )

        for member_name in members:
            _validate_archive_member(member_name, str(path))

        metadata = tomllib.loads(
            archive.read(METADATA_FILENAME).decode("utf-8")
        )
        prompt_text = archive.read(PROMPT_FILENAME).decode("utf-8")
        chunks = json.loads(archive.read(CHUNKS_FILENAME).decode("utf-8"))

    if not isinstance(metadata, dict):
        raise InvalidPersonaPackageError(str(path), "metadata is invalid")
    persona_block = metadata.get("persona", {})
    if not isinstance(persona_block, dict):
        raise InvalidPersonaPackageError(str(path), "metadata missing [persona] section")

    schema_version = int(persona_block.get("schema_version", 0) or 0)
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise InvalidPersonaPackageError(
            str(path),
            f"unsupported schema version {schema_version}; expected one of {SUPPORTED_SCHEMA_VERSIONS}"
        )

    persona_name = validate_persona_name(str(persona_block.get("name", "") or ""))
    if not isinstance(chunks, list):
        raise InvalidPersonaPackageError(str(path), "chunks file must be a JSON array")

    personas_root = data_dir / PERSONAS_DIR_NAME
    personas_root.mkdir(parents=True, exist_ok=True)
    paths = get_persona_paths(data_dir, persona_name)
    paths.root_dir.mkdir(parents=True, exist_ok=True)

    write_metadata(paths.metadata_path, metadata)
    write_prompt(paths.prompt_path, prompt_text)
    write_chunks(paths.chunks_path, chunks)

    # Extract additional artifacts (authored-books, knowledge-catalog) if present
    with ZipFile(path, "r") as archive:
        for member_name in archive.namelist():
            if member_name.startswith(f"{AUTHORED_BOOKS_DIR_NAME}/") or \
               member_name.startswith(f"{KNOWLEDGE_DIR_NAME}/"):
                target_path = paths.root_dir / member_name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(archive.read(member_name))

    # Ensure catalog exists for legacy schemas
    if schema_version < 3:
        k_paths = get_knowledge_paths(paths.root_dir)
        if not k_paths["sources"].exists() or not k_paths["entries"].exists():
            rebuild_catalog_from_legacy(paths.root_dir)

    embedding_stats = rebuild_embeddings(persona_dir=paths.root_dir, chunks=chunks)
    rebuild_runtime_index(persona_dir=paths.root_dir)

    return {
        "ok": True,
        "name": persona_name,
        "path": str(paths.root_dir),
        "chunks": len(chunks),
        "embedding_stats": embedding_stats,
    }


def _validate_archive_member(member_name: str, archive_path: str) -> None:
    normalized = PurePosixPath(str(member_name or ""))
    if normalized.is_absolute():
        raise InvalidPersonaPackageError(archive_path, "contains absolute path")
    if any(part == ".." for part in normalized.parts):
        raise InvalidPersonaPackageError(archive_path, "contains path traversal entry")

"""Persistence helpers for manual persona creator plugin."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import tomlkit

PERSONA_SCHEMA_VERSION = 1
PERSONAS_DIR_NAME = "personas"
METADATA_FILENAME = "metadata.toml"
PROMPT_FILENAME = "behavior_prompt.md"
CHUNKS_FILENAME = "chunks.json"
PERSONA_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


@dataclass(frozen=True)
class PersonaPaths:
    """Filesystem layout for one persona."""

    root_dir: Path
    metadata_path: Path
    prompt_path: Path
    chunks_path: Path


def validate_persona_name(name: str) -> str:
    """Validate and normalize persona name."""
    normalized = str(name or "").strip()
    if not PERSONA_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "persona name must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$"
        )
    return normalized


def get_personas_root(data_dir: Path) -> Path:
    """Return canonical persona root directory."""
    return data_dir / PERSONAS_DIR_NAME


def get_persona_paths(data_dir: Path, persona_name: str) -> PersonaPaths:
    """Resolve canonical files for one persona."""
    validated_name = validate_persona_name(persona_name)
    persona_root = get_personas_root(data_dir) / validated_name
    return PersonaPaths(
        root_dir=persona_root,
        metadata_path=persona_root / METADATA_FILENAME,
        prompt_path=persona_root / PROMPT_FILENAME,
        chunks_path=persona_root / CHUNKS_FILENAME,
    )


def list_persona_names(data_dir: Path) -> List[str]:
    """List personas in deterministic order."""
    personas_root = get_personas_root(data_dir)
    if not personas_root.exists():
        return []
    names = [path.name for path in personas_root.iterdir() if path.is_dir()]
    return sorted(names)


def persona_exists(data_dir: Path, persona_name: str) -> bool:
    """Return whether persona storage exists."""
    paths = get_persona_paths(data_dir, persona_name)
    return paths.metadata_path.exists() and paths.prompt_path.exists()


def create_persona(
    *,
    data_dir: Path,
    persona_name: str,
    description: str,
    behavior_prompt: str,
) -> PersonaPaths:
    """Create canonical persona directory and base files."""
    paths = get_persona_paths(data_dir, persona_name)
    paths.root_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "persona": {
            "name": validate_persona_name(persona_name),
            "description": str(description or "").strip(),
            "schema_version": PERSONA_SCHEMA_VERSION,
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        }
    }
    write_metadata(paths.metadata_path, metadata)
    write_prompt(paths.prompt_path, behavior_prompt)
    if not paths.chunks_path.exists():
        write_chunks(paths.chunks_path, [])
    return paths


def read_metadata(metadata_path: Path) -> Dict[str, Any]:
    """Read and validate persona metadata file."""
    with metadata_path.open("rb") as file_obj:
        payload = tomllib.load(file_obj)

    persona_block = payload.get("persona", {}) if isinstance(payload, dict) else {}
    if not isinstance(persona_block, dict):
        raise ValueError("metadata is missing [persona] section")

    name = validate_persona_name(str(persona_block.get("name", "")))
    schema_version = int(persona_block.get("schema_version", 0) or 0)
    if schema_version != PERSONA_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported persona schema_version={schema_version}; expected {PERSONA_SCHEMA_VERSION}"
        )

    metadata = dict(payload)
    metadata["persona"] = dict(persona_block)
    metadata["persona"]["name"] = name
    metadata["persona"]["schema_version"] = schema_version
    return metadata


def write_metadata(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """Persist metadata atomically."""
    document = tomlkit.document()
    for key, value in metadata.items():
        document[key] = value
    rendered = tomlkit.dumps(document)
    _write_text_atomic(metadata_path, rendered)


def read_prompt(prompt_path: Path) -> str:
    """Read behavior prompt markdown."""
    return prompt_path.read_text(encoding="utf-8")


def write_prompt(prompt_path: Path, behavior_prompt: str) -> None:
    """Write behavior prompt atomically."""
    _write_text_atomic(prompt_path, str(behavior_prompt or "").strip())


def read_chunks(chunks_path: Path) -> List[Dict[str, Any]]:
    """Read and validate normalized chunk list."""
    if not chunks_path.exists():
        return []
    payload = json.loads(chunks_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("chunks.json must contain a JSON array")
    normalized: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        normalized.append(
            {
                "chunk_id": str(item.get("chunk_id", "") or "").strip(),
                "text": text,
                "source": str(item.get("source", "") or "").strip(),
                "title": str(item.get("title", "") or "").strip(),
                "chunk_index": int(item.get("chunk_index", 0) or 0),
            }
        )
    return normalized


def write_chunks(chunks_path: Path, chunks: List[Dict[str, Any]]) -> None:
    """Write normalized chunks atomically."""
    rendered = json.dumps(chunks, ensure_ascii=True, indent=2)
    _write_text_atomic(chunks_path, rendered)


def touch_updated_at(metadata_path: Path) -> None:
    """Update metadata timestamp after mutating persona data."""
    metadata = read_metadata(metadata_path)
    persona_block = metadata.setdefault("persona", {})
    persona_block["updated_at"] = _utc_now_iso()
    write_metadata(metadata_path, metadata)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)

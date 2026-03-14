"""Persistence helpers for manual persona creator plugin."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

import tomlkit

PERSONA_SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = {1, 2, 3}
PERSONAS_DIR_NAME = "personas"
METADATA_FILENAME = "metadata.toml"
PROMPT_FILENAME = "behavior_prompt.md"
CHUNKS_FILENAME = "chunks.json"

AUTHORED_BOOKS_DIR_NAME = "authored_books"
AUTHORED_BOOKS_INDEX_FILENAME = "index.json"
BOOK_METADATA_FILENAME = "book.toml"
VIEWPOINTS_FILENAME = "viewpoints.json"
REPORT_FILENAME = "report.json"

INGESTION_JOBS_DIR_NAME = "ingestion_jobs"
JOB_MANIFEST_FILENAME = "job.toml"

INGESTED_SOURCES_DIR_NAME = "ingested_sources"
SOURCE_METADATA_FILENAME = "source.toml"
SOURCE_FACTS_FILENAME = "facts.json"
SOURCE_TIMELINE_FILENAME = "timeline.json"
SOURCE_CONFLICTS_FILENAME = "conflicts.json"

SOURCE_INGESTION_JOBS_DIR_NAME = "source_ingestion_jobs"

PERSONA_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")


@dataclass(frozen=True)
class PersonaPaths:
    """Filesystem layout for one persona."""

    root_dir: Path
    metadata_path: Path
    prompt_path: Path
    chunks_path: Path


@dataclass(frozen=True)
class AuthoredBookPaths:
    """Filesystem layout for one authored book inside a persona."""

    book_dir: Path
    metadata_path: Path
    viewpoints_path: Path
    report_path: Path


@dataclass(frozen=True)
class SourceBundlePaths:
    """Filesystem layout for one milestone-3 source bundle."""

    source_dir: Path
    metadata_path: Path
    report_path: Path
    viewpoints_path: Path
    facts_path: Path
    timeline_path: Path
    conflicts_path: Path


@dataclass(frozen=True)
class IngestionJobPaths:
    """Filesystem layout for one ingestion job inside a persona."""

    job_dir: Path
    manifest_path: Path


@dataclass(frozen=True)
class SourceIngestionJobPaths:
    """Filesystem layout for one milestone-3 source ingestion job."""

    job_dir: Path
    manifest_path: Path


def validate_persona_name(name: str) -> str:
    """Validate and normalize persona name."""
    normalized = str(name or "").strip()
    if not PERSONA_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "persona name must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$"
        )
    return normalized


def get_book_key(*, title: str, publication_year: Optional[int], isbn: Optional[str]) -> str:
    """
    Generate a path-safe, deterministic book key.
    Prefers ISBN if available, otherwise uses normalized title and year.
    """
    if isbn:
        normalized_isbn = re.sub(r"[^a-zA-Z0-9]", "", isbn).lower()
        if normalized_isbn:
            return f"isbn-{normalized_isbn}"

    # Fallback to title and year
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "unknown-book"
    if publication_year:
        return f"{slug}-{publication_year}"
    return slug


def get_source_id(kind: str, bundle_text: str) -> str:
    """Generate a deterministic milestone-3 source ID."""
    fingerprint = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()[:16]
    return f"source:{kind}:{fingerprint}"


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


def get_book_paths(persona_root: Path, book_key: str) -> AuthoredBookPaths:
    """Resolve canonical files for one authored book."""
    book_dir = persona_root / AUTHORED_BOOKS_DIR_NAME / book_key
    return AuthoredBookPaths(
        book_dir=book_dir,
        metadata_path=book_dir / BOOK_METADATA_FILENAME,
        viewpoints_path=book_dir / VIEWPOINTS_FILENAME,
        report_path=book_dir / REPORT_FILENAME,
    )


def get_job_paths(persona_root: Path, job_id: str) -> IngestionJobPaths:
    """Resolve canonical files for one ingestion job."""
    job_dir = persona_root / INGESTION_JOBS_DIR_NAME / job_id
    return IngestionJobPaths(
        job_dir=job_dir,
        manifest_path=job_dir / JOB_MANIFEST_FILENAME,
    )


def get_source_bundle_paths(persona_root: Path, source_id_slug: str) -> SourceBundlePaths:
    """Resolve canonical files for one milestone-3 source bundle."""
    source_dir = persona_root / INGESTED_SOURCES_DIR_NAME / source_id_slug
    return SourceBundlePaths(
        source_dir=source_dir,
        metadata_path=source_dir / SOURCE_METADATA_FILENAME,
        report_path=source_dir / REPORT_FILENAME,
        viewpoints_path=source_dir / VIEWPOINTS_FILENAME,
        facts_path=source_dir / SOURCE_FACTS_FILENAME,
        timeline_path=source_dir / SOURCE_TIMELINE_FILENAME,
        conflicts_path=source_dir / SOURCE_CONFLICTS_FILENAME,
    )


def get_source_job_paths(persona_root: Path, job_id: str) -> SourceIngestionJobPaths:
    """Resolve canonical files for one milestone-3 source ingestion job."""
    job_dir = persona_root / SOURCE_INGESTION_JOBS_DIR_NAME / job_id
    return SourceIngestionJobPaths(
        job_dir=job_dir,
        manifest_path=job_dir / JOB_MANIFEST_FILENAME,
    )


def list_books(persona_root: Path) -> List[str]:
    """List authored book keys for a persona."""
    books_root = persona_root / AUTHORED_BOOKS_DIR_NAME
    if not books_root.exists():
        return []
    return sorted([path.name for path in books_root.iterdir() if path.is_dir()])


def list_jobs(persona_root: Path) -> List[str]:
    """List ingestion job IDs for a persona."""
    jobs_root = persona_root / INGESTION_JOBS_DIR_NAME
    if not jobs_root.exists():
        return []
    return sorted([path.name for path in jobs_root.iterdir() if path.is_dir()])


def list_source_bundles(persona_root: Path) -> List[str]:
    """List source bundle IDs for a persona."""
    sources_root = persona_root / INGESTED_SOURCES_DIR_NAME
    if not sources_root.exists():
        return []
    return sorted([path.name for path in sources_root.iterdir() if path.is_dir()])


def list_source_jobs(persona_root: Path) -> List[str]:
    """List milestone-3 source ingestion job IDs for a persona."""
    jobs_root = persona_root / SOURCE_INGESTION_JOBS_DIR_NAME
    if not jobs_root.exists():
        return []
    return sorted([path.name for path in jobs_root.iterdir() if path.is_dir()])


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
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported persona schema_version={schema_version}; expected one of {SUPPORTED_SCHEMA_VERSIONS}"
        )

    # Automatic rebuild for missing v1/v2 catalogs and runtime index
    if schema_version < 3:
        from asky.plugins.manual_persona_creator.knowledge_catalog import (
            get_knowledge_paths,
            rebuild_catalog_from_legacy,
        )
        from asky.plugins.manual_persona_creator.runtime_index import (
            rebuild_runtime_index,
            runtime_index_path,
        )

        paths = get_knowledge_paths(metadata_path.parent)
        if not paths["sources"].exists() or not paths["entries"].exists():
            rebuild_catalog_from_legacy(metadata_path.parent)
        
        if not runtime_index_path(metadata_path.parent).exists():
            rebuild_runtime_index(metadata_path.parent)

    metadata = dict(payload)
    metadata["persona"] = dict(persona_block)
    metadata["persona"]["name"] = name
    metadata["persona"]["schema_version"] = schema_version
    return metadata


def write_metadata(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """Persist metadata atomically."""
    document = tomlkit.document()
    for key, value in metadata.items():
        if value is not None:
            document[key] = _clean_toml_value(value)
    rendered = tomlkit.dumps(document)
    _write_text_atomic(metadata_path, rendered)


def read_source_metadata(metadata_path: Path) -> Dict[str, Any]:
    """Read source metadata, tolerating legacy JSON for backward compatibility."""
    if not metadata_path.exists():
        raise FileNotFoundError(f"Source metadata not found: {metadata_path}")
    
    # Try TOML first (canonical for this version)
    try:
        with metadata_path.open("rb") as file_obj:
            return tomllib.load(file_obj)
    except Exception:
        # Fallback to legacy JSON
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Could not read source metadata as TOML or JSON: {e}") from e


def write_source_metadata(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """Persist source metadata as TOML atomically."""
    document = tomlkit.document()
    for key, value in metadata.items():
        if value is not None:
            document[key] = _clean_toml_value(value)
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


def read_job_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Read and validate job manifest file."""
    with manifest_path.open("rb") as file_obj:
        return tomllib.load(file_obj)


def write_job_manifest(manifest_path: Path, manifest: Dict[str, Any]) -> None:
    """Persist job manifest atomically."""
    document = tomlkit.document()
    for key, value in manifest.items():
        if value is not None:
            document[key] = _clean_toml_value(value)
    rendered = tomlkit.dumps(document)
    _write_text_atomic(manifest_path, rendered)


def read_book_metadata(metadata_path: Path) -> Dict[str, Any]:
    """Read and validate authored book metadata file."""
    with metadata_path.open("rb") as file_obj:
        return tomllib.load(file_obj)


def write_book_metadata(metadata_path: Path, metadata: Dict[str, Any]) -> None:
    """Persist authored book metadata atomically."""
    document = tomlkit.document()
    for key, value in metadata.items():
        if value is not None:
            document[key] = _clean_toml_value(value)
    rendered = tomlkit.dumps(document)
    _write_text_atomic(metadata_path, rendered)


def touch_updated_at(metadata_path: Path) -> None:
    """Update metadata timestamp after mutating persona data."""
    metadata = read_metadata(metadata_path)
    persona_block = metadata.setdefault("persona", {})
    persona_block["updated_at"] = _utc_now_iso()
    write_metadata(metadata_path, metadata)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean_toml_value(value: Any) -> Any:
    """Recursively remove None values from dicts/lists for TOML compatibility."""
    if isinstance(value, dict):
        return {k: _clean_toml_value(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_clean_toml_value(v) for v in value if v is not None]
    return value


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)

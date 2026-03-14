"""Tests for manual persona source service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
from asky.plugins.manual_persona_creator.source_service import add_manual_sources
from asky.plugins.manual_persona_creator.storage import (
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PROMPT_FILENAME,
    write_chunks,
    write_metadata,
)


def test_add_manual_sources_success(tmp_path: Path):
    persona_root = tmp_path / "test_p"
    persona_root.mkdir()
    
    metadata = {
        "persona": {
            "name": "test_p",
            "schema_version": 3,
        }
    }
    write_metadata(persona_root / METADATA_FILENAME, metadata)
    (persona_root / PROMPT_FILENAME).write_text("prompt")
    write_chunks(persona_root / CHUNKS_FILENAME, [])

    # Create dummy source file
    source_file = tmp_path / "source.txt"
    source_file.write_text("This is some new knowledge.")
    
    result = add_manual_sources(persona_root, [str(source_file)])
    
    assert result.processed_sources == 1
    assert result.added_chunks > 0
    assert result.skipped_existing_sources == 0
    
    # Verify catalog
    catalog = read_catalog(persona_root)
    assert catalog is not None
    assert len(catalog["sources"]) == 1
    assert catalog["sources"][0].label == "source.txt"
    assert len(catalog["entries"]) == result.added_chunks
    
    # Verify legacy chunks.json
    with (persona_root / CHUNKS_FILENAME).open("r") as f:
        chunks = json.load(f)
        assert len(chunks) == result.added_chunks
        assert chunks[0]["source"] == "source.txt"


def test_add_manual_sources_deduplication(tmp_path: Path):
    persona_root = tmp_path / "test_p"
    persona_root.mkdir()
    
    metadata = {
        "persona": {
            "name": "test_p",
            "schema_version": 3,
        }
    }
    write_metadata(persona_root / METADATA_FILENAME, metadata)
    (persona_root / PROMPT_FILENAME).write_text("prompt")
    write_chunks(persona_root / CHUNKS_FILENAME, [])

    source_file = tmp_path / "source.txt"
    source_file.write_text("Deduplication test content.")
    
    # First ingestion
    result1 = add_manual_sources(persona_root, [str(source_file)])
    assert result1.processed_sources == 1
    
    # Second ingestion with same content
    result2 = add_manual_sources(persona_root, [str(source_file)])
    assert result2.processed_sources == 0
    assert result2.skipped_existing_sources == 1
    assert result2.added_chunks == 0
    
    # Verify catalog hasn't duplicated entries
    catalog = read_catalog(persona_root)
    assert len(catalog["sources"]) == 1
    assert len(catalog["entries"]) == result1.added_chunks


def test_prepare_source_preflight(tmp_path):
    from asky.plugins.manual_persona_creator.source_service import prepare_source_preflight
    from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind
    
    preflight = prepare_source_preflight(tmp_path, "arendt", PersonaSourceKind.BIOGRAPHY, tmp_path / "bio.txt")
    assert preflight["kind"] == PersonaSourceKind.BIOGRAPHY
    assert preflight["initial_status"] == "pending"
    
    preflight_auto = prepare_source_preflight(tmp_path, "arendt", PersonaSourceKind.ARTICLE, tmp_path / "art.txt")
    assert preflight_auto["initial_status"] == "approved"


def test_create_source_ingestion_job(tmp_path):
    from asky.plugins.manual_persona_creator.source_service import create_source_ingestion_job
    from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind
    from asky.plugins.manual_persona_creator.storage import create_persona
    
    data_dir = tmp_path / "data"
    create_persona(data_dir=data_dir, persona_name="arendt", description="test", behavior_prompt="test")
    
    job_id = create_source_ingestion_job(data_dir, "arendt", PersonaSourceKind.BIOGRAPHY, tmp_path / "bio.txt")
    assert job_id.startswith("job_")
    
    persona_root = data_dir / "personas" / "arendt"
    from asky.plugins.manual_persona_creator.storage import get_source_job_paths
    job_paths = get_source_job_paths(persona_root, job_id)
    assert job_paths.manifest_path.exists()

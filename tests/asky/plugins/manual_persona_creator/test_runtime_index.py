"""Tests for persona runtime index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.knowledge_catalog import (
    rebuild_catalog_from_legacy,
)
from asky.plugins.manual_persona_creator.runtime_index import (
    read_runtime_index,
    rebuild_runtime_index,
    runtime_index_path,
)
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    BOOK_METADATA_FILENAME,
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PROMPT_FILENAME,
    VIEWPOINTS_FILENAME,
    write_chunks,
    write_metadata,
)


def test_rebuild_runtime_index_from_v2_legacy(tmp_path: Path):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    # Create v2 legacy artifacts
    metadata = {
        "persona": {
            "name": "test_persona",
            "schema_version": 2,
        }
    }
    write_metadata(persona_root / METADATA_FILENAME, metadata)
    (persona_root / PROMPT_FILENAME).write_text("Test prompt")
    
    chunks = [
        {
            "chunk_id": "c1",
            "text": "Chunk 1 text",
            "source": "manual.txt",
            "chunk_index": 0,
        }
    ]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    # Create authored book
    book_dir = persona_root / AUTHORED_BOOKS_DIR_NAME / "test-book"
    book_dir.mkdir(parents=True)
    
    book_metadata = {
        "book": {
            "title": "Test Book",
            "author": "Test Author",
        }
    }
    from asky.plugins.manual_persona_creator.storage import write_book_metadata
    write_book_metadata(book_dir / BOOK_METADATA_FILENAME, book_metadata)

    viewpoints = [
        {
            "viewpoint_id": "vp1",
            "viewpoint_text": "Viewpoint 1 text",
            "topic": "Topic 1",
            "evidence": [
                {"text": "Evidence 1", "page_ref": "10"}
            ]
        }
    ]
    (book_dir / VIEWPOINTS_FILENAME).write_text(json.dumps(viewpoints))

    # 1. Rebuild catalog first (needed for runtime index)
    rebuild_catalog_from_legacy(persona_root)
    
    # 2. Rebuild runtime index
    result = rebuild_runtime_index(persona_root)
    assert result["rebuilt"] is True
    assert result["indexed_entries"] == 3  # 1 chunk + 1 viewpoint + 1 evidence

    # 3. Verify index content
    index = read_runtime_index(persona_root)
    assert len(index) == 3
    
    entry_ids = {r["entry_id"] for r in index}
    assert "chunk:c1" in entry_ids
    assert "viewpoint:vp1" in entry_ids
    assert "evidence:vp1:0" in entry_ids
    
    vp_record = next(r for r in index if r["entry_id"] == "viewpoint:vp1")
    assert vp_record["entry_kind"] == "viewpoint"
    assert vp_record["source_id"] == "book:test-book"
    assert vp_record["metadata"]["topic"] == "Topic 1"
    assert "vector" in vp_record
    assert len(vp_record["vector"]) > 0


def test_rebuild_runtime_index_no_catalog(tmp_path: Path):
    persona_root = tmp_path / "empty_persona"
    persona_root.mkdir()
    
    result = rebuild_runtime_index(persona_root)
    assert result["rebuilt"] is False
    assert result["reason"] == "catalog_missing"


def test_runtime_index_rebuild_is_deterministic(tmp_path: Path):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    chunks = [{"chunk_id": "c1", "text": "same text", "source": "s.txt"}]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    rebuild_catalog_from_legacy(persona_root)
    
    rebuild_runtime_index(persona_root)
    index1 = read_runtime_index(persona_root)
    
    # Remove and rebuild
    runtime_index_path(persona_root).unlink()
    
    rebuild_runtime_index(persona_root)
    index2 = read_runtime_index(persona_root)
    
    assert index1[0]["vector"] == index2[0]["vector"]
    assert index1[0]["entry_id"] == index2[0]["entry_id"]

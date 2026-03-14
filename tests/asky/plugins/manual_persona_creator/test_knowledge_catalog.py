"""Tests for persona knowledge catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.knowledge_catalog import (
    ENTRIES_FILENAME,
    KNOWLEDGE_DIR_NAME,
    SOURCES_FILENAME,
    read_catalog,
    rebuild_catalog_from_legacy,
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


def test_rebuild_catalog_from_v2_legacy(tmp_path: Path):
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
        },
        {
            "chunk_id": "c2",
            "text": "Chunk 2 text",
            "source": "manual.txt",
            "chunk_index": 1,
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

    # Run rebuild
    rebuild_catalog_from_legacy(persona_root)

    # Verify catalog
    catalog = read_catalog(persona_root)
    assert catalog is not None
    assert len(catalog["sources"]) == 2  # 1 book + 1 manual
    assert len(catalog["entries"]) == 4  # 2 chunks + 1 viewpoint + 1 evidence

    sources = {s.source_id: s for s in catalog["sources"]}
    assert "book:test-book" in sources
    manual_source_id = [sid for sid in sources if sid.startswith("manual:")][0]
    
    entries = {e.entry_id: e for e in catalog["entries"]}
    assert "chunk:c1" in entries
    assert "chunk:c2" in entries
    assert "viewpoint:vp1" in entries
    assert "evidence:vp1:0" in entries

    assert entries["chunk:c1"].source_id == manual_source_id
    assert entries["viewpoint:vp1"].source_id == "book:test-book"
    assert entries["evidence:vp1:0"].parent_entry_id == "viewpoint:vp1"


def test_rebuild_catalog_with_modern_authored_book_and_compat_chunks(tmp_path: Path):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    # Create chunks.json with mixed sources including authored-book compat
    chunks = [
        {
            "chunk_id": "m1",
            "text": "Manual text",
            "source": "manual.txt",
        },
        {
            "chunk_id": "vp-entry1",
            "text": "Topic: T1\nClaim: C1\nStance: supports\nEvidence: E1 [S1]",
            "source": "authored-book://book1",
        }
    ]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    # Create authored book with modern shape
    book_dir = persona_root / AUTHORED_BOOKS_DIR_NAME / "book1"
    book_dir.mkdir(parents=True)
    
    book_metadata = {
        "title": "Modern Book",
        "authors": ["Author One"],
        "publication_year": 2024,
        "isbn": "123-456",
    }
    from asky.plugins.manual_persona_creator.storage import write_book_metadata
    write_book_metadata(book_dir / BOOK_METADATA_FILENAME, book_metadata)

    viewpoints = [
        {
            "entry_id": "entry1",
            "topic": "T1",
            "claim": "C1",
            "stance_label": "supports",
            "confidence": 0.95,
            "book_key": "book1",
            "book_title": "Modern Book",
            "publication_year": 2024,
            "isbn": "123-456",
            "evidence": [
                {"excerpt": "E1", "section_ref": "S1"}
            ]
        }
    ]
    (book_dir / VIEWPOINTS_FILENAME).write_text(json.dumps(viewpoints))

    # Run rebuild
    rebuild_catalog_from_legacy(persona_root)

    # Verify catalog
    catalog = read_catalog(persona_root)
    assert catalog is not None
    
    # 1 book + 1 manual source (compat chunk should NOT create a manual source)
    assert len(catalog["sources"]) == 2
    sources = {s.source_id: s for s in catalog["sources"]}
    assert "book:book1" in sources
    manual_sources = [sid for sid in sources if sid.startswith("manual:")]
    assert len(manual_sources) == 1
    
    # 1 manual chunk + 1 viewpoint + 1 evidence
    # (The compat chunk itself IS projected as a chunk entry currently, 
    # but the instructions say "skip authored-book compatibility chunks 
    # during manual-source grouping so they do not create fake manual:* sources")
    # Actually, the implementation I wrote SKIPS them in the loop that populates chunks_by_source.
    # So they won't even be projected as entries. Let's verify that.
    
    # entries: 1 manual chunk + 1 viewpoint + 1 evidence = 3
    assert len(catalog["entries"]) == 3
    entries = {e.entry_id: e for e in catalog["entries"]}
    assert "chunk:m1" in entries
    assert "chunk:vp-entry1" not in entries  # Correctly skipped
    assert "viewpoint:entry1" in entries
    assert "evidence:entry1:0" in entries
    
    # Verify metadata mapping
    vp = entries["viewpoint:entry1"]
    assert vp.text == "C1"
    assert vp.metadata["topic"] == "T1"
    assert vp.metadata["stance_label"] == "supports"
    assert vp.metadata["publication_year"] == 2024
    
    ev = entries["evidence:entry1:0"]
    assert ev.text == "E1"
    assert ev.metadata["section_ref"] == "S1"


def test_catalog_rebuild_is_deterministic(tmp_path: Path):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    chunks = [{"chunk_id": "c1", "text": "same text", "source": "s.txt"}]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    rebuild_catalog_from_legacy(persona_root)
    catalog1 = read_catalog(persona_root)
    
    # Remove and rebuild
    (persona_root / KNOWLEDGE_DIR_NAME / SOURCES_FILENAME).unlink()
    (persona_root / KNOWLEDGE_DIR_NAME / ENTRIES_FILENAME).unlink()
    
    rebuild_catalog_from_legacy(persona_root)
    catalog2 = read_catalog(persona_root)
    
    assert catalog1["sources"][0].source_id == catalog2["sources"][0].source_id


def test_schema_v3_export_carries_knowledge_catalog(tmp_path: Path):
    from asky.plugins.manual_persona_creator.exporter import export_persona_package
    from zipfile import ZipFile

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    persona_name = "test_p"
    persona_root = data_dir / "personas" / persona_name
    persona_root.mkdir(parents=True)

    metadata = {
        "persona": {
            "name": persona_name,
            "schema_version": 3,
        }
    }
    write_metadata(persona_root / METADATA_FILENAME, metadata)
    (persona_root / PROMPT_FILENAME).write_text("prompt")
    write_chunks(persona_root / CHUNKS_FILENAME, [])

    # Create knowledge catalog
    k_dir = persona_root / KNOWLEDGE_DIR_NAME
    k_dir.mkdir()
    (k_dir / SOURCES_FILENAME).write_text("[]")
    (k_dir / ENTRIES_FILENAME).write_text("[]")

    export_path = export_persona_package(data_dir=data_dir, persona_name=persona_name)
    
    with ZipFile(export_path, "r") as archive:
        members = archive.namelist()
        assert f"{KNOWLEDGE_DIR_NAME}/{SOURCES_FILENAME}" in members
        assert f"{KNOWLEDGE_DIR_NAME}/{ENTRIES_FILENAME}" in members

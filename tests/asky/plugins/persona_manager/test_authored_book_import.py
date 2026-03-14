from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    BOOK_METADATA_FILENAME,
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PROMPT_FILENAME,
    REPORT_FILENAME,
    VIEWPOINTS_FILENAME,
)
from asky.plugins.persona_manager.importer import import_persona_archive


class _FakeEmbeddingClient:
    def embed(self, texts):
        return [[float(i + 1), float(i + 2)] for i, _ in enumerate(texts)]

    def embed_single(self, text):
        _ = text
        return [1.0, 2.0]


def test_import_round_trips_authored_books(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    data_dir = tmp_path / "data"
    archive_path = tmp_path / "persona_v2.zip"
    
    persona_name = "arendt"
    book_key = "the-human-condition-1958"
    
    metadata = {
        "persona": {
            "name": persona_name,
            "description": "Hannah Arendt",
            "schema_version": 2,
        }
    }
    chunks = []
    prompt = "You are Hannah Arendt."
    
    # Files for the archive
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        metadata_toml = (
            "[persona]\n"
            f'name = "{persona_name}"\n'
            f'description = "{metadata["persona"]["description"]}"\n'
            "schema_version = 2\n"
        )
        archive.writestr(METADATA_FILENAME, metadata_toml)
        archive.writestr(PROMPT_FILENAME, prompt)
        
        # Compat chunk for authored book
        chunks = [
            {
                "chunk_id": "vp-v1",
                "text": "Topic: T1\nClaim: C1\nStance: supports\nEvidence: E1 [S1]",
                "source": f"authored-book://{book_key}",
            }
        ]
        archive.writestr(CHUNKS_FILENAME, json.dumps(chunks))
        
        # Authored book files with modern shape
        book_prefix = f"{AUTHORED_BOOKS_DIR_NAME}/{book_key}"
        book_metadata_toml = (
            'title = "The Human Condition"\n'
            'authors = ["Hannah Arendt"]\n'
            'publication_year = 1958\n'
            'isbn = "0-226-02598-5"\n'
        )
        archive.writestr(f"{book_prefix}/{BOOK_METADATA_FILENAME}", book_metadata_toml)
        
        viewpoints = [
            {
                "entry_id": "v1",
                "topic": "T1",
                "claim": "C1",
                "stance_label": "supports",
                "confidence": 1.0,
                "book_key": book_key,
                "book_title": "The Human Condition",
                "publication_year": 1958,
                "isbn": "0-226-02598-5",
                "evidence": [
                    {"excerpt": "E1", "section_ref": "S1"}
                ]
            }
        ]
        archive.writestr(f"{book_prefix}/{VIEWPOINTS_FILENAME}", json.dumps(viewpoints))
        archive.writestr(f"{book_prefix}/{REPORT_FILENAME}", "{}")

    # Import
    result = import_persona_archive(
        data_dir=data_dir,
        archive_path=str(archive_path),
    )
    
    assert result["ok"]
    assert result["name"] == persona_name
    
    # Verify files exist in data_dir
    persona_root = data_dir / "personas" / persona_name
    assert (persona_root / AUTHORED_BOOKS_DIR_NAME / book_key / BOOK_METADATA_FILENAME).exists()
    assert (persona_root / AUTHORED_BOOKS_DIR_NAME / book_key / VIEWPOINTS_FILENAME).exists()
    
    # Verify catalog exists and is correct
    from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
    catalog = read_catalog(persona_root)
    assert catalog is not None
    
    # Should have 1 book source and 0 manual sources (because the only chunk was a compat chunk)
    assert len(catalog["sources"]) == 1
    assert catalog["sources"][0].source_id == f"book:{book_key}"
    
    # Should have 1 viewpoint + 1 evidence = 2 entries
    assert len(catalog["entries"]) == 2
    entries = {e.entry_id: e for e in catalog["entries"]}
    assert "viewpoint:v1" in entries
    assert "evidence:v1:0" in entries
    
    # Verify embeddings were rebuilt
    assert (persona_root / "embeddings.json").exists()


def test_import_v1_archive_still_works(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    data_dir = tmp_path / "data"
    archive_path = tmp_path / "persona_v1.zip"
    
    persona_name = "old_arendt"
    
    # Use schema_version = 1
    metadata = (
        "[persona]\n"
        f'name = "{persona_name}"\n'
        "schema_version = 1\n"
    )
    
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(METADATA_FILENAME, metadata)
        archive.writestr(PROMPT_FILENAME, "prompt")
        archive.writestr(CHUNKS_FILENAME, "[]")

    # Import
    result = import_persona_archive(
        data_dir=data_dir,
        archive_path=str(archive_path),
    )
    
    assert result["ok"]
    assert result["name"] == persona_name
    persona_root = data_dir / "personas" / persona_name
    assert (persona_root / METADATA_FILENAME).exists()

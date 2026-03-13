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
        archive.writestr(CHUNKS_FILENAME, json.dumps(chunks))
        
        # Authored book files
        book_prefix = f"{AUTHORED_BOOKS_DIR_NAME}/{book_key}"
        archive.writestr(f"{book_prefix}/{BOOK_METADATA_FILENAME}", "title = 'The Human Condition'")
        archive.writestr(f"{book_prefix}/{VIEWPOINTS_FILENAME}", "[]")
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
    assert (persona_root / AUTHORED_BOOKS_DIR_NAME / book_key / REPORT_FILENAME).exists()
    
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

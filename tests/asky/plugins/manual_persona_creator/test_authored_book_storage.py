from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import tomlkit

from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    BOOK_METADATA_FILENAME,
    PERSONA_SCHEMA_VERSION,
    REPORT_FILENAME,
    SUPPORTED_SCHEMA_VERSIONS,
    VIEWPOINTS_FILENAME,
    INGESTION_JOBS_DIR_NAME,
    create_persona,
    get_book_key,
    get_book_paths,
    get_persona_paths,
    read_metadata,
    write_metadata,
)


def test_book_key_generation():
    # ISBN priority
    assert get_book_key(title="Title", publication_year=2020, isbn="978-3-16-148410-0") == "isbn-9783161484100"
    
    # Title and year fallback
    assert get_book_key(title="The Great Gatsby", publication_year=1925, isbn=None) == "the-great-gatsby-1925"
    
    # Title only fallback
    assert get_book_key(title="No Year", publication_year=None, isbn=None) == "no-year"
    
    # Normalization
    assert get_book_key(title="  Spaced   Title  ", publication_year=2021, isbn=None) == "spaced-title-2021"


def test_persona_schema_compatibility(tmp_path: Path):
    data_dir = tmp_path / "data"
    paths = create_persona(
        data_dir=data_dir,
        persona_name="compat",
        description="demo",
        behavior_prompt="prompt",
    )
    
    # Verify it's created with latest version
    metadata = read_metadata(paths.metadata_path)
    assert metadata["persona"]["schema_version"] == PERSONA_SCHEMA_VERSION
    assert PERSONA_SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS

    # Force version 1
    metadata["persona"]["schema_version"] = 1
    write_metadata(paths.metadata_path, metadata)
    
    # Verify it still reads
    metadata_v1 = read_metadata(paths.metadata_path)
    assert metadata_v1["persona"]["schema_version"] == 1


def test_export_includes_authored_books_excludes_jobs(tmp_path: Path):
    data_dir = tmp_path / "data"
    persona_name = "book_persona"
    paths = create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="demo",
        behavior_prompt="prompt",
    )
    
    # Create an authored book
    book_key = "test-book-2024"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    book_paths.metadata_path.write_text("title = 'Test Book'", encoding="utf-8")
    book_paths.viewpoints_path.write_text("[]", encoding="utf-8")
    book_paths.report_path.write_text("{}", encoding="utf-8")
    
    # Create a job (should be excluded)
    job_dir = paths.root_dir / INGESTION_JOBS_DIR_NAME / "job-123"
    job_dir.mkdir(parents=True)
    (job_dir / "job.toml").write_text("status = 'running'", encoding="utf-8")
    (job_dir / "scratch.txt").write_text("scratch content", encoding="utf-8")
    
    archive_path = export_persona_package(data_dir=data_dir, persona_name=persona_name)
    
    with ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
        
        # Core files
        assert "metadata.toml" in names
        assert "behavior_prompt.md" in names
        assert "chunks.json" in names
        
        # Authored book files
        assert f"{AUTHORED_BOOKS_DIR_NAME}/{book_key}/{BOOK_METADATA_FILENAME}" in names
        assert f"{AUTHORED_BOOKS_DIR_NAME}/{book_key}/{VIEWPOINTS_FILENAME}" in names
        assert f"{AUTHORED_BOOKS_DIR_NAME}/{book_key}/{REPORT_FILENAME}" in names
        
        # Job files (must be excluded)
        assert not any(name.startswith(INGESTION_JOBS_DIR_NAME) for name in names)
        assert "embeddings.json" not in names

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from asky.plugins.manual_persona_creator.book_service import (
    create_ingestion_job,
    get_authored_book_report,
    get_ingestion_identity_status,
    list_authored_books,
    prepare_ingestion_preflight,
    query_authored_viewpoints,
    update_ingestion_job_inputs,
)
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
    IngestionIdentityStatus,
)
from asky.plugins.manual_persona_creator.storage import create_persona, write_book_metadata


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def persona_name():
    return "test-persona"


@pytest.fixture
def setup_persona(data_dir, persona_name):
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="Test persona",
        behavior_prompt="Test prompt",
    )


def test_get_ingestion_identity_status_available(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="New Book", authors=["Author"])
    status = get_ingestion_identity_status(
        data_dir=data_dir,
        persona_name=persona_name,
        metadata=metadata,
        mode="ingest"
    )
    assert status == IngestionIdentityStatus.AVAILABLE


def test_get_ingestion_identity_status_duplicate(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="Existing Book", authors=["Author"], publication_year=2020)
    
    # Manually create existing book
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, get_book_paths
    paths = get_persona_paths(data_dir, persona_name)
    book_key = "existing-book-2020"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    write_book_metadata(book_paths.metadata_path, {"title": "Existing Book", "authors": ["Author"], "publication_year": 2020})
    
    status = get_ingestion_identity_status(
        data_dir=data_dir,
        persona_name=persona_name,
        metadata=metadata,
        mode="ingest"
    )
    assert status == IngestionIdentityStatus.DUPLICATE_COMPLETED


def test_create_ingestion_job_rejection(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="Existing Book", authors=["Author"], publication_year=2020)
    
    # Manually create existing book
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, get_book_paths
    paths = get_persona_paths(data_dir, persona_name)
    book_key = "existing-book-2020"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    write_book_metadata(book_paths.metadata_path, {"title": "Existing Book", "authors": ["Author"], "publication_year": 2020})
    
    with pytest.raises(ValueError, match="Book already exists"):
        create_ingestion_job(
            data_dir=data_dir,
            persona_name=persona_name,
            source_path="/tmp/test.epub",
            source_fingerprint="abc",
            metadata=metadata,
            targets=ExtractionTargets(8, 24),
            mode="ingest"
        )


def test_create_ingestion_job_reingest_allowed(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="Existing Book", authors=["Author"], publication_year=2020)
    
    # Manually create existing book
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, get_book_paths
    paths = get_persona_paths(data_dir, persona_name)
    book_key = "existing-book-2020"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    write_book_metadata(book_paths.metadata_path, {"title": "Existing Book", "authors": ["Author"], "publication_year": 2020})
    
    job_id = create_ingestion_job(
        data_dir=data_dir,
        persona_name=persona_name,
        source_path="/tmp/test.epub",
        source_fingerprint="abc",
        metadata=metadata,
        targets=ExtractionTargets(8, 24),
        mode="reingest",
        expected_book_key=book_key
    )
    assert job_id is not None


def test_create_ingestion_job_reingest_forbidden(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="Mismatched Book", authors=["Author"], publication_year=2021)
    
    # Manually create existing book
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, get_book_paths
    paths = get_persona_paths(data_dir, persona_name)
    book_key = "existing-book-2020"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    write_book_metadata(book_paths.metadata_path, {"title": "Existing Book", "authors": ["Author"], "publication_year": 2020})
    
    with pytest.raises(ValueError, match="Identity mismatch"):
        create_ingestion_job(
            data_dir=data_dir,
            persona_name=persona_name,
            source_path="/tmp/test.epub",
            source_fingerprint="abc",
            metadata=metadata,
            targets=ExtractionTargets(8, 24),
            mode="reingest",
            expected_book_key=book_key
        )


def test_update_ingestion_job_inputs_persists_edits(data_dir, persona_name, setup_persona):
    metadata = BookMetadata(title="Draft Book", authors=["Author"], publication_year=2020)
    job_id = create_ingestion_job(
        data_dir=data_dir,
        persona_name=persona_name,
        source_path="/tmp/test.epub",
        source_fingerprint="abc",
        metadata=metadata,
        targets=ExtractionTargets(8, 24),
        mode="ingest",
    )

    updated_metadata = BookMetadata(title="Edited Book", authors=["Author Two"], publication_year=2021)
    updated_targets = ExtractionTargets(10, 30)
    update_ingestion_job_inputs(
        data_dir=data_dir,
        persona_name=persona_name,
        job_id=job_id,
        metadata=updated_metadata,
        targets=updated_targets,
        mode="ingest",
    )

    from asky.plugins.manual_persona_creator.storage import get_job_paths, get_persona_paths, read_job_manifest

    paths = get_persona_paths(data_dir, persona_name)
    manifest = read_job_manifest(get_job_paths(paths.root_dir, job_id).manifest_path)
    assert manifest["metadata"]["title"] == "Edited Book"
    assert manifest["metadata"]["authors"] == ["Author Two"]
    assert manifest["targets"]["topic_target"] == 10
    assert manifest["targets"]["viewpoint_target"] == 30

import pytest
from pathlib import Path
from asky.plugins.manual_persona_creator.creation_service import (
    PersonaCreationSpecs,
    StagedSourceSpec,
    create_persona_from_scratch
)
from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind
from asky.plugins.manual_persona_creator.book_types import BookMetadata, ExtractionTargets
from asky.plugins.manual_persona_creator import storage

@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d

def test_create_persona_with_manual_source(data_dir):
    source_file = data_dir / "interview.txt"
    source_file.write_text("An interview with somebody.")
    
    specs = PersonaCreationSpecs(
        name="test-persona",
        description="A test persona",
        behavior_prompt="Act like a tester.",
        initial_sources=[
            StagedSourceSpec(
                kind=PersonaSourceKind.INTERVIEW,
                path=str(source_file)
            )
        ]
    )
    
    name, jobs = create_persona_from_scratch(data_dir, specs)
    assert name == "test-persona"
    assert len(jobs) == 1
    assert storage.persona_exists(data_dir, name)
    
    # Check if manual source job was created
    paths = storage.get_persona_paths(data_dir, name)
    job_ids = storage.list_source_jobs(paths.root_dir)
    assert len(job_ids) == 1

def test_rollback_after_shell_creation(data_dir, monkeypatch):
    source_file = data_dir / "article.txt"
    source_file.write_text("Some text.")
    
    specs = PersonaCreationSpecs(
        name="failing-persona",
        description="Should be rolled back",
        behavior_prompt="Prompt",
        initial_sources=[
            StagedSourceSpec(
                kind=PersonaSourceKind.ARTICLE,
                path=str(source_file)
            )
        ]
    )
    
    from asky.plugins.manual_persona_creator import source_service
    def mock_create_job(*args, **kwargs):
        raise RuntimeError("Injected failure")
        
    monkeypatch.setattr(source_service, "create_source_ingestion_job", mock_create_job)
    
    with pytest.raises(RuntimeError, match="Injected failure"):
        create_persona_from_scratch(data_dir, specs)
        
    # Check that directory was removed
    paths = storage.get_persona_paths(data_dir, "failing-persona")
    assert not paths.root_dir.exists()

def test_validation_errors(data_dir):
    # Empty prompt
    specs = PersonaCreationSpecs(
        name="invalid",
        description="",
        behavior_prompt="",
        initial_sources=[StagedSourceSpec(kind="article", path="p")]
    )
    with pytest.raises(ValueError, match="Behavior prompt cannot be empty"):
        create_persona_from_scratch(data_dir, specs)

    # No sources
    specs = PersonaCreationSpecs(
        name="invalid",
        description="",
        behavior_prompt="Prompt",
        initial_sources=[]
    )
    with pytest.raises(ValueError, match="At least one initial source"):
        create_persona_from_scratch(data_dir, specs)

def test_resumable_authored_book_returns_real_job_id(data_dir, monkeypatch):
    """Verify resumable authored-book finalization returns the existing job ID, not None."""
    from asky.plugins.manual_persona_creator import book_service
    from unittest.mock import MagicMock

    book_file = data_dir / "book.txt"
    book_file.write_text("Chapter 1: Introduction\n\nSome text here.")

    # Mock the book service functions to avoid complex document setup
    mock_preflight = MagicMock()
    mock_preflight.source_fingerprint = "mock-fingerprint"
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.book_service.prepare_ingestion_preflight",
        MagicMock(return_value=mock_preflight)
    )

    # Mock update_ingestion_job_inputs to return None (as per current impl)
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.book_service.update_ingestion_job_inputs",
        MagicMock(return_value=None)
    )

    # Mock create_ingestion_job
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.book_service.create_ingestion_job",
        MagicMock(return_value="new-job-123")
    )

    # Mock source service
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_service.create_source_ingestion_job",
        MagicMock(return_value="source-job-456")
    )

    # Test: create persona with resumable job
    resumable_job_id = "existing-resumable-job-789"
    specs = PersonaCreationSpecs(
        name="test-persona-resumable",
        description="Test with resumable book",
        behavior_prompt="Test behavior",
        initial_sources=[
            StagedSourceSpec(
                kind="authored_book",
                path=str(book_file),
                metadata=BookMetadata(title="Test Book", authors=["Author"], publication_year=2024, isbn="123"),
                targets=ExtractionTargets(topic_target=10, viewpoint_target=5),
                resumable_job_id=resumable_job_id
            )
        ]
    )

    name, jobs = create_persona_from_scratch(data_dir, specs)

    # Verify that the returned job ID is the resumable job ID, not None
    assert len(jobs) == 1
    assert jobs[0].job_id == resumable_job_id, f"Expected {resumable_job_id}, got {jobs[0].job_id}"
    assert jobs[0].job_id is not None

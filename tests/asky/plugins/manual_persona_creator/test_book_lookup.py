import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from asky.plugins.manual_persona_creator.book_lookup import run_preflight
from asky.plugins.manual_persona_creator.book_types import MetadataCandidate
from asky.plugins.manual_persona_creator.storage import create_persona, write_job_manifest


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


@patch("asky.plugins.manual_persona_creator.book_lookup.fetch_source_via_adapter")
@patch("asky.plugins.manual_persona_creator.book_lookup.lookup_open_library_metadata")
def test_run_preflight_resumable(mock_lookup, mock_fetch, data_dir, persona_name, setup_persona, tmp_path):
    # Setup source file
    source_file = tmp_path / "book.txt"
    source_file.write_text("Some content")
    
    mock_fetch.return_value = {"content": "Some content"}
    mock_lookup.return_value = [
        MetadataCandidate(
            metadata=MagicMock(title="Test Book", authors=["Author"], publication_year=2020, isbn=None),
            confidence=1.0
        )
    ]
    
    # Create a resumable job
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, get_job_paths
    paths = get_persona_paths(data_dir, persona_name)
    job_id = "resumable-job-id"
    job_paths = get_job_paths(paths.root_dir, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    from asky.plugins.manual_persona_creator.book_lookup import get_source_fingerprint
    fingerprint = get_source_fingerprint("Some content")
    
    manifest_data = {
        "job_id": job_id,
        "persona_name": persona_name,
        "source_path": str(source_file),
        "source_fingerprint": fingerprint,
        "status": "planned",
        "mode": "ingest",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2023-01-01T00:00:00Z",
        "metadata": {"title": "Test Book", "authors": ["Author"], "publication_year": 2020, "isbn": None},
        "targets": {"topic_target": 8, "viewpoint_target": 24},
        "stages_completed": [],
    }
    write_job_manifest(job_paths.manifest_path, manifest_data)
    
    result = run_preflight(
        persona_name=persona_name,
        source_path=str(source_file),
        data_dir=data_dir
    )
    
    assert result.resumable_job_id == job_id
    assert result.resumable_manifest is not None
    assert result.resumable_manifest.job_id == job_id
    assert isinstance(result.candidates[0], MetadataCandidate)

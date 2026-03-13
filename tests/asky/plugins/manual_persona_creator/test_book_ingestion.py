import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from asky.plugins.manual_persona_creator.book_ingestion import (
    BookIngestionJob,
    _validate_topics_payload,
    _validate_viewpoint_payload,
)
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
    IngestionJobManifest,
    ViewpointEntry,
    ViewpointEvidence,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_job_paths,
    get_persona_paths,
    write_job_manifest,
)


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


def test_book_ingestion_job_identity_guard(data_dir, persona_name, setup_persona):
    # Setup job
    paths = get_persona_paths(data_dir, persona_name)
    job_id = "test-job"
    job_paths = get_job_paths(paths.root_dir, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    metadata = {"title": "Existing Book", "authors": ["Author"], "publication_year": 2020, "isbn": None}
    manifest_data = {
        "job_id": job_id,
        "persona_name": persona_name,
        "source_path": "/tmp/book.txt",
        "source_fingerprint": "abc",
        "status": "planned",
        "mode": "ingest",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2023-01-01T00:00:00Z",
        "metadata": metadata,
        "targets": {"topic_target": 8, "viewpoint_target": 24},
        "stages_completed": [],
    }
    write_job_manifest(job_paths.manifest_path, manifest_data)
    
    # Create existing book
    from asky.plugins.manual_persona_creator.storage import get_book_paths, write_book_metadata
    book_key = "existing-book-2020"
    book_paths = get_book_paths(paths.root_dir, book_key)
    book_paths.book_dir.mkdir(parents=True)
    write_book_metadata(book_paths.metadata_path, metadata)
    
    job = BookIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    
    with pytest.raises(ValueError, match="Book already exists"):
        job.run()


def test_validate_topics_payload():
    assert _validate_topics_payload(["Topic A", "Topic B"]) == ["Topic A", "Topic B"]
    assert _validate_topics_payload(["  Topic A  ", ""]) == ["Topic A"]
    with pytest.raises(ValueError, match="Expected a list"):
        _validate_topics_payload("not a list")
    with pytest.raises(ValueError, match="No valid topics found"):
        _validate_topics_payload([])
    with pytest.raises(ValueError, match="No valid topics found"):
        _validate_topics_payload(["", "  "])


def test_validate_viewpoint_payload():
    valid = {
        "claim": "The sky is blue.",
        "stance_label": "supports",
        "confidence": 0.9,
        "evidence": [{"excerpt": "Look up", "section_ref": "1.1"}],
    }
    result = _validate_viewpoint_payload(valid, "Color of sky")
    assert result["claim"] == "The sky is blue."
    assert result["stance_label"] == "supports"
    assert result["confidence"] == 0.9
    assert len(result["evidence"]) == 1

    with pytest.raises(ValueError, match="Missing or invalid 'claim'"):
        _validate_viewpoint_payload({**valid, "claim": ""}, "topic")
    with pytest.raises(ValueError, match="Invalid 'stance_label'"):
        _validate_viewpoint_payload({**valid, "stance_label": "awesome"}, "topic")
    with pytest.raises(ValueError, match="Confidence out of range"):
        _validate_viewpoint_payload({**valid, "confidence": 1.5}, "topic")
    with pytest.raises(ValueError, match="No valid evidence items found"):
        _validate_viewpoint_payload({**valid, "evidence": []}, "topic")


@patch("asky.plugins.manual_persona_creator.book_ingestion.get_llm_msg")
def test_stage_discover_topics_strict_json(mock_llm, data_dir, persona_name, setup_persona):
    job = BookIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id="test-job")
    job.manifest = IngestionJobManifest(
        job_id="test-job",
        persona_name=persona_name,
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        status="running",
        mode="ingest",
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z",
        metadata=BookMetadata(title="Title", authors=["Author"]),
        targets=ExtractionTargets(topic_target=2, viewpoint_target=5),
    )
    job.job_paths.job_dir.mkdir(parents=True, exist_ok=True)

    # Mock non-JSON response
    mock_llm.return_value = {"content": "Here are topics: Topic 1, Topic 2"}
    with pytest.raises(ValueError, match="No JSON array found"):
        job._stage_discover_topics([])
    assert len(job.manifest.warnings) == 1
    assert "Topic discovery failed" in job.manifest.warnings[0]


@patch("asky.plugins.manual_persona_creator.book_ingestion.get_llm_msg")
@patch("asky.plugins.manual_persona_creator.book_ingestion.get_embedding_client")
def test_stage_extract_viewpoints_warning_accumulation(
    mock_embed, mock_llm, data_dir, persona_name, setup_persona
):
    job = BookIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id="test-job")
    job.manifest = IngestionJobManifest(
        job_id="test-job",
        persona_name=persona_name,
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        status="running",
        mode="ingest",
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z",
        metadata=BookMetadata(title="Title", authors=["Author"]),
        targets=ExtractionTargets(topic_target=2, viewpoint_target=5),
    )
    job.job_paths.job_dir.mkdir(parents=True, exist_ok=True)

    mock_client = MagicMock()
    mock_client.embed.return_value = [[0.1] * 1536]
    mock_client.embed_single.return_value = [0.1] * 1536
    mock_embed.return_value = mock_client

    # 1st topic: valid JSON
    # 2nd topic: invalid stance
    mock_llm.side_effect = [
        {
            "content": '{"claim": "Valid", "stance_label": "supports", "confidence": 1.0, "evidence": [{"excerpt": "x", "section_ref": "s"}]}'
        },
        {"content": '{"claim": "Invalid", "stance_label": "bad_stance", "confidence": 1.0}'},
    ]

    viewpoints = job._stage_extract_viewpoints(
        "content", [{"id": "1", "summary": "s", "start_char": 0, "end_char": 7}], ["Topic 1", "Topic 2"]
    )

    assert len(viewpoints) == 1
    assert viewpoints[0].claim == "Valid"
    assert len(job.manifest.warnings) == 1
    assert "Invalid 'stance_label': bad_stance" in job.manifest.warnings[0]


def test_report_persistence_details(data_dir, persona_name, setup_persona):
    job = BookIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id="test-job")
    job.manifest = IngestionJobManifest(
        job_id="test-job",
        persona_name=persona_name,
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        status="running",
        mode="ingest",
        created_at="2023-01-01T00:00:00Z",
        updated_at="2023-01-01T00:00:00Z",
        metadata=BookMetadata(title="Report Title", authors=["Author"]),
        targets=ExtractionTargets(topic_target=5, viewpoint_target=10),
        stage_timings={"read_source": 1.5, "summarize": 10.0},
        warnings=["Warning A"],
    )
    job.job_paths.job_dir.mkdir(parents=True, exist_ok=True)

    viewpoints = [
        ViewpointEntry(
            entry_id="1",
            topic="Topic",
            claim="Claim",
            stance_label="supports",
            confidence=1.0,
            book_key="report-title",
            book_title="Report Title",
            publication_year=None,
            isbn=None,
            evidence=[ViewpointEvidence(excerpt="e", section_ref="r")],
        )
    ]

    report = job._stage_materialize_book(viewpoints)
    
    # Verify report fields
    assert report.warnings == ["Warning A"]
    assert report.stage_timings["read_source"] == 1.5
    assert report.actual_topics == 1
    assert report.actual_viewpoints == 1

    # Verify report.json on disk
    report_path = (
        data_dir / "personas" / "test-persona" / "authored_books" / "report-title" / "report.json"
    )
    assert report_path.exists()
    saved_report = json.loads(report_path.read_text())
    assert saved_report["warnings"] == ["Warning A"]
    assert saved_report["stage_timings"]["summarize"] == 10.0
    assert saved_report["metadata"]["title"] == "Report Title"

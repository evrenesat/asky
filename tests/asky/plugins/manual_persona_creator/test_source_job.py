"""Tests for milestone-3 source ingestion job."""

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.source_job import SourceIngestionJob
from asky.plugins.manual_persona_creator.source_types import (
    PersonaReviewStatus,
    PersonaSourceIngestionJobManifest,
    PersonaSourceKind,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_source_job_paths,
    write_job_manifest,
)


def test_source_job_lifecycle(tmp_path, monkeypatch):
    """Verify source ingestion job lifecycle and kind-aware defaults."""
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / persona_name
    job_id = "job1"
    job_paths = get_source_job_paths(persona_root, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    source_file = tmp_path / "source.txt"
    source_file.write_text("Arendt was born in 1906.", encoding="utf-8")
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=PersonaSourceKind.BIOGRAPHY,
        source_path=str(source_file),
        status="created",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        metadata={
            "source_class": "biography_or_autobiography",
            "trust_class": "third_party_secondary",
        },
    )
    write_job_manifest(job_paths.manifest_path, manifest.__dict__)
    
    # Mock LLM and adapters
    mock_response = {
        "viewpoints": [{"claim": "Freedom is action", "topic": "politics", "confidence": 0.9}],
        "facts": [{"text": "Born in 1906", "topic": "birth", "attribution": "biographer"}],
        "timeline": [{"text": "Birth", "year": 1906}],
        "conflicts": []
    }
    
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_job.fetch_source_via_adapter",
        lambda *a, **k: {"content": "Arendt was born in 1906."}
    )
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_job.SourceIngestionJob._call_llm",
        lambda *a, **k: json.dumps(mock_response)
    )
    # Mock auto-approve projection
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_service.approve_source_bundle",
        lambda *a, **k: None
    )

    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    report = job.run()
    
    assert report.status == "success"
    assert report.extracted_counts["viewpoints"] == 1
    assert report.extracted_counts["facts"] == 1
    assert report.extracted_counts["timeline"] == 1
    
    # Verify review status for BIOGRAPHY is PENDING
    source_id = report.source_id
    from asky.plugins.manual_persona_creator.storage import (
        get_source_bundle_paths,
        read_source_metadata,
    )
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    metadata = read_source_metadata(bundle_paths.metadata_path)
    assert metadata["review_status"] == PersonaReviewStatus.PENDING


def test_source_job_auto_approve(tmp_path, monkeypatch):
    """Verify auto-approval for authored short-form sources."""
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / persona_name
    job_id = "job2"
    job_paths = get_source_job_paths(persona_root, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    source_file = tmp_path / "article.txt"
    source_file.write_text("I believe in action.", encoding="utf-8")
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=PersonaSourceKind.ARTICLE,
        source_path=str(source_file),
        status="created",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        metadata={
            "source_class": "manual_source",
            "trust_class": "authored_primary",
        },
    )
    write_job_manifest(job_paths.manifest_path, manifest.__dict__)
    
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_job.fetch_source_via_adapter",
        lambda *a, **k: {"content": "I believe in action."}
    )
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_job.SourceIngestionJob._call_llm",
        lambda *a, **k: json.dumps({"viewpoints": [{"claim": "Believe in action", "topic": "politics", "confidence": 1.0}]})
    )
    
    # Track projection calls
    projection_called = False
    def mock_approve(*a, **k):
        nonlocal projection_called
        projection_called = True
    
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_service.approve_source_bundle",
        mock_approve
    )

    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    job.run()
    
    assert projection_called is True

"""Tests for milestone-3 source storage contract."""

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.knowledge_catalog import (
    CONFLICTS_FILENAME,
    KNOWLEDGE_DIR_NAME,
    get_knowledge_paths,
)
from asky.plugins.manual_persona_creator.source_types import (
    PersonaReviewStatus,
    PersonaSourceKind,
)
from asky.plugins.manual_persona_creator.storage import (
    INGESTED_SOURCES_DIR_NAME,
    SOURCE_INGESTION_JOBS_DIR_NAME,
    create_persona,
    get_source_bundle_paths,
    get_source_id,
    get_source_job_paths,
    list_source_bundles,
    list_source_jobs,
)
from asky.plugins.persona_manager.importer import import_persona_archive


def test_deterministic_source_id():
    """Verify source-id generation is deterministic and kind-aware."""
    kind = PersonaSourceKind.BIOGRAPHY
    text = "some bundle text"
    source_id = get_source_id(kind, text)
    
    assert source_id.startswith(f"source:{kind}:")
    assert len(source_id.split(":")[-1]) == 16
    
    # Same input -> same ID
    assert get_source_id(kind, text) == source_id
    
    # Different kind -> different ID
    assert get_source_id(PersonaSourceKind.AUTOBIOGRAPHY, text) != source_id
    
    # Different text -> different ID
    assert get_source_id(kind, "other text") != source_id


def test_source_bundle_paths(tmp_path):
    """Verify source bundle filesystem layout."""
    persona_root = tmp_path / "arendt"
    source_id = "source:biography:abc123def4567890"
    paths = get_source_bundle_paths(persona_root, source_id)
    
    assert paths.source_dir == persona_root / INGESTED_SOURCES_DIR_NAME / source_id
    assert paths.metadata_path == paths.source_dir / "source.toml"
    assert paths.report_path == paths.source_dir / "report.json"
    assert paths.viewpoints_path == paths.source_dir / "viewpoints.json"
    assert paths.facts_path == paths.source_dir / "facts.json"
    assert paths.timeline_path == paths.source_dir / "timeline.json"
    assert paths.conflicts_path == paths.source_dir / "conflicts.json"


def test_source_job_paths(tmp_path):
    """Verify source ingestion job filesystem layout."""
    persona_root = tmp_path / "arendt"
    job_id = "job_123"
    paths = get_source_job_paths(persona_root, job_id)
    
    assert paths.job_dir == persona_root / SOURCE_INGESTION_JOBS_DIR_NAME / job_id
    assert paths.manifest_path == paths.job_dir / "job.toml"


def test_list_sources_and_jobs(tmp_path):
    """Verify listing of sources and jobs."""
    persona_root = tmp_path / "arendt"
    
    # Initially empty
    assert list_source_bundles(persona_root) == []
    assert list_source_jobs(persona_root) == []
    
    # Create some directories
    (persona_root / INGESTED_SOURCES_DIR_NAME / "src1").mkdir(parents=True)
    (persona_root / INGESTED_SOURCES_DIR_NAME / "src2").mkdir(parents=True)
    (persona_root / SOURCE_INGESTION_JOBS_DIR_NAME / "job1").mkdir(parents=True)
    
    assert list_source_bundles(persona_root) == ["src1", "src2"]
    assert list_source_jobs(persona_root) == ["job1"]


def test_source_bundle_round_trip(tmp_path, monkeypatch):
    """Verify source bundles and conflict groups survive export/import."""
    data_dir = tmp_path / "data"
    create_persona(
        data_dir=data_dir,
        persona_name="arendt",
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / "arendt"
    source_id = "source:biography:abc123def4567890"
    paths = get_source_bundle_paths(persona_root, source_id)
    paths.source_dir.mkdir(parents=True)
    paths.metadata_path.write_text("kind = 'biography'", encoding="utf-8")
    paths.report_path.write_text("{}", encoding="utf-8")
    
    # Add global conflict groups
    k_paths = get_knowledge_paths(persona_root)
    k_paths["dir"].mkdir(parents=True)
    k_paths["conflicts"].write_text("[]", encoding="utf-8")
    
    # Add a job that should be excluded
    job_paths = get_source_job_paths(persona_root, "job1")
    job_paths.job_dir.mkdir(parents=True)
    job_paths.manifest_path.write_text("status = 'running'", encoding="utf-8")
    
    # Export
    export_path = data_dir / "arendt.zip"
    export_persona_package(data_dir=data_dir, persona_name="arendt", output_path=str(export_path))
    
    # Import into new data dir
    new_data_dir = tmp_path / "new_data"
    
    # Mock embeddings rebuild to avoid real LLM calls
    monkeypatch.setattr("asky.plugins.persona_manager.knowledge.rebuild_embeddings", lambda **k: {})
    # Mock runtime index rebuild
    monkeypatch.setattr("asky.plugins.manual_persona_creator.runtime_index.rebuild_runtime_index", lambda **k: None)

    import_persona_archive(data_dir=new_data_dir, archive_path=str(export_path))
    
    new_persona_root = new_data_dir / "personas" / "arendt"
    new_paths = get_source_bundle_paths(new_persona_root, source_id)
    
    assert new_paths.metadata_path.exists()
    assert new_paths.report_path.exists()
    assert (new_persona_root / KNOWLEDGE_DIR_NAME / CONFLICTS_FILENAME).exists()
    
    # Verify job exclusion
    assert not (new_persona_root / SOURCE_INGESTION_JOBS_DIR_NAME).exists()

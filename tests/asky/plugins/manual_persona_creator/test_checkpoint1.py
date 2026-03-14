"""Tests for Checkpoint 1: Bundle input and TOML metadata."""

import json
from pathlib import Path
import pytest
import tomllib
from asky.plugins.manual_persona_creator.source_job import SourceIngestionJob
from asky.plugins.manual_persona_creator.source_types import (
    PersonaSourceIngestionJobManifest,
    PersonaSourceKind,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_source_job_paths,
    write_job_manifest,
    get_source_bundle_paths,
)

def test_directory_bundle_success(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    persona_name = "test_dir"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    
    source_dir = tmp_path / "notes"
    source_dir.mkdir()
    (source_dir / "note1.txt").write_text("Note 1 content", encoding="utf-8")
    (source_dir / "note2.txt").write_text("Note 2 content", encoding="utf-8")
    
    persona_root = data_dir / "personas" / persona_name
    job_id = "job_dir"
    job_paths = get_source_job_paths(persona_root, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=PersonaSourceKind.NOTES,
        source_path=str(source_dir),
        status="created",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        metadata={"source_class": "manual_source", "trust_class": "authored_primary"},
    )
    write_job_manifest(job_paths.manifest_path, manifest.__dict__)
    
    # Mock LLM and adapters
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_job.fetch_source_via_adapter", 
                        lambda target, operation: {"content": target.split("/")[-1] + " content"})
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_job.SourceIngestionJob._call_llm", 
                        lambda *a, **k: json.dumps({"viewpoints": [], "facts": [], "timeline": [], "conflicts": []}))
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_service.approve_source_bundle", lambda *a, **k: None)

    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    report = job.run()
    
    assert report.status == "success"
    bundle_paths = get_source_bundle_paths(persona_root, report.source_id)
    
    # Verify TOML serialization
    with bundle_paths.metadata_path.open("rb") as f:
        metadata = tomllib.load(f)
    assert metadata["kind"] == "notes"
    assert metadata["source_id"] == report.source_id

def test_manifest_bundle_success(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    persona_name = "test_manifest"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    
    (tmp_path / "f1.txt").write_text("F1", encoding="utf-8")
    (tmp_path / "f2.txt").write_text("F2", encoding="utf-8")
    manifest_file = tmp_path / "my_manifest.txt"
    manifest_file.write_text("f1.txt\n# comment\n  \n f2.txt ", encoding="utf-8")
    
    persona_root = data_dir / "personas" / persona_name
    job_id = "job_manifest"
    job_paths = get_source_job_paths(persona_root, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=PersonaSourceKind.POSTS,
        source_path=str(manifest_file),
        status="created",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        metadata={"source_class": "manual_source", "trust_class": "authored_primary"},
    )
    write_job_manifest(job_paths.manifest_path, manifest.__dict__)
    
    # Mock LLM and adapters
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_job.fetch_source_via_adapter", 
                        lambda target, operation: {"content": target.split("/")[-1]})
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_job.SourceIngestionJob._call_llm", 
                        lambda *a, **k: json.dumps({"viewpoints": [], "facts": [], "timeline": [], "conflicts": []}))
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_service.approve_source_bundle", lambda *a, **k: None)

    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    report = job.run()
    
    assert report.status == "success"

def test_manifest_missing_member_failure(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    persona_name = "test_fail"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    
    manifest_file = tmp_path / "bad_manifest.txt"
    manifest_file.write_text("/non/existent/file.txt", encoding="utf-8")
    
    persona_root = data_dir / "personas" / persona_name
    job_id = "job_fail"
    job_paths = get_source_job_paths(persona_root, job_id)
    job_paths.job_dir.mkdir(parents=True)
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=PersonaSourceKind.NOTES,
        source_path=str(manifest_file),
        status="created",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        metadata={"source_class": "manual_source", "trust_class": "authored_primary"},
    )
    write_job_manifest(job_paths.manifest_path, manifest.__dict__)
    
    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    with pytest.raises(ValueError, match="Manifest bundle error"):
        job.run()

def test_legacy_json_metadata_reading(tmp_path):
    # This tests the tolerant reader in storage.py
    from asky.plugins.manual_persona_creator.storage import read_source_metadata
    metadata_path = tmp_path / "source.toml"
    legacy_data = {"source_id": "legacy1", "kind": "notes"}
    metadata_path.write_text(json.dumps(legacy_data), encoding="utf-8")
    
    read_data = read_source_metadata(metadata_path)
    assert read_data["source_id"] == "legacy1"
    assert read_data["kind"] == "notes"

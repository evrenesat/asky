"""Tests for milestone-3 source review and projection."""

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.knowledge_catalog import (
    KNOWLEDGE_DIR_NAME,
    read_catalog,
)
from asky.plugins.manual_persona_creator.knowledge_types import PersonaEntryKind
from asky.plugins.manual_persona_creator.source_service import (
    approve_source_bundle,
    reject_source_bundle,
)
from asky.plugins.manual_persona_creator.source_types import (
    PersonaReviewStatus,
    PersonaSourceKind,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_source_bundle_paths,
    read_source_metadata,
    write_source_metadata,
)


def test_approve_source_bundle_projection(tmp_path, monkeypatch):
    """Verify that approving a source projects knowledge into canonical artifacts."""
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / persona_name
    source_id = "source:biography:abc123def4567890"
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    bundle_paths.source_dir.mkdir(parents=True)
    
    # Setup bundle data
    metadata = {
        "source_id": source_id,
        "kind": PersonaSourceKind.BIOGRAPHY,
        "label": "Arendt Bio",
        "review_status": PersonaReviewStatus.PENDING,
        "source_class": "biography_or_autobiography",
        "trust_class": "third_party_secondary",
    }
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    viewpoints = [{"claim": "Freedom is action", "topic": "politics", "confidence": 0.9}]
    bundle_paths.viewpoints_path.write_text(json.dumps(viewpoints), encoding="utf-8")
    
    facts = [{"text": "Born in 1906", "topic": "birth", "attribution": "biographer"}]
    bundle_paths.facts_path.write_text(json.dumps(facts), encoding="utf-8")
    
    timeline = [{"text": "Birth", "year": 1906}]
    bundle_paths.timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
    
    conflicts = [{"topic": "birth_year", "description": "Contradicts primary source"}]
    bundle_paths.conflicts_path.write_text(json.dumps(conflicts), encoding="utf-8")

    # Mock rebuilds
    monkeypatch.setattr("asky.plugins.manual_persona_creator.source_service.rebuild_runtime_index", lambda **k: None)
    monkeypatch.setattr("asky.plugins.persona_manager.knowledge.rebuild_embeddings", lambda **k: {})

    approve_source_bundle(data_dir, persona_name, source_id)
    
    # Verify metadata update
    updated_metadata = read_source_metadata(bundle_paths.metadata_path)
    assert updated_metadata["review_status"] == PersonaReviewStatus.APPROVED
    
    # Verify catalog projection
    catalog = read_catalog(persona_root)
    assert any(s.source_id == source_id for s in catalog["sources"])
    
    entries = catalog["entries"]
    assert any(e.entry_kind == PersonaEntryKind.VIEWPOINT and e.text == "Freedom is action" for e in entries)
    assert any(e.entry_kind == PersonaEntryKind.PERSONA_FACT and e.text == "Born in 1906" for e in entries)
    assert any(e.entry_kind == PersonaEntryKind.TIMELINE_EVENT and e.text == "Birth" for e in entries)
    
    # Verify conflict group projection
    from asky.plugins.manual_persona_creator.knowledge_catalog import get_knowledge_paths
    k_paths = get_knowledge_paths(persona_root)
    projected_conflicts = json.loads(k_paths["conflicts"].read_text(encoding="utf-8"))
    assert len(projected_conflicts) == 1
    assert projected_conflicts[0]["topic"] == "birth_year"


def test_reject_source_bundle(tmp_path):
    """Verify that rejecting a source updates status but does not project."""
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / persona_name
    source_id = "source:biography:abc123def4567890"
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    bundle_paths.source_dir.mkdir(parents=True)
    
    metadata = {
        "source_id": source_id,
        "kind": PersonaSourceKind.BIOGRAPHY,
        "label": "Arendt Bio",
        "review_status": PersonaReviewStatus.PENDING,
        "source_class": "biography_or_autobiography",
        "trust_class": "third_party_secondary",
    }
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    reject_source_bundle(data_dir, persona_name, source_id)
    
    updated_metadata = read_source_metadata(bundle_paths.metadata_path)
    assert updated_metadata["review_status"] == PersonaReviewStatus.REJECTED
    
    # Verify catalog NOT updated
    catalog = read_catalog(persona_root)
    if catalog:
        assert not any(s.source_id == source_id for s in catalog["sources"])

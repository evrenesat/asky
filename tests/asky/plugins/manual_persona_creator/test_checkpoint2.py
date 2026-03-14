"""Tests for Checkpoint 2: Idempotent approval and topic filtering."""

import json
from pathlib import Path
import pytest
from asky.plugins.manual_persona_creator.source_service import (
    approve_source_bundle,
    query_approved_facts,
    query_approved_viewpoints,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_source_bundle_paths,
    write_source_metadata,
)
from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog

def test_approval_idempotence(tmp_path):
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    persona_root = data_dir / "personas" / persona_name
    
    source_id = "source:test:123"
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    bundle_paths.source_dir.mkdir(parents=True)
    
    metadata = {
        "source_id": source_id,
        "kind": "notes",
        "label": "test.txt",
        "review_status": "pending",
        "source_class": "manual_source",
        "trust_class": "authored_primary",
    }
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    facts = [{"text": "Fact 1", "topic": "politics"}]
    bundle_paths.facts_path.write_text(json.dumps(facts), encoding="utf-8")
    
    # First approval
    approve_source_bundle(data_dir, persona_name, source_id)
    
    catalog = read_catalog(persona_root)
    assert len([s for s in catalog["sources"] if s.source_id == source_id]) == 1
    assert len([e for e in catalog["entries"] if e.source_id == source_id]) == 1
    
    # Second approval (should replace, not append)
    approve_source_bundle(data_dir, persona_name, source_id)
    
    catalog = read_catalog(persona_root)
    assert len([s for s in catalog["sources"] if s.source_id == source_id]) == 1
    assert len([e for e in catalog["entries"] if e.source_id == source_id]) == 1

def test_reprojection_refreshes_entries(tmp_path):
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    persona_root = data_dir / "personas" / persona_name
    
    source_id = "source:test:789"
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    bundle_paths.source_dir.mkdir(parents=True)
    
    write_source_metadata(bundle_paths.metadata_path, {
        "source_id": source_id, "kind": "notes", "label": "t.txt", 
        "review_status": "pending", "source_class": "manual_source", "trust_class": "authored_primary"
    })
    
    bundle_paths.facts_path.write_text(json.dumps([{"text": "Initial Fact"}]), encoding="utf-8")
    approve_source_bundle(data_dir, persona_name, source_id)
    
    facts = query_approved_facts(data_dir, persona_name, source_id=source_id)
    assert len(facts) == 1
    assert facts[0].text == "Initial Fact"
    
    # Change artifacts and re-approve
    bundle_paths.facts_path.write_text(json.dumps([{"text": "Updated Fact"}]), encoding="utf-8")
    approve_source_bundle(data_dir, persona_name, source_id)
    
    facts = query_approved_facts(data_dir, persona_name, source_id=source_id)
    assert len(facts) == 1
    assert facts[0].text == "Updated Fact"

def test_topic_filtering(tmp_path):
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(data_dir=data_dir, persona_name=persona_name, description="test", behavior_prompt="test")
    persona_root = data_dir / "personas" / persona_name
    
    source_id = "source:test:456"
    bundle_paths = get_source_bundle_paths(persona_root, source_id)
    bundle_paths.source_dir.mkdir(parents=True)
    
    write_source_metadata(bundle_paths.metadata_path, {
        "source_id": source_id, "kind": "notes", "label": "t.txt", 
        "review_status": "pending", "source_class": "manual_source", "trust_class": "authored_primary"
    })
    
    facts = [
        {"text": "Political Fact", "topic": "Politics"},
        {"text": "Personal Fact", "topic": "Life"}
    ]
    bundle_paths.facts_path.write_text(json.dumps(facts), encoding="utf-8")
    
    approve_source_bundle(data_dir, persona_name, source_id)
    
    # Test case-insensitive filtering
    politics_facts = query_approved_facts(data_dir, persona_name, topic="politics")
    assert len(politics_facts) == 1
    assert politics_facts[0].text == "Political Fact"
    
    life_facts = query_approved_facts(data_dir, persona_name, topic="LIFE")
    assert len(life_facts) == 1
    assert life_facts[0].text == "Personal Fact"
    
    none_facts = query_approved_facts(data_dir, persona_name, topic="nonexistent")
    assert len(none_facts) == 0

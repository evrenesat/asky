"""Tests for milestone-3 approved-only runtime boundary."""

import json
from pathlib import Path

import pytest

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
)
from asky.plugins.persona_manager.runtime_planner import plan_persona_packets


def test_approved_only_retrieval(tmp_path, monkeypatch):
    """Verify that only approved milestone-3 knowledge appears in runtime retrieval."""
    data_dir = tmp_path / "data"
    persona_name = "arendt"
    create_persona(
        data_dir=data_dir,
        persona_name=persona_name,
        description="test",
        behavior_prompt="test",
    )
    
    persona_root = data_dir / "personas" / persona_name
    
    # 1. Create a pending source
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
    bundle_paths.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    
    viewpoints = [{"claim": "Freedom is action", "topic": "politics", "confidence": 0.9}]
    bundle_paths.viewpoints_path.write_text(json.dumps(viewpoints), encoding="utf-8")
    bundle_paths.facts_path.write_text("[]", encoding="utf-8")
    bundle_paths.timeline_path.write_text("[]", encoding="utf-8")
    bundle_paths.conflicts_path.write_text("[]", encoding="utf-8")

    # Mock embeddings to return deterministic vectors
    class MockEmbedding:
        def embed_single(self, text):
            return [0.1] * 1536
        def embed(self, texts):
            return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr("asky.plugins.manual_persona_creator.runtime_index.get_embedding_client", lambda: MockEmbedding())
    monkeypatch.setattr("asky.plugins.persona_manager.runtime_planner.get_embedding_client", lambda: MockEmbedding())
    monkeypatch.setattr("asky.plugins.persona_manager.knowledge.rebuild_embeddings", lambda **k: {})

    # Initially, retrieval should be empty (pending source not projected)
    packets = plan_persona_packets(persona_dir=persona_root, query_text="freedom", top_k=5)
    assert len(packets) == 0
    
    # 2. Approve the source
    approve_source_bundle(data_dir, persona_name, source_id)
    
    # Now it should be retrievable
    packets = plan_persona_packets(persona_dir=persona_root, query_text="freedom", top_k=5)
    assert len(packets) > 0
    assert any(p.text == "Freedom is action" for p in packets)
    
    # 3. Facts and timeline should still be excluded from primary packets
    # Let's add a fact
    facts = [{"text": "Born in 1906", "topic": "birth", "attribution": "biographer"}]
    bundle_paths.facts_path.write_text(json.dumps(facts), encoding="utf-8")
    
    approve_source_bundle(data_dir, persona_name, source_id) # Re-approve to project new fact
    
    packets = plan_persona_packets(persona_dir=persona_root, query_text="1906", top_k=5)
    # Even though it's approved and in index, it's not a PRIMARY_KIND
    assert not any(p.text == "Born in 1906" for p in packets)

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    get_web_collection_paths,
    get_web_page_paths,
    get_source_bundle_paths,
    get_promoted_web_source_id,
    read_web_page_manifest,
)
from asky.plugins.manual_persona_creator.web_service import approve_web_page, reject_web_page
from asky.plugins.manual_persona_creator.web_types import (
    WebPageManifest,
    WebPageStatus,
    WebPageClassification,
)

def test_approve_web_page_materialization(tmp_path: Path):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_approval"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    
    page_id = "page:123"
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    p_paths.page_dir.mkdir(parents=True)
    
    # Write page artifacts
    p_paths.content_path.write_text("# Web Content", encoding="utf-8")
    
    manifest = {
        "page_id": page_id,
        "status": "review_ready",
        "requested_url": "https://example.com",
        "final_url": "https://example.com/",
        "normalized_final_url": "example.com/",
        "title": "Example",
        "classification": "authored_by_persona"
    }
    import tomlkit
    doc = tomlkit.document()
    for k, v in manifest.items():
        doc[k] = v
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    
    preview = {
        "short_summary": "Summary",
        "candidate_viewpoints": [{"viewpoint": "VP1", "topic": "T1"}]
    }
    p_paths.preview_path.write_text(json.dumps(preview), encoding="utf-8")
    
    # Approve
    approve_web_page(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, page_id=page_id)
    
    # Verify status updated
    m_data = tomllib_load(p_paths.manifest_path)
    assert m_data["status"] == "approved"
    
    # Verify source bundle materialized
    source_id = get_promoted_web_source_id("example.com/")
    bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
    
    assert bundle_paths.source_dir.exists()
    assert bundle_paths.source_dir.name == source_id
    assert bundle_paths.content_path.read_text(encoding="utf-8") == "# Web Content"
    assert bundle_paths.metadata_path.exists()
    assert bundle_paths.viewpoints_path.exists()
    
    # Verify knowledge index
    from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
    catalog = read_catalog(paths.root_dir)
    assert any(s.source_id == source_id for s in catalog["sources"])
    assert any(e.source_id == source_id and e.entry_kind == "viewpoint" for e in catalog["entries"])

def tomllib_load(path: Path):
    import tomllib
    with path.open("rb") as f:
        return tomllib.load(f)

def test_reject_after_approve_retracts_knowledge(tmp_path: Path):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_retract"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    
    page_id = "page:retract"
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    p_paths.page_dir.mkdir(parents=True)
    p_paths.content_path.write_text("# Content", encoding="utf-8")
    
    manifest = {
        "page_id": page_id,
        "status": "review_ready",
        "requested_url": "https://example.com/r",
        "final_url": "https://example.com/r",
        "normalized_final_url": "example.com/r",
        "title": "Retract",
        "classification": "authored_by_persona"
    }
    import tomlkit
    doc = tomlkit.document()
    for k, v in manifest.items():
        doc[k] = v
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    
    # 1. Approve
    approve_web_page(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, page_id=page_id)
    
    source_id = get_promoted_web_source_id("example.com/r")
    from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
    catalog = read_catalog(paths.root_dir)
    assert any(s.source_id == source_id for s in catalog["sources"])
    
    # 2. Reject (Retract)
    reject_web_page(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, page_id=page_id)
    
    # Verify removed
    catalog = read_catalog(paths.root_dir)
    assert not any(s.source_id == source_id for s in catalog["sources"])
    
    bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
    assert not bundle_paths.source_dir.exists()

def test_retract_web_page_syncs_bundle_status(tmp_path: Path):
    from asky.plugins.manual_persona_creator.web_service import approve_web_page, retract_web_page
    from asky.plugins.manual_persona_creator.storage import (
        create_persona,
        get_persona_paths,
        get_web_collection_paths,
        get_web_page_paths,
        get_source_bundle_paths,
        read_source_metadata,
    )
    from asky.plugins.manual_persona_creator.source_types import PersonaReviewStatus

    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_sync"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    
    page_id = "page:sync"
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    p_paths.page_dir.mkdir(parents=True)
    p_paths.content_path.write_text("# Sync Content", encoding="utf-8")
    
    manifest = {
        "page_id": page_id,
        "status": "review_ready",
        "requested_url": "https://example.com/sync",
        "final_url": "https://example.com/sync",
        "normalized_final_url": "example.com/sync",
        "title": "Sync",
        "classification": "authored_by_persona"
    }
    import tomlkit
    doc = tomlkit.document()
    for k, v in manifest.items():
        doc[k] = v
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    
    # 1. Approve
    approve_web_page(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, page_id=page_id)
    
    import tomllib
    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    source_id = m["promoted_source_id"]
    
    bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
    meta = read_source_metadata(bundle_paths.metadata_path)
    assert meta["review_status"] == PersonaReviewStatus.APPROVED.value
    
    # 2. Retract
    retract_web_page(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, page_id=page_id)
    
    # Verify page status
    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    assert m["status"] == "review_ready"
    
    # Verify bundle status sync
    meta = read_source_metadata(bundle_paths.metadata_path)
    assert meta["review_status"] == PersonaReviewStatus.PENDING.value

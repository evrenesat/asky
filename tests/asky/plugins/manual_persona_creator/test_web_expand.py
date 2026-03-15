from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

import pytest
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    get_web_collection_paths,
    get_web_page_paths,
    read_web_frontier,
)
from asky.plugins.manual_persona_creator.web_job import WebCollectionJob
from asky.plugins.manual_persona_creator.web_types import (
    WebCollectionManifest,
    WebCollectionMode,
    WebCollectionInputMode,
    WebCollectionStatus,
)

@pytest.fixture
def mock_retrieval():
    with patch("asky.plugins.manual_persona_creator.web_job.fetch_url_document") as mock:
        yield mock

def test_broad_expansion_overcollect_cap(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_broad"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 10", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.BROAD_EXPAND,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=10,
        seed_inputs=["https://example.com/1"],
    )
    
    # Target 10 -> overcollect_cap = 13
    # We'll mock 15 different pages. It should stop after 13.
    mock_retrieval.side_effect = [
        {
            "final_url": f"https://example.com/{i}",
            "content": f"Content {i}",
            "links": [{"href": f"https://example.com/{i+1}"}]
        } for i in range(1, 20)
    ]
    
    job = WebCollectionJob(persona_name=persona_name, persona_description="test", paths=c_paths, target_results=10, mode=WebCollectionMode.BROAD_EXPAND)
    job.run(manifest)
    
    # Should have fetched exactly 13 unique pages (including the first one)
    assert mock_retrieval.call_count == 13
    
    frontier = read_web_frontier(c_paths.frontier_path)
    assert frontier["overcollect_cap"] == 13
    assert frontier["raw_unique_fetch_count"] == 13

def test_near_duplicate_filtering_with_embeddings(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_near_dup"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 5", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.BROAD_EXPAND,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=5,
        seed_inputs=["https://example.com/1", "https://example.com/2"],
    )
    
    # Mock embeddings: page 1 and page 2 are very similar
    mock_embedding = MagicMock()
    # Return same embedding for both
    mock_embedding.embed_text.return_value = [0.1, 0.2, 0.3]
    
    mock_retrieval.side_effect = [
        {
            "final_url": "https://example.com/1",
            "content": "Content 1",
            "links": []
        },
        {
            "final_url": "https://example.com/2",
            "content": "Content 2 (almost same)",
            "links": []
        }
    ]
    
    job = WebCollectionJob(
        persona_name=persona_name, 
        persona_description="test", 
        paths=c_paths, 
        target_results=5, 
        mode=WebCollectionMode.BROAD_EXPAND,
        embedding_client=mock_embedding
    )
    job.run(manifest)
    
    # Should have 1 page and 1 duplicate
    pages_dir = c_paths.collection_dir / "pages"
    page_dirs = [p.name for p in pages_dir.iterdir() if p.is_dir()]
    assert any(p.startswith("page:") for p in page_dirs)
    assert any(p.startswith("dup:") for p in page_dirs)
    
    dup_id = [p for p in page_dirs if p.startswith("dup:")][0]
    p_paths = get_web_page_paths(c_paths.collection_dir, dup_id)
    from asky.plugins.manual_persona_creator.storage import read_web_page_report
    report = read_web_page_report(p_paths.report_path)
    assert report["duplicate_info"]["reason"] == "embedding_similarity"
    assert report["duplicate_info"]["similarity_score"] >= 0.99 # Same embedding returned

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


def test_seed_domain_collection_job(tmp_path: Path, mock_retrieval):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_20260314120000_12345678"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=2,
        seed_inputs=["https://example.com/start"],
    )
    
    # Mock first page fetch
    mock_retrieval.side_effect = [
        {
            "final_url": "https://example.com/start",
            "content": "Content of start page",
            "title": "Start Page",
            "links": [{"href": "https://example.com/page1"}, {"href": "https://other.com/page"}]
        },
        {
            "final_url": "https://example.com/page1",
            "content": "Content of page 1",
            "title": "Page 1",
            "links": []
        }
    ]
    
    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description="Test description",
        paths=c_paths,
        target_results=2,
        mode=WebCollectionMode.SEED_DOMAIN,
    )
    
    # Pre-write manifest for job._update_manifest_status
    import tomlkit
    doc = tomlkit.document()
    doc["status"] = manifest.status.value
    doc["collection_id"] = manifest.collection_id
    doc["target_results"] = manifest.target_results
    doc["updated_at"] = ""
    c_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    job.run(manifest)
    
    # Verify frontier filtering (only example.com should be added)
    assert mock_retrieval.call_count == 2
    mock_retrieval.assert_any_call(url="https://example.com/start", include_links=True, trace_context=ANY, trace_callback=ANY)
    mock_retrieval.assert_any_call(url="https://example.com/page1", include_links=True, trace_context=ANY, trace_callback=ANY)
    
    # Verify pages saved
    pages = [p.name for p in (c_paths.collection_dir / "pages").iterdir() if p.is_dir()]
    assert len(pages) == 2


def test_duplicate_filtering(tmp_path: Path, mock_retrieval):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_20260314120000_12345678"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=5,
        seed_inputs=["https://example.com/1", "https://example.com/2"],
    )
    
    # Mock fetches with identical content
    mock_retrieval.side_effect = [
        {
            "final_url": "https://example.com/1",
            "content": "Identical content",
            "title": "Page 1",
            "links": []
        },
        {
            "final_url": "https://example.com/2",
            "content": "Identical content",
            "title": "Page 2",
            "links": []
        }
    ]
    
    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description="Test description",
        paths=c_paths,
        target_results=5,
        mode=WebCollectionMode.SEED_DOMAIN,
    )
    
    # Pre-write manifest
    import tomlkit
    doc = tomlkit.document()
    doc["status"] = manifest.status.value
    doc["collection_id"] = manifest.collection_id
    doc["target_results"] = manifest.target_results
    doc["updated_at"] = ""
    c_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    job.run(manifest)
    
    # Only one page should be saved as review_ready
    pages_root = c_paths.collection_dir / "pages"
    page_dirs = [p for p in pages_root.iterdir() if p.is_dir()]
    assert len(page_dirs) == 2  # One page, one duplicate
    
    review_ready_count = 0
    for p in page_dirs:
        if p.name.startswith("page:"):
            review_ready_count += 1
    assert review_ready_count == 1


def test_broad_expansion_with_search(tmp_path: Path, mock_retrieval):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_20260314120000_SEARCH"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.BROAD_EXPAND,
        input_mode=WebCollectionInputMode.SEARCH_QUERY,
        status=WebCollectionStatus.COLLECTING,
        target_results=1,
        seed_inputs=["test query"],
    )
    
    mock_search = MagicMock(return_value={"results": [{"url": "https://searched.com/res"}]})
    
    mock_retrieval.side_effect = [
        {
            "final_url": "https://searched.com/res",
            "content": "Searched content",
            "title": "Searched Result",
            "links": []
        }
    ]
    
    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description="Test description",
        paths=c_paths,
        target_results=1,
        mode=WebCollectionMode.BROAD_EXPAND,
        search_executor=mock_search,
    )
    
    # Pre-write manifest
    import tomlkit
    doc = tomlkit.document()
    doc["status"] = manifest.status.value
    doc["collection_id"] = manifest.collection_id
    doc["target_results"] = manifest.target_results
    doc["updated_at"] = ""
    c_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    job.run(manifest)
    
    mock_search.assert_called_once()
    assert mock_search.call_args[0][0]["query"] == "test query"
    assert mock_retrieval.call_count == 1
    mock_retrieval.assert_any_call(url="https://searched.com/res", include_links=True, trace_context=ANY, trace_callback=ANY)


def test_broad_expansion_cross_domain(tmp_path: Path, mock_retrieval):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_20260314120000_BROAD"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.BROAD_EXPAND,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=2,
        seed_inputs=["https://example.com/start"],
    )
    
    # Mock fetches: first page has a cross-domain link
    mock_retrieval.side_effect = [
        {
            "final_url": "https://example.com/start",
            "content": "Start content",
            "title": "Start",
            "links": [{"href": "https://other-domain.com/page"}]
        },
        {
            "final_url": "https://other-domain.com/page",
            "content": "Other content",
            "title": "Other",
            "links": []
        }
    ]
    
    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description="Test description",
        paths=c_paths,
        target_results=2,
        mode=WebCollectionMode.BROAD_EXPAND,
    )
    
    # Pre-write manifest
    import tomlkit
    doc = tomlkit.document()
    doc["status"] = manifest.status.value
    doc["collection_id"] = manifest.collection_id
    doc["target_results"] = manifest.target_results
    doc["updated_at"] = ""
    c_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    job.run(manifest)
    
    # Verify cross-domain URL was fetched
    assert mock_retrieval.call_count == 2
    mock_retrieval.assert_any_call(url="https://other-domain.com/page", include_links=True, trace_context=ANY, trace_callback=ANY)

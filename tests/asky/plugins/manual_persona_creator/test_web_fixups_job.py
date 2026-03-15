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
    read_web_page_manifest,
    read_web_page_report,
)
from asky.plugins.manual_persona_creator.web_job import WebCollectionJob
from asky.plugins.manual_persona_creator.web_types import (
    WebCollectionManifest,
    WebCollectionMode,
    WebCollectionInputMode,
    WebCollectionStatus,
    WebPageStatus,
)

@pytest.fixture
def mock_retrieval():
    with patch("asky.plugins.manual_persona_creator.web_job.fetch_url_document") as mock:
        yield mock

def test_host_boundary_apex_www_alias(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_alias"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    
    # Pre-write manifest
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 10", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=10,
        seed_inputs=["https://example.com"],
    )
    
    job = WebCollectionJob(persona_name=persona_name, persona_description="test", paths=c_paths, target_results=10, mode=WebCollectionMode.SEED_DOMAIN)
    
    # Mock fetches: example.com has links to www.example.com (allow), sub.example.com (reject), example.org (reject)
    mock_retrieval.side_effect = [
        {
            "final_url": "https://example.com/",
            "content": "Start",
            "links": [
                {"href": "https://www.example.com/page"},
                {"href": "https://sub.example.com/page"},
                {"href": "https://example.org/page"}
            ]
        },
        {
            "final_url": "https://www.example.com/page",
            "content": "WWW Page",
            "links": []
        }
    ]
    
    job.run(manifest)
    
    # Only example.com and www.example.com should be fetched
    assert mock_retrieval.call_count == 2
    mock_retrieval.assert_any_call(url="https://example.com", include_links=True, trace_context=ANY, trace_callback=ANY)
    mock_retrieval.assert_any_call(url="https://www.example.com/page", include_links=True, trace_context=ANY, trace_callback=ANY)

def test_host_boundary_subdomain_seed(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_sub"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 10", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=10,
        seed_inputs=["https://docs.example.com"],
    )
    
    job = WebCollectionJob(persona_name=persona_name, persona_description="test", paths=c_paths, target_results=10, mode=WebCollectionMode.SEED_DOMAIN)
    
    # Mock fetches: docs.example.com has links to example.com (reject), www.example.com (reject)
    mock_retrieval.side_effect = [
        {
            "final_url": "https://docs.example.com/",
            "content": "Docs",
            "links": [
                {"href": "https://example.com/"},
                {"href": "https://www.example.com/"}
            ]
        }
    ]
    
    job.run(manifest)
    
    assert mock_retrieval.call_count == 1
    mock_retrieval.assert_any_call(url="https://docs.example.com", include_links=True, trace_context=ANY, trace_callback=ANY)

def test_failed_page_persistence(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_fail"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 10", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=10,
        seed_inputs=["https://example.com/fail"],
    )
    
    mock_retrieval.return_value = {"error": "404 Not Found", "final_url": "https://example.com/fail"}
    
    job = WebCollectionJob(persona_name=persona_name, persona_description="test", paths=c_paths, target_results=10, mode=WebCollectionMode.SEED_DOMAIN)
    job.run(manifest)
    
    # Verify failed page exists
    pages_dir = c_paths.collection_dir / "pages"
    failed_dirs = [p for p in pages_dir.iterdir() if p.name.startswith("failed:")]
    assert len(failed_dirs) == 1
    
    p_paths = get_web_page_paths(c_paths.collection_dir, failed_dirs[0].name)
    manifest_data = read_web_page_manifest(p_paths.manifest_path)
    assert manifest_data["status"] == WebPageStatus.FETCH_FAILED.value
    
    report_data = read_web_page_report(p_paths.report_path)
    assert report_data["status"] == WebPageStatus.FETCH_FAILED.value
    assert report_data["failure_reason"] == "404 Not Found"

def test_retrieval_provenance_recording(tmp_path: Path, mock_retrieval):
    persona_name = "arendt"
    create_persona(data_dir=tmp_path, persona_name=persona_name, description="test", behavior_prompt="test")
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = "web_test_provenance"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    c_paths.manifest_path.write_text("status = 'collecting'\ntarget_results = 1", encoding="utf-8")

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=WebCollectionInputMode.SEED_URLS,
        status=WebCollectionStatus.COLLECTING,
        target_results=1,
        seed_inputs=["https://example.com"],
    )
    
    # We want to verify that trace_events are captured.
    # Since fetch_url_document is mocked, we need to make it call the callback if we want real events,
    # OR we can just verify the job passes a callback.
    
    def side_effect(url, **kwargs):
        callback = kwargs.get("trace_callback")
        if callback:
            callback({"kind": "playwright_success", "source": "playwright_browser", "url": url})
        return {
            "final_url": url,
            "content": "Provenance test",
            "source": "playwright/trafilatura",
            "page_type": "article",
            "links": []
        }
    
    mock_retrieval.side_effect = side_effect
    
    job = WebCollectionJob(persona_name=persona_name, persona_description="test", paths=c_paths, target_results=1, mode=WebCollectionMode.SEED_DOMAIN)
    job.run(manifest)
    
    pages_dir = c_paths.collection_dir / "pages"
    page_id = [p.name for p in pages_dir.iterdir() if p.name.startswith("page:")][0]
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    
    report = read_web_page_report(p_paths.report_path)
    assert report["retrieval"]["provider"] == "playwright"
    assert report["retrieval"]["source"] == "playwright/trafilatura"
    assert any(ev["kind"] == "playwright_success" for ev in report["retrieval"]["trace_events"])

from __future__ import annotations

import json
from pathlib import Path

import pytest
from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    get_web_collection_id,
    get_web_collection_paths,
    get_web_page_id,
    get_web_page_paths,
    list_web_collections,
    list_web_pages,
    create_persona,
)
from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.persona_manager.importer import import_persona_archive


def test_web_storage_paths(tmp_path: Path):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    collection_id = get_web_collection_id()
    assert collection_id.startswith("web_")
    
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    assert c_paths.collection_dir.name == collection_id
    assert c_paths.manifest_path.name == "collection.toml"
    assert c_paths.frontier_path.name == "frontier.json"
    
    page_id = get_web_page_id("https://example.com/page")
    assert page_id.startswith("page:")
    
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    assert p_paths.page_dir.name == page_id
    assert p_paths.manifest_path.name == "page.toml"
    assert p_paths.content_path.name == "content.md"
    assert p_paths.links_path.name == "links.json"
    assert p_paths.preview_path.name == "preview.json"


def test_web_collection_listing(tmp_path: Path):
    persona_name = "test_persona"
    create_persona(
        data_dir=tmp_path,
        persona_name=persona_name,
        description="Test description",
        behavior_prompt="Test prompt",
    )
    paths = get_persona_paths(tmp_path, persona_name)
    
    assert list_web_collections(paths.root_dir) == []
    
    collection_id = "web_20260314120000_12345678"
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True)
    
    assert list_web_collections(paths.root_dir) == [collection_id]
    
    assert list_web_pages(c_paths.collection_dir) == []
    page_id = "page:1234567890abcdef"
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    p_paths.page_dir.mkdir(parents=True)
    
    assert list_web_pages(c_paths.collection_dir) == [page_id]


def test_web_collection_export_import(tmp_path: Path):
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
    c_paths.manifest_path.write_text("status = 'review_ready'", encoding="utf-8")
    c_paths.frontier_path.write_text("[]", encoding="utf-8")
    
    page_id = "page:1234567890abcdef"
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
    p_paths.page_dir.mkdir(parents=True)
    p_paths.manifest_path.write_text("title = 'Test Page'", encoding="utf-8")
    p_paths.content_path.write_text("# Test content", encoding="utf-8")
    
    # Export
    export_path = tmp_path / "export.zip"
    export_persona_package(
        data_dir=tmp_path,
        persona_name=persona_name,
        output_path=str(export_path),
    )
    assert export_path.exists()
    
    # Import into new location
    import_dir = tmp_path / "import_root"
    import_persona_archive(data_dir=import_dir, archive_path=str(export_path))
    
    i_paths = get_persona_paths(import_dir, persona_name)
    assert i_paths.root_dir.exists()
    
    i_c_paths = get_web_collection_paths(i_paths.root_dir, collection_id)
    assert i_c_paths.collection_dir.exists()
    assert i_c_paths.manifest_path.read_text(encoding="utf-8") == "status = 'review_ready'"
    
    i_p_paths = get_web_page_paths(i_c_paths.collection_dir, page_id)
    assert i_p_paths.page_dir.exists()
    assert i_p_paths.content_path.read_text(encoding="utf-8") == "# Test content"

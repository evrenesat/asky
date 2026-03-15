from __future__ import annotations

import json
from pathlib import Path

import pytest
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    get_web_collection_paths,
    get_web_page_paths,
)
from asky.plugins.manual_persona_creator.web_service import get_collection_review_pages
from asky.plugins.manual_persona_creator.web_types import WebPageStatus


def test_get_collection_review_pages(tmp_path: Path):
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
    
    # Create one review_ready page
    page1_id = "page:1"
    p1_paths = get_web_page_paths(c_paths.collection_dir, page1_id)
    p1_paths.page_dir.mkdir(parents=True)
    p1_paths.manifest_path.write_text("status = 'review_ready'\npage_id = 'page:1'", encoding="utf-8")
    
    # Create one approved page
    page2_id = "page:2"
    p2_paths = get_web_page_paths(c_paths.collection_dir, page2_id)
    p2_paths.page_dir.mkdir(parents=True)
    p2_paths.manifest_path.write_text("status = 'approved'\npage_id = 'page:2'", encoding="utf-8")
    
    # List all
    pages = get_collection_review_pages(data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id)
    assert len(pages) == 2
    
    # List review_ready only
    ready_pages = get_collection_review_pages(
        data_dir=tmp_path, persona_name=persona_name, collection_id=collection_id, status=WebPageStatus.REVIEW_READY.value
    )
    assert len(ready_pages) == 1
    assert ready_pages[0]["page_id"] == "page:1"

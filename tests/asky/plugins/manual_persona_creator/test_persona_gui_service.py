"""Tests for Persona GUI service adapters."""

from __future__ import annotations

from pathlib import Path
from asky.plugins.manual_persona_creator.gui_service import list_personas_summary, get_persona_detail
from asky.plugins.manual_persona_creator.storage import get_persona_paths


def test_list_personas_summary(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # Create a persona
    p_name = "test_persona"
    paths = get_persona_paths(data_dir, p_name)
    paths.root_dir.mkdir(parents=True)
    paths.metadata_path.write_text(f"[persona]\nname = '{p_name}'\nschema_version = 3\ndescription = 'test desc'", encoding="utf-8")
    
    summaries = list_personas_summary(data_dir)
    assert len(summaries) == 1
    assert summaries[0].name == p_name
    assert summaries[0].description == "test desc"


def test_get_persona_detail(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    p_name = "test_persona"
    paths = get_persona_paths(data_dir, p_name)
    paths.root_dir.mkdir(parents=True)
    paths.metadata_path.write_text(f"[persona]\nname = '{p_name}'\nschema_version = 3\ndescription = 'test desc'", encoding="utf-8")
    
    detail = get_persona_detail(data_dir, p_name)
    assert detail["name"] == p_name
    assert "metadata" in detail
    assert "books" in detail
    assert "approved_sources" in detail

from __future__ import annotations

import logging
from pathlib import Path
from zipfile import ZipFile

import pytest

from asky.core.registry import ToolRegistry
from asky.plugins.base import PluginContext
from asky.plugins.hook_types import ToolRegistryBuildContext
from asky.plugins.hooks import HookRegistry
from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.ingestion import ingest_persona_sources
from asky.plugins.manual_persona_creator.plugin import ManualPersonaCreatorPlugin
from asky.plugins.manual_persona_creator.storage import (
    PERSONA_SCHEMA_VERSION,
    create_persona,
    get_persona_paths,
    read_metadata,
    validate_persona_name,
    write_chunks,
)


def _plugin_context(tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    return PluginContext(
        plugin_name="manual_persona_creator",
        config_dir=tmp_path,
        data_dir=tmp_path / "plugin_data",
        config={},
        hook_registry=hooks,
        logger=logging.getLogger("test.manual_persona_creator"),
    )


def test_manual_persona_creator_does_not_register_tools(tmp_path: Path):
    """Persona creation tools are now CLI-only and should not be registered."""
    hooks = HookRegistry()
    plugin = ManualPersonaCreatorPlugin()
    context = _plugin_context(tmp_path, hooks)
    plugin.activate(context)

    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    assert "manual_persona_create" not in registry.get_tool_names()
    assert "manual_persona_export" not in registry.get_tool_names()


def test_persona_storage_validation_and_schema(tmp_path: Path):
    data_dir = tmp_path / "data"
    create_persona(
        data_dir=data_dir,
        persona_name="demo_persona",
        description="demo",
        behavior_prompt="be concise",
    )

    metadata = read_metadata(get_persona_paths(data_dir, "demo_persona").metadata_path)
    assert metadata["persona"]["schema_version"] == PERSONA_SCHEMA_VERSION

    with pytest.raises(ValueError):
        validate_persona_name("bad name with spaces")


def test_ingestion_returns_partial_warnings(tmp_path: Path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("Line one.\nLine two.\nLine three.", encoding="utf-8")

    result = ingest_persona_sources(
        sources=[str(file_path), str(tmp_path / "missing.txt")],
        min_chunk_chars=4,
    )

    assert result["stats"]["processed_sources"] >= 1
    assert len(result["chunks"]) >= 1
    assert len(result["warnings"]) >= 1


def test_export_contains_metadata_prompt_and_chunks(tmp_path: Path):
    data_dir = tmp_path / "data"
    paths = create_persona(
        data_dir=data_dir,
        persona_name="exportable",
        description="demo",
        behavior_prompt="answer like exportable",
    )
    write_chunks(
        paths.chunks_path,
        [
            {
                "chunk_id": "1:1",
                "chunk_index": 1,
                "text": "Chunk text",
                "source": str(tmp_path / "absolute/source.txt"),
                "title": "Source",
            }
        ],
    )

    archive_path = export_persona_package(data_dir=data_dir, persona_name="exportable")

    with ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
        assert names == {"metadata.toml", "behavior_prompt.md", "chunks.json"}
        chunks_payload = archive.read("chunks.json").decode("utf-8")
        assert "source.txt" in chunks_payload
        assert str(tmp_path) not in chunks_payload

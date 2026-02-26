from __future__ import annotations

import json
import logging
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from asky.core.registry import ToolRegistry
from asky.plugins.base import PluginContext
from asky.plugins.hook_types import PrePreloadContext, SessionResolvedContext, ToolRegistryBuildContext
from asky.plugins.hooks import HookRegistry
from asky.plugins.manual_persona_creator.storage import PERSONA_SCHEMA_VERSION
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.plugin import PersonaManagerPlugin


class _FakeEmbeddingClient:
    def embed(self, texts):
        return [[float(i + 1), float(i + 2)] for i, _ in enumerate(texts)]

    def embed_single(self, text):
        _ = text
        return [1.0, 2.0]


def _plugin_context(tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    return PluginContext(
        plugin_name="persona_manager",
        config_dir=tmp_path,
        data_dir=tmp_path / "persona_data",
        config={"knowledge_top_k": 2},
        hook_registry=hooks,
        logger=logging.getLogger("test.persona_manager"),
    )


def _create_persona_archive(tmp_path: Path, name: str = "demo") -> Path:
    archive_path = tmp_path / f"{name}.zip"
    metadata = (
        "[persona]\n"
        f'name = "{name}"\n'
        f"schema_version = {PERSONA_SCHEMA_VERSION}\n"
    )
    chunks = [
        {
            "chunk_id": "1:1",
            "chunk_index": 1,
            "text": "Persona chunk text",
            "source": "notes.txt",
            "title": "Notes",
        }
    ]

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("metadata.toml", metadata)
        archive.writestr("behavior_prompt.md", "Speak like demo persona")
        archive.writestr("chunks.json", json.dumps(chunks))
    return archive_path


def test_persona_manager_does_not_register_tools(tmp_path: Path):
    """Persona tools are now CLI-only and should not be registered."""
    hooks = HookRegistry()
    plugin = PersonaManagerPlugin()
    context = _plugin_context(tmp_path, hooks)
    plugin.activate(context)

    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    assert "persona_import_package" not in registry.get_tool_names()
    assert "persona_load" not in registry.get_tool_names()


def test_import_rebuilds_embeddings(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    archive_path = _create_persona_archive(tmp_path, name="imported")
    result = import_persona_archive(
        data_dir=tmp_path / "persona_data",
        archive_path=str(archive_path),
    )

    assert result["ok"] is True
    assert result["embedding_stats"]["embedded_chunks"] == 1
    assert (tmp_path / "persona_data" / "personas" / "imported" / "embeddings.json").exists()


def test_prompt_and_preload_injection_for_loaded_persona(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    archive_path = _create_persona_archive(tmp_path, name="loaded")
    import_persona_archive(
        data_dir=tmp_path / "persona_data",
        archive_path=str(archive_path),
    )

    hooks = HookRegistry()
    plugin = PersonaManagerPlugin()
    context = _plugin_context(tmp_path, hooks)
    plugin.activate(context)

    hooks.invoke(
        "SESSION_RESOLVED",
        SessionResolvedContext(
            request=None,
            session_manager=None,
            session_resolution=type("S", (), {"session_id": 7})(),
        ),
    )

    # Directly call the plugin method instead of using tool dispatch
    result = plugin._tool_load_persona({"name": "loaded"})
    assert result.get("ok") is True

    extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base prompt")
    assert "Loaded Persona (loaded)" in extended_prompt

    pre_payload = PrePreloadContext(
        request=type("R", (), {"lean": False})(),
        query_text="what should I do",
        research_mode=False,
        research_source_mode=None,
        local_corpus_paths=None,
        preload_local_sources=True,
        preload_shortlist=True,
        shortlist_override=None,
        additional_source_context=None,
    )
    hooks.invoke("PRE_PRELOAD", pre_payload)
    assert "Persona knowledge context:" in str(pre_payload.additional_source_context)


def test_session_binding_persists_and_child_session_is_unbound(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    archive_path = _create_persona_archive(tmp_path, name="sticky")
    import_persona_archive(
        data_dir=tmp_path / "persona_data",
        archive_path=str(archive_path),
    )

    hooks_a = HookRegistry()
    plugin_a = PersonaManagerPlugin()
    context_a = _plugin_context(tmp_path, hooks_a)
    plugin_a.activate(context_a)

    hooks_a.invoke(
        "SESSION_RESOLVED",
        SessionResolvedContext(
            request=None,
            session_manager=None,
            session_resolution=type("S", (), {"session_id": 42})(),
        ),
    )
    
    # Directly call the plugin method instead of using tool dispatch
    result = plugin_a._tool_load_persona({"name": "sticky"})
    assert result.get("ok") is True

    hooks_b = HookRegistry()
    plugin_b = PersonaManagerPlugin()
    context_b = _plugin_context(tmp_path, hooks_b)
    plugin_b.activate(context_b)

    hooks_b.invoke(
        "SESSION_RESOLVED",
        SessionResolvedContext(
            request=None,
            session_manager=None,
            session_resolution=type("S", (), {"session_id": 42})(),
        ),
    )
    assert "Loaded Persona (sticky)" in hooks_b.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")

    hooks_b.invoke(
        "SESSION_RESOLVED",
        SessionResolvedContext(
            request=None,
            session_manager=None,
            session_resolution=type("S", (), {"session_id": 43})(),
        ),
    )
    assert hooks_b.invoke_chain("SYSTEM_PROMPT_EXTEND", "base") == "base"

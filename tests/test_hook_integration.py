"""Integration tests for persona manager hook system.

Tests the complete hook integration flow with mention-based persona loading:
- SESSION_RESOLVED hook restores persona bindings
- SYSTEM_PROMPT_EXTEND hook injects persona behavior
- PRE_PRELOAD hook injects persona knowledge
- End-to-end flow: mention → resolve → load → hooks execute
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from asky.cli.mention_parser import parse_persona_mention
from asky.plugins.base import PluginContext
from asky.plugins.hook_types import (
    PrePreloadContext,
    SessionResolvedContext,
)
from asky.plugins.hooks import HookRegistry
from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import (
    PERSONA_SCHEMA_VERSION,
    create_persona,
)
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.plugin import PersonaManagerPlugin
from asky.plugins.persona_manager.resolver import (
    resolve_persona_name,
    set_persona_alias,
)
from asky.plugins.persona_manager.session_binding import set_session_binding


class _FakeEmbeddingClient:
    """Fake embedding client for testing."""

    def embed(self, texts):
        return [[float(i + 1), float(i + 2)] for i, _ in enumerate(texts)]

    def embed_single(self, text):
        _ = text
        return [1.0, 2.0]


def _plugin_context(tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    """Create a plugin context for testing."""
    return PluginContext(
        plugin_name="persona_manager",
        config_dir=tmp_path,
        data_dir=tmp_path / "persona_data",
        config={"knowledge_top_k": 3},
        hook_registry=hooks,
        logger=logging.getLogger("test.hook_integration"),
    )


def _create_persona_archive(
    tmp_path: Path,
    name: str = "test_persona",
    behavior_prompt: str = "Test behavior prompt",
    chunks: list | None = None,
) -> Path:
    """Create a persona archive for testing."""
    archive_path = tmp_path / f"{name}.zip"
    metadata = (
        "[persona]\n"
        f'name = "{name}"\n'
        f"schema_version = {PERSONA_SCHEMA_VERSION}\n"
    )

    if chunks is None:
        chunks = [
            {
                "chunk_id": "1:1",
                "chunk_index": 1,
                "text": "Test knowledge chunk about testing",
                "source": "test_notes.txt",
                "title": "Test Notes",
            },
            {
                "chunk_id": "1:2",
                "chunk_index": 2,
                "text": "Additional knowledge about development",
                "source": "dev_notes.txt",
                "title": "Dev Notes",
            },
        ]

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("metadata.toml", metadata)
        archive.writestr("behavior_prompt.md", behavior_prompt)
        archive.writestr("chunks.json", json.dumps(chunks))

    return archive_path


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory for testing."""
    return tmp_path / "data"


@pytest.fixture
def kvstore(tmp_path: Path) -> PluginKVStore:
    """Create a KVStore instance for testing."""
    db_path = tmp_path / "test.db"
    return PluginKVStore("persona_manager", db_path=db_path)


@pytest.fixture
def sample_personas(monkeypatch, temp_data_dir: Path):
    """Create sample personas for testing."""
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )

    create_persona(
        data_dir=temp_data_dir,
        persona_name="developer",
        description="Software developer persona",
        behavior_prompt="You are a helpful software developer with expertise in Python.",
    )

    create_persona(
        data_dir=temp_data_dir,
        persona_name="writer",
        description="Content writer persona",
        behavior_prompt="You are a creative content writer with a focus on clarity.",
    )


class TestSessionResolvedHook:
    """Test SESSION_RESOLVED hook execution with mention-loaded personas."""

    def test_session_resolved_restores_persona_binding(
        self, monkeypatch, tmp_path: Path
    ):
        """Test that SESSION_RESOLVED hook restores persona from session binding."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        archive_path = _create_persona_archive(
            tmp_path, name="developer", behavior_prompt="You are a developer."
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive_path),
        )

        set_session_binding(
            tmp_path / "persona_data",
            session_id="42",
            persona_name="developer",
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
                session_resolution=type("S", (), {"session_id": "42"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base prompt")
        assert "Loaded Persona (developer)" in extended_prompt
        assert "You are a developer." in extended_prompt

    def test_session_resolved_with_mention_loaded_persona(
        self, monkeypatch, tmp_path: Path, kvstore: PluginKVStore
    ):
        """Test SESSION_RESOLVED hook with persona loaded via @mention."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        archive_path = _create_persona_archive(
            tmp_path, name="writer", behavior_prompt="You are a writer."
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive_path),
        )

        query = "@writer help me write an article"
        mention_result = parse_persona_mention(query)
        assert mention_result.has_mention

        resolved_name = resolve_persona_name(
            mention_result.persona_identifier,
            kvstore,
            tmp_path / "persona_data",
        )
        assert resolved_name == "writer"

        set_session_binding(
            tmp_path / "persona_data",
            session_id="100",
            persona_name=resolved_name,
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
                session_resolution=type("S", (), {"session_id": "100"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base prompt")
        assert "Loaded Persona (writer)" in extended_prompt
        assert "You are a writer." in extended_prompt

    def test_session_resolved_with_nonexistent_persona_clears_binding(
        self, monkeypatch, tmp_path: Path
    ):
        """Test that SESSION_RESOLVED clears binding if persona doesn't exist."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        set_session_binding(
            tmp_path / "persona_data",
            session_id="99",
            persona_name="nonexistent",
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
                session_resolution=type("S", (), {"session_id": "99"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base prompt")
        assert extended_prompt == "base prompt"


class TestSystemPromptExtendHook:
    """Test SYSTEM_PROMPT_EXTEND hook with persona context."""

    def test_system_prompt_extend_injects_persona_behavior(
        self, monkeypatch, tmp_path: Path
    ):
        """Test that SYSTEM_PROMPT_EXTEND hook injects persona behavior prompt."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        behavior_prompt = "You are an expert Python developer specializing in testing."
        archive_path = _create_persona_archive(
            tmp_path, name="test_expert", behavior_prompt=behavior_prompt
        )
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
                session_resolution=type("S", (), {"session_id": "50"})(),
            ),
        )

        result = plugin._tool_load_persona({"name": "test_expert"})
        assert result.get("ok") is True

        base_prompt = "You are a helpful AI assistant."
        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", base_prompt)

        assert base_prompt in extended_prompt
        assert "Loaded Persona (test_expert)" in extended_prompt
        assert behavior_prompt in extended_prompt

    def test_system_prompt_extend_with_no_persona_returns_unchanged(
        self, tmp_path: Path
    ):
        """Test that SYSTEM_PROMPT_EXTEND returns unchanged prompt when no persona."""
        hooks = HookRegistry()
        plugin = PersonaManagerPlugin()
        context = _plugin_context(tmp_path, hooks)
        plugin.activate(context)

        hooks.invoke(
            "SESSION_RESOLVED",
            SessionResolvedContext(
                request=None,
                session_manager=None,
                session_resolution=type("S", (), {"session_id": "60"})(),
            ),
        )

        base_prompt = "You are a helpful AI assistant."
        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", base_prompt)

        assert extended_prompt == base_prompt

    def test_system_prompt_extend_with_alias_loaded_persona(
        self, monkeypatch, tmp_path: Path, kvstore: PluginKVStore
    ):
        """Test SYSTEM_PROMPT_EXTEND with persona loaded via alias."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        behavior_prompt = "You are a DevOps engineer."
        archive_path = _create_persona_archive(
            tmp_path, name="devops", behavior_prompt=behavior_prompt
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive_path),
        )

        set_persona_alias("ops", "devops", kvstore, tmp_path / "persona_data")

        query = "@ops help me deploy"
        mention_result = parse_persona_mention(query)
        resolved_name = resolve_persona_name(
            mention_result.persona_identifier,
            kvstore,
            tmp_path / "persona_data",
        )
        assert resolved_name == "devops"

        set_session_binding(
            tmp_path / "persona_data",
            session_id="70",
            persona_name=resolved_name,
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
                session_resolution=type("S", (), {"session_id": "70"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")
        assert "Loaded Persona (devops)" in extended_prompt
        assert behavior_prompt in extended_prompt


class TestPrePreloadHook:
    """Test PRE_PRELOAD hook with persona sources."""

    def test_pre_preload_injects_persona_knowledge(
        self, monkeypatch, tmp_path: Path
    ):
        """Test that PRE_PRELOAD hook injects persona knowledge chunks."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        chunks = [
            {
                "chunk_id": "1:1",
                "chunk_index": 1,
                "text": "Python testing best practices include using pytest",
                "source": "testing_guide.md",
                "title": "Testing Guide",
            },
            {
                "chunk_id": "1:2",
                "chunk_index": 2,
                "text": "Always write unit tests for critical functions",
                "source": "testing_guide.md",
                "title": "Testing Guide",
            },
        ]

        archive_path = _create_persona_archive(
            tmp_path,
            name="test_guru",
            behavior_prompt="You are a testing expert.",
            chunks=chunks,
        )
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
                session_resolution=type("S", (), {"session_id": "80"})(),
            ),
        )

        result = plugin._tool_load_persona({"name": "test_guru"})
        assert result.get("ok") is True

        pre_payload = PrePreloadContext(
            request=type("R", (), {"lean": False})(),
            query_text="how do I write good tests",
            research_mode=False,
            research_source_mode=None,
            local_corpus_paths=None,
            preload_local_sources=True,
            preload_shortlist=True,
            shortlist_override="auto",
            additional_source_context=None,
        )

        hooks.invoke("PRE_PRELOAD", pre_payload)

        assert pre_payload.additional_source_context is not None
        assert "Persona knowledge context:" in pre_payload.additional_source_context
        assert "testing_guide.md" in pre_payload.additional_source_context

    def test_pre_preload_skips_when_lean_mode(self, monkeypatch, tmp_path: Path):
        """Test that PRE_PRELOAD skips persona knowledge in lean mode."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        archive_path = _create_persona_archive(tmp_path, name="lean_test")
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
                session_resolution=type("S", (), {"session_id": "85"})(),
            ),
        )

        result = plugin._tool_load_persona({"name": "lean_test"})
        assert result.get("ok") is True

        pre_payload = PrePreloadContext(
            request=type("R", (), {"lean": True})(),
            query_text="test query",
            research_mode=False,
            research_source_mode=None,
            local_corpus_paths=None,
            preload_local_sources=True,
            preload_shortlist=True,
            shortlist_override="auto",
            additional_source_context=None,
        )

        hooks.invoke("PRE_PRELOAD", pre_payload)

        assert pre_payload.additional_source_context is None

    def test_pre_preload_with_no_persona_does_nothing(self, tmp_path: Path):
        """Test that PRE_PRELOAD does nothing when no persona is loaded."""
        hooks = HookRegistry()
        plugin = PersonaManagerPlugin()
        context = _plugin_context(tmp_path, hooks)
        plugin.activate(context)

        hooks.invoke(
            "SESSION_RESOLVED",
            SessionResolvedContext(
                request=None,
                session_manager=None,
                session_resolution=type("S", (), {"session_id": "90"})(),
            ),
        )

        pre_payload = PrePreloadContext(
            request=type("R", (), {"lean": False})(),
            query_text="test query",
            research_mode=False,
            research_source_mode=None,
            local_corpus_paths=None,
            preload_local_sources=True,
            preload_shortlist=True,
            shortlist_override="auto",
            additional_source_context=None,
        )

        hooks.invoke("PRE_PRELOAD", pre_payload)

        assert pre_payload.additional_source_context is None


class TestEndToEndHookFlow:
    """Test end-to-end flow: mention → resolve → load → hooks execute."""

    def test_complete_mention_to_hooks_flow(
        self, monkeypatch, tmp_path: Path, kvstore: PluginKVStore
    ):
        """Test complete flow from @mention to all hooks executing."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        behavior_prompt = "You are a full-stack developer."
        chunks = [
            {
                "chunk_id": "1:1",
                "chunk_index": 1,
                "text": "React is a JavaScript library for building UIs",
                "source": "react_notes.md",
                "title": "React Notes",
            },
        ]

        archive_path = _create_persona_archive(
            tmp_path,
            name="fullstack",
            behavior_prompt=behavior_prompt,
            chunks=chunks,
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive_path),
        )

        query = "@fullstack how do I build a React app?"
        mention_result = parse_persona_mention(query)
        assert mention_result.has_mention
        assert mention_result.persona_identifier == "fullstack"
        assert mention_result.cleaned_query == "how do I build a React app?"

        resolved_name = resolve_persona_name(
            mention_result.persona_identifier,
            kvstore,
            tmp_path / "persona_data",
        )
        assert resolved_name == "fullstack"

        set_session_binding(
            tmp_path / "persona_data",
            session_id="200",
            persona_name=resolved_name,
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
                session_resolution=type("S", (), {"session_id": "200"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base prompt")
        assert "Loaded Persona (fullstack)" in extended_prompt
        assert behavior_prompt in extended_prompt

        pre_payload = PrePreloadContext(
            request=type("R", (), {"lean": False})(),
            query_text=mention_result.cleaned_query,
            research_mode=False,
            research_source_mode=None,
            local_corpus_paths=None,
            preload_local_sources=True,
            preload_shortlist=True,
            shortlist_override="auto",
            additional_source_context=None,
        )

        hooks.invoke("PRE_PRELOAD", pre_payload)

        assert pre_payload.additional_source_context is not None
        assert "Persona knowledge context:" in pre_payload.additional_source_context
        assert "react_notes.md" in pre_payload.additional_source_context

    def test_complete_alias_mention_to_hooks_flow(
        self, monkeypatch, tmp_path: Path, kvstore: PluginKVStore
    ):
        """Test complete flow with alias: @alias → resolve → load → hooks execute."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        behavior_prompt = "You are a data scientist."
        chunks = [
            {
                "chunk_id": "1:1",
                "chunk_index": 1,
                "text": "Pandas is a data manipulation library",
                "source": "data_science.md",
                "title": "Data Science",
            },
        ]

        archive_path = _create_persona_archive(
            tmp_path,
            name="data_scientist",
            behavior_prompt=behavior_prompt,
            chunks=chunks,
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive_path),
        )

        set_persona_alias("ds", "data_scientist", kvstore, tmp_path / "persona_data")

        query = "@ds help me analyze this dataset"
        mention_result = parse_persona_mention(query)
        assert mention_result.has_mention
        assert mention_result.persona_identifier == "ds"

        resolved_name = resolve_persona_name(
            mention_result.persona_identifier,
            kvstore,
            tmp_path / "persona_data",
        )
        assert resolved_name == "data_scientist"

        set_session_binding(
            tmp_path / "persona_data",
            session_id="300",
            persona_name=resolved_name,
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
                session_resolution=type("S", (), {"session_id": "300"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")
        assert "Loaded Persona (data_scientist)" in extended_prompt
        assert behavior_prompt in extended_prompt

        pre_payload = PrePreloadContext(
            request=type("R", (), {"lean": False})(),
            query_text=mention_result.cleaned_query,
            research_mode=False,
            research_source_mode=None,
            local_corpus_paths=None,
            preload_local_sources=True,
            preload_shortlist=True,
            shortlist_override="auto",
            additional_source_context=None,
        )

        hooks.invoke("PRE_PRELOAD", pre_payload)

        assert pre_payload.additional_source_context is not None
        assert "data_science.md" in pre_payload.additional_source_context

    def test_persona_replacement_via_mention_updates_hooks(
        self, monkeypatch, tmp_path: Path, kvstore: PluginKVStore
    ):
        """Test that replacing persona via mention updates all hooks."""
        monkeypatch.setattr(
            "asky.plugins.persona_manager.knowledge.get_embedding_client",
            lambda: _FakeEmbeddingClient(),
        )

        archive1 = _create_persona_archive(
            tmp_path, name="persona_a", behavior_prompt="You are persona A."
        )
        archive2 = _create_persona_archive(
            tmp_path, name="persona_b", behavior_prompt="You are persona B."
        )

        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive1),
        )
        import_persona_archive(
            data_dir=tmp_path / "persona_data",
            archive_path=str(archive2),
        )

        set_session_binding(
            tmp_path / "persona_data",
            session_id="400",
            persona_name="persona_a",
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
                session_resolution=type("S", (), {"session_id": "400"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")
        assert "Loaded Persona (persona_a)" in extended_prompt
        assert "You are persona A." in extended_prompt

        query = "@persona_b help me"
        mention_result = parse_persona_mention(query)
        resolved_name = resolve_persona_name(
            mention_result.persona_identifier,
            kvstore,
            tmp_path / "persona_data",
        )

        set_session_binding(
            tmp_path / "persona_data",
            session_id="400",
            persona_name=resolved_name,
        )

        hooks.invoke(
            "SESSION_RESOLVED",
            SessionResolvedContext(
                request=None,
                session_manager=None,
                session_resolution=type("S", (), {"session_id": "400"})(),
            ),
        )

        extended_prompt = hooks.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")
        assert "Loaded Persona (persona_b)" in extended_prompt
        assert "You are persona B." in extended_prompt
        assert "persona_a" not in extended_prompt

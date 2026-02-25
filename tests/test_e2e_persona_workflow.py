"""End-to-end integration tests for persona workflow.

Tests complete workflows including:
- Create persona → load via mention → query with persona
- Alias workflow: create alias → load via alias mention
- Session persistence across multiple queries
- Import/export round-trip
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.cli.mention_parser import parse_persona_mention
from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    list_persona_names,
    persona_exists,
    read_chunks,
    read_metadata,
    read_prompt,
)
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.resolver import (
    resolve_persona_name,
    set_persona_alias,
)
from asky.plugins.persona_manager.session_binding import (
    get_session_binding,
    set_session_binding,
)


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
def mock_session():
    """Mock session for testing."""
    session = MagicMock()
    session.id = 1
    session.name = "test-session"
    return session


class TestCompletePersonaWorkflow:
    """Test complete workflow: create → load via mention → query."""
    
    def test_create_persona_then_load_via_mention(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test creating a persona and loading it via @mention."""
        persona_name = "test-developer"
        behavior_prompt = "You are a helpful software developer assistant."
        description = "Developer persona for testing"
        
        paths = create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description=description,
            behavior_prompt=behavior_prompt,
        )
        
        assert paths.root_dir.exists()
        assert paths.metadata_path.exists()
        assert paths.prompt_path.exists()
        assert paths.chunks_path.exists()
        
        assert persona_exists(temp_data_dir, persona_name)
        
        query = f"@{persona_name} how do I optimize this code?"
        result = parse_persona_mention(query)
        
        assert result.has_mention
        assert result.persona_identifier == persona_name
        assert result.cleaned_query == "how do I optimize this code?"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == persona_name
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == persona_name
        
        loaded_prompt = read_prompt(paths.prompt_path)
        assert loaded_prompt == behavior_prompt
    
    def test_create_multiple_personas_and_switch_between_them(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test creating multiple personas and switching between them."""
        create_persona(
            data_dir=temp_data_dir,
            persona_name="developer",
            description="Developer persona",
            behavior_prompt="You are a software developer.",
        )
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name="writer",
            description="Writer persona",
            behavior_prompt="You are a content writer.",
        )
        
        personas = list_persona_names(temp_data_dir)
        assert "developer" in personas
        assert "writer" in personas
        
        query1 = "@developer help with code"
        result1 = parse_persona_mention(query1)
        resolved1 = resolve_persona_name(result1.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved1)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == "developer"
        
        query2 = "@writer help with article"
        result2 = parse_persona_mention(query2)
        resolved2 = resolve_persona_name(result2.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved2)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == "writer"


class TestAliasWorkflow:
    """Test alias workflow: create alias → load via alias mention."""
    
    def test_create_alias_and_load_via_alias(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test creating an alias and loading persona via alias mention."""
        persona_name = "software-engineer"
        alias = "dev"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Software engineer persona",
            behavior_prompt="You are an experienced software engineer.",
        )
        
        set_persona_alias(alias, persona_name, kvstore, temp_data_dir)
        
        query = f"@{alias} optimize this function"
        result = parse_persona_mention(query)
        
        assert result.has_mention
        assert result.persona_identifier == alias
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == persona_name
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == persona_name
    
    def test_multiple_aliases_for_same_persona(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test creating multiple aliases for the same persona."""
        persona_name = "content-creator"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Content creator persona",
            behavior_prompt="You are a creative content creator.",
        )
        
        set_persona_alias("writer", persona_name, kvstore, temp_data_dir)
        set_persona_alias("creator", persona_name, kvstore, temp_data_dir)
        set_persona_alias("author", persona_name, kvstore, temp_data_dir)
        
        for alias in ["writer", "creator", "author"]:
            query = f"@{alias} help me"
            result = parse_persona_mention(query)
            resolved = resolve_persona_name(result.persona_identifier, kvstore, temp_data_dir)
            assert resolved == persona_name
    
    def test_alias_workflow_with_session_persistence(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test that alias-loaded persona persists in session."""
        persona_name = "data-scientist"
        alias = "ds"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Data scientist persona",
            behavior_prompt="You are a data scientist.",
        )
        
        set_persona_alias(alias, persona_name, kvstore, temp_data_dir)
        
        query = f"@{alias} analyze this data"
        result = parse_persona_mention(query)
        resolved = resolve_persona_name(result.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved)
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == persona_name
        
        query2 = "what about this other dataset?"
        result2 = parse_persona_mention(query2)
        assert not result2.has_mention
        
        bound_persona_after = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona_after == persona_name


class TestSessionPersistence:
    """Test session persistence across multiple queries."""
    
    def test_persona_persists_across_queries(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test that persona binding persists across multiple queries."""
        persona_name = "assistant"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="General assistant",
            behavior_prompt="You are a helpful assistant.",
        )
        
        query1 = f"@{persona_name} help me with task 1"
        result1 = parse_persona_mention(query1)
        resolved1 = resolve_persona_name(result1.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved1)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == persona_name
        
        query2 = "now help me with task 2"
        result2 = parse_persona_mention(query2)
        assert not result2.has_mention
        
        assert get_session_binding(temp_data_dir, mock_session.id) == persona_name
        
        query3 = "and finally task 3"
        result3 = parse_persona_mention(query3)
        assert not result3.has_mention
        
        assert get_session_binding(temp_data_dir, mock_session.id) == persona_name
    
    def test_persona_persists_until_explicitly_changed(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test that persona persists until explicitly changed or unloaded."""
        create_persona(
            data_dir=temp_data_dir,
            persona_name="persona-a",
            description="Persona A",
            behavior_prompt="You are persona A.",
        )
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name="persona-b",
            description="Persona B",
            behavior_prompt="You are persona B.",
        )
        
        query1 = "@persona-a first query"
        result1 = parse_persona_mention(query1)
        resolved1 = resolve_persona_name(result1.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved1)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == "persona-a"
        
        for _ in range(5):
            query = "another query without mention"
            result = parse_persona_mention(query)
            assert not result.has_mention
            assert get_session_binding(temp_data_dir, mock_session.id) == "persona-a"
        
        query2 = "@persona-b switch to persona B"
        result2 = parse_persona_mention(query2)
        resolved2 = resolve_persona_name(result2.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved2)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == "persona-b"
    
    def test_unload_persona_clears_binding(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        mock_session,
    ):
        """Test that unloading persona clears session binding."""
        persona_name = "temporary-persona"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Temporary persona",
            behavior_prompt="You are a temporary persona.",
        )
        
        query = f"@{persona_name} help me"
        result = parse_persona_mention(query)
        resolved = resolve_persona_name(result.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=resolved)
        
        assert get_session_binding(temp_data_dir, mock_session.id) == persona_name
        
        set_session_binding(temp_data_dir, session_id=mock_session.id, persona_name=None)
        
        assert get_session_binding(temp_data_dir, mock_session.id) is None
    
    def test_different_sessions_have_independent_bindings(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
    ):
        """Test that different sessions maintain independent persona bindings."""
        session1 = MagicMock()
        session1.id = 1
        
        session2 = MagicMock()
        session2.id = 2
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name="persona-x",
            description="Persona X",
            behavior_prompt="You are persona X.",
        )
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name="persona-y",
            description="Persona Y",
            behavior_prompt="You are persona Y.",
        )
        
        set_session_binding(temp_data_dir, session_id=session1.id, persona_name="persona-x")
        set_session_binding(temp_data_dir, session_id=session2.id, persona_name="persona-y")
        
        assert get_session_binding(temp_data_dir, session1.id) == "persona-x"
        assert get_session_binding(temp_data_dir, session2.id) == "persona-y"
        
        set_session_binding(temp_data_dir, session_id=session1.id, persona_name=None)
        
        assert get_session_binding(temp_data_dir, session1.id) is None
        assert get_session_binding(temp_data_dir, session2.id) == "persona-y"


class TestImportExportRoundTrip:
    """Test import/export round-trip functionality."""
    
    def test_export_then_import_preserves_persona(
        self,
        temp_data_dir: Path,
        tmp_path: Path,
    ):
        """Test that exporting and importing a persona preserves all data."""
        persona_name = "export-test-persona"
        behavior_prompt = "You are a test persona for export/import."
        description = "Test persona for round-trip testing"
        
        paths = create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description=description,
            behavior_prompt=behavior_prompt,
        )
        
        original_metadata = read_metadata(paths.metadata_path)
        original_prompt = read_prompt(paths.prompt_path)
        original_chunks = read_chunks(paths.chunks_path)
        
        export_path = tmp_path / "export"
        export_path.mkdir()
        
        archive_path = export_persona_package(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            output_path=str(export_path / f"{persona_name}.zip"),
        )
        
        assert Path(archive_path).exists()
        assert Path(archive_path).suffix == ".zip"
        
        with zipfile.ZipFile(archive_path, 'r') as zf:
            namelist = zf.namelist()
            assert "metadata.toml" in namelist
            assert "behavior_prompt.md" in namelist
            assert "chunks.json" in namelist
        
        import_data_dir = tmp_path / "import_data"
        import_data_dir.mkdir()
        
        result = import_persona_archive(
            data_dir=import_data_dir,
            archive_path=str(archive_path),
        )
        
        assert result["ok"]
        assert result["name"] == persona_name
        
        imported_paths = get_persona_paths(import_data_dir, persona_name)
        assert imported_paths.root_dir.exists()
        assert imported_paths.metadata_path.exists()
        assert imported_paths.prompt_path.exists()
        assert imported_paths.chunks_path.exists()
        
        imported_metadata = read_metadata(imported_paths.metadata_path)
        imported_prompt = read_prompt(imported_paths.prompt_path)
        imported_chunks = read_chunks(imported_paths.chunks_path)
        
        assert imported_metadata["persona"]["description"] == original_metadata["persona"]["description"]
        assert imported_prompt == original_prompt
        assert len(imported_chunks) == len(original_chunks)
    
    def test_export_import_with_chunks(
        self,
        temp_data_dir: Path,
        tmp_path: Path,
    ):
        """Test export/import with knowledge chunks."""
        persona_name = "chunked-persona"
        
        paths = create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Persona with chunks",
            behavior_prompt="You are a persona with knowledge chunks.",
        )
        
        from asky.plugins.manual_persona_creator.storage import write_chunks
        
        test_chunks = [
            {"text": "Chunk 1 content", "source": "test1.txt"},
            {"text": "Chunk 2 content", "source": "test2.txt"},
            {"text": "Chunk 3 content", "source": "test3.txt"},
        ]
        write_chunks(paths.chunks_path, test_chunks)
        
        export_path = tmp_path / "export"
        export_path.mkdir()
        
        archive_path = export_persona_package(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            output_path=str(export_path / f"{persona_name}.zip"),
        )
        
        import_data_dir = tmp_path / "import_data"
        import_data_dir.mkdir()
        
        result = import_persona_archive(
            data_dir=import_data_dir,
            archive_path=str(archive_path),
        )
        
        assert result["ok"]
        assert result["chunks"] == len(test_chunks)
        
        imported_paths = get_persona_paths(import_data_dir, persona_name)
        imported_chunks = read_chunks(imported_paths.chunks_path)
        
        assert len(imported_chunks) == len(test_chunks)
        for original, imported in zip(test_chunks, imported_chunks):
            assert imported["text"] == original["text"]
    
    def test_export_import_multiple_personas(
        self,
        temp_data_dir: Path,
        tmp_path: Path,
    ):
        """Test exporting and importing multiple personas."""
        personas = [
            ("persona-1", "First persona", "You are persona 1."),
            ("persona-2", "Second persona", "You are persona 2."),
            ("persona-3", "Third persona", "You are persona 3."),
        ]
        
        export_path = tmp_path / "export"
        export_path.mkdir()
        
        archive_paths = []
        for name, desc, prompt in personas:
            create_persona(
                data_dir=temp_data_dir,
                persona_name=name,
                description=desc,
                behavior_prompt=prompt,
            )
            
            archive = export_persona_package(
                data_dir=temp_data_dir,
                persona_name=name,
                output_path=str(export_path / f"{name}.zip"),
            )
            archive_paths.append(archive)
        
        import_data_dir = tmp_path / "import_data"
        import_data_dir.mkdir()
        
        for archive_path in archive_paths:
            result = import_persona_archive(
                data_dir=import_data_dir,
                archive_path=str(archive_path),
            )
            assert result["ok"]
        
        imported_personas = list_persona_names(import_data_dir)
        assert len(imported_personas) == len(personas)
        
        for name, desc, prompt in personas:
            assert name in imported_personas
            paths = get_persona_paths(import_data_dir, name)
            imported_prompt = read_prompt(paths.prompt_path)
            assert imported_prompt == prompt


class TestCompleteEndToEndScenario:
    """Test complete end-to-end scenarios combining all features."""
    
    def test_full_workflow_with_all_features(
        self,
        temp_data_dir: Path,
        tmp_path: Path,
        kvstore: PluginKVStore,
    ):
        """Test complete workflow: create, alias, export, import, load, persist."""
        session1 = MagicMock()
        session1.id = 1
        
        session2 = MagicMock()
        session2.id = 2
        
        persona_name = "full-workflow-persona"
        alias = "fwp"
        
        create_persona(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            description="Full workflow test persona",
            behavior_prompt="You are a full workflow test persona.",
        )
        
        set_persona_alias(alias, persona_name, kvstore, temp_data_dir)
        
        query1 = f"@{alias} first query"
        result1 = parse_persona_mention(query1)
        resolved1 = resolve_persona_name(result1.persona_identifier, kvstore, temp_data_dir)
        set_session_binding(temp_data_dir, session_id=session1.id, persona_name=resolved1)
        
        assert get_session_binding(temp_data_dir, session1.id) == persona_name
        
        for i in range(3):
            query = f"query {i+2} without mention"
            result = parse_persona_mention(query)
            assert not result.has_mention
            assert get_session_binding(temp_data_dir, session1.id) == persona_name
        
        export_path = tmp_path / "export"
        export_path.mkdir()
        
        archive_path = export_persona_package(
            data_dir=temp_data_dir,
            persona_name=persona_name,
            output_path=str(export_path / f"{persona_name}.zip"),
        )
        
        import_data_dir = tmp_path / "import_data"
        import_data_dir.mkdir()
        
        result = import_persona_archive(
            data_dir=import_data_dir,
            archive_path=str(archive_path),
        )
        assert result["ok"]
        
        kvstore2 = PluginKVStore("persona_manager", db_path=tmp_path / "test2.db")
        set_persona_alias(alias, persona_name, kvstore2, import_data_dir)
        
        query2 = f"@{alias} query in new environment"
        result2 = parse_persona_mention(query2)
        resolved2 = resolve_persona_name(result2.persona_identifier, kvstore2, import_data_dir)
        set_session_binding(import_data_dir, session_id=session2.id, persona_name=resolved2)
        
        assert get_session_binding(import_data_dir, session2.id) == persona_name
        
        assert get_session_binding(temp_data_dir, session1.id) == persona_name
        assert get_session_binding(import_data_dir, session2.id) == persona_name

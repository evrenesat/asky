"""Tests for CLI persona command handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    persona_exists,
)
from asky.cli.persona_commands import (
    handle_persona_alias,
    handle_persona_aliases,
    handle_persona_create,
    handle_persona_current,
    handle_persona_export,
    handle_persona_import,
    handle_persona_list,
    handle_persona_load,
    handle_persona_unload,
    handle_persona_unalias,
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
def sample_personas(temp_data_dir: Path):
    """Create sample personas for testing."""
    create_persona(
        data_dir=temp_data_dir,
        persona_name="developer",
        description="Software developer persona",
        behavior_prompt="You are a helpful software developer.",
    )
    
    create_persona(
        data_dir=temp_data_dir,
        persona_name="writer",
        description="Content writer persona",
        behavior_prompt="You are a creative content writer.",
    )


@pytest.fixture
def mock_session():
    """Mock session for testing session-dependent commands."""
    session = MagicMock()
    session.id = 1
    session.name = "test-session"
    return session


# Test persona create command


def test_handle_persona_create_success(temp_data_dir: Path, tmp_path: Path):
    """Test successfully creating a persona."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("You are a test persona.")
    
    args = argparse.Namespace(
        name="test-persona",
        prompt=str(prompt_file),
        description="Test description",
    )
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_create(args)
    
    assert persona_exists(temp_data_dir, "test-persona")


def test_handle_persona_create_empty_name(temp_data_dir: Path, tmp_path: Path):
    """Test creating persona with empty name fails."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("You are a test persona.")
    
    args = argparse.Namespace(
        name="",
        prompt=str(prompt_file),
        description="Test description",
    )
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_create(args)
    
    # Should not create any persona
    from asky.plugins.manual_persona_creator.storage import list_persona_names
    assert list_persona_names(temp_data_dir) == []


def test_handle_persona_create_nonexistent_prompt_file(temp_data_dir: Path):
    """Test creating persona with non-existent prompt file fails."""
    args = argparse.Namespace(
        name="test-persona",
        prompt="/nonexistent/prompt.md",
        description="Test description",
    )
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_create(args)
    
    assert not persona_exists(temp_data_dir, "test-persona")


def test_handle_persona_create_duplicate_name(temp_data_dir: Path, tmp_path: Path, sample_personas):
    """Test creating persona with duplicate name fails."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("You are a test persona.")
    
    args = argparse.Namespace(
        name="developer",
        prompt=str(prompt_file),
        description="Test description",
    )
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_create(args)
    
    # Should still only have the original persona
    from asky.plugins.manual_persona_creator.storage import list_persona_names
    assert "developer" in list_persona_names(temp_data_dir)


# Test persona load command


def test_handle_persona_load_success(temp_data_dir: Path, sample_personas, mock_session):
    """Test successfully loading a persona."""
    args = argparse.Namespace(name="developer")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1), \
         patch("asky.cli.persona_commands.get_session_by_id", return_value=mock_session):
        handle_persona_load(args)
    
    from asky.plugins.persona_manager.session_binding import get_session_binding
    assert get_session_binding(temp_data_dir, 1) == "developer"


def test_handle_persona_load_nonexistent_persona(temp_data_dir: Path, sample_personas, mock_session):
    """Test loading non-existent persona fails."""
    args = argparse.Namespace(name="nonexistent")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1), \
         patch("asky.cli.persona_commands.get_session_by_id", return_value=mock_session):
        handle_persona_load(args)
    
    from asky.plugins.persona_manager.session_binding import get_session_binding
    assert get_session_binding(temp_data_dir, 1) is None


def test_handle_persona_load_no_active_session(temp_data_dir: Path, sample_personas):
    """Test loading persona without active session fails."""
    args = argparse.Namespace(name="developer")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=None):
        handle_persona_load(args)
    
    # Should not create any binding
    from asky.plugins.persona_manager.session_binding import load_bindings
    assert load_bindings(temp_data_dir) == {}


def test_handle_persona_load_empty_name(temp_data_dir: Path, mock_session):
    """Test loading persona with empty name fails."""
    args = argparse.Namespace(name="")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1), \
         patch("asky.cli.persona_commands.get_session_by_id", return_value=mock_session):
        handle_persona_load(args)
    
    from asky.plugins.persona_manager.session_binding import get_session_binding
    assert get_session_binding(temp_data_dir, 1) is None


# Test persona unload command


def test_handle_persona_unload_success(temp_data_dir: Path, sample_personas, mock_session):
    """Test successfully unloading a persona."""
    # First load a persona
    from asky.plugins.persona_manager.session_binding import set_session_binding
    set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
    
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1):
        handle_persona_unload(args)
    
    from asky.plugins.persona_manager.session_binding import get_session_binding
    assert get_session_binding(temp_data_dir, 1) is None


def test_handle_persona_unload_no_persona_loaded(temp_data_dir: Path, mock_session):
    """Test unloading when no persona is loaded."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1):
        handle_persona_unload(args)
    
    # Should not raise error, just show message
    from asky.plugins.persona_manager.session_binding import get_session_binding
    assert get_session_binding(temp_data_dir, 1) is None


def test_handle_persona_unload_no_active_session(temp_data_dir: Path):
    """Test unloading without active session."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=None):
        handle_persona_unload(args)
    
    # Should not raise error
    from asky.plugins.persona_manager.session_binding import load_bindings
    assert load_bindings(temp_data_dir) == {}


# Test persona current command


def test_handle_persona_current_with_loaded_persona(temp_data_dir: Path, sample_personas):
    """Test displaying currently loaded persona."""
    from asky.plugins.persona_manager.session_binding import set_session_binding
    set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
    
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1):
        handle_persona_current(args)
    
    # Should display persona info without error


def test_handle_persona_current_no_persona_loaded(temp_data_dir: Path):
    """Test displaying current persona when none is loaded."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1):
        handle_persona_current(args)
    
    # Should display "no persona loaded" message without error


def test_handle_persona_current_no_active_session(temp_data_dir: Path):
    """Test displaying current persona without active session."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=None):
        handle_persona_current(args)
    
    # Should display "no active session" message without error


# Test persona list command


def test_handle_persona_list_with_personas(temp_data_dir: Path, sample_personas):
    """Test listing personas when personas exist."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_list(args)
    
    # Should display table without error


def test_handle_persona_list_empty(temp_data_dir: Path):
    """Test listing personas when none exist."""
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_list(args)
    
    # Should display "no personas" message without error


def test_handle_persona_list_shows_active_persona(temp_data_dir: Path, sample_personas):
    """Test that list command shows which persona is active."""
    from asky.plugins.persona_manager.session_binding import set_session_binding
    set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
    
    args = argparse.Namespace()
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.get_shell_session_id", return_value=1):
        handle_persona_list(args)
    
    # Should display table with active indicator


# Test persona alias command


def test_handle_persona_alias_success(temp_data_dir: Path, sample_personas, tmp_path: Path):
    """Test successfully creating an alias."""
    args = argparse.Namespace(alias="dev", persona_name="developer")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock the set_persona_alias to succeed
        with patch("asky.cli.persona_commands.set_persona_alias"):
            handle_persona_alias(args)


def test_handle_persona_alias_nonexistent_persona(temp_data_dir: Path, sample_personas):
    """Test creating alias for non-existent persona fails."""
    args = argparse.Namespace(alias="test", persona_name="nonexistent")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock set_persona_alias to raise ValueError
        with patch("asky.cli.persona_commands.set_persona_alias", side_effect=ValueError("Persona 'nonexistent' does not exist")):
            handle_persona_alias(args)


def test_handle_persona_alias_empty_alias(temp_data_dir: Path, sample_personas):
    """Test creating alias with empty name fails."""
    args = argparse.Namespace(alias="", persona_name="developer")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_alias(args)
    
    # Should display error message


def test_handle_persona_alias_empty_persona_name(temp_data_dir: Path):
    """Test creating alias with empty persona name fails."""
    args = argparse.Namespace(alias="dev", persona_name="")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_alias(args)
    
    # Should display error message


# Test persona unalias command


def test_handle_persona_unalias_success(temp_data_dir: Path, tmp_path: Path):
    """Test successfully removing an alias."""
    args = argparse.Namespace(alias="dev")
    
    with patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock remove_persona_alias to return True
        with patch("asky.cli.persona_commands.remove_persona_alias", return_value=True):
            handle_persona_unalias(args)


def test_handle_persona_unalias_nonexistent_alias(temp_data_dir: Path):
    """Test removing non-existent alias."""
    args = argparse.Namespace(alias="nonexistent")
    
    with patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock remove_persona_alias to return False
        with patch("asky.cli.persona_commands.remove_persona_alias", return_value=False):
            handle_persona_unalias(args)


def test_handle_persona_unalias_empty_alias(temp_data_dir: Path):
    """Test removing alias with empty name."""
    args = argparse.Namespace(alias="")
    
    with patch("asky.cli.persona_commands.PluginKVStore"):
        handle_persona_unalias(args)
    
    # Should display error message


# Test persona aliases command


def test_handle_persona_aliases_all(temp_data_dir: Path, sample_personas):
    """Test listing all aliases."""
    args = argparse.Namespace(persona_name=None)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock list_all_aliases to return some aliases
        with patch("asky.cli.persona_commands.list_all_aliases", return_value=[("dev", "developer"), ("author", "writer")]):
            handle_persona_aliases(args)


def test_handle_persona_aliases_for_specific_persona(temp_data_dir: Path, sample_personas):
    """Test listing aliases for a specific persona."""
    args = argparse.Namespace(persona_name="developer")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock get_persona_aliases to return aliases
        with patch("asky.cli.persona_commands.get_persona_aliases", return_value=["dev", "coder"]):
            handle_persona_aliases(args)


def test_handle_persona_aliases_no_aliases(temp_data_dir: Path, sample_personas):
    """Test listing aliases when none exist."""
    args = argparse.Namespace(persona_name=None)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore") as mock_kvstore_class:
        mock_kvstore = MagicMock()
        mock_kvstore_class.return_value = mock_kvstore
        
        # Mock list_all_aliases to return empty list
        with patch("asky.cli.persona_commands.list_all_aliases", return_value=[]):
            handle_persona_aliases(args)


def test_handle_persona_aliases_nonexistent_persona(temp_data_dir: Path, sample_personas):
    """Test listing aliases for non-existent persona."""
    args = argparse.Namespace(persona_name="nonexistent")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.PluginKVStore"):
        handle_persona_aliases(args)
    
    # Should display error message


# Test persona import command


def test_handle_persona_import_zip_success(temp_data_dir: Path, tmp_path: Path):
    """Test successfully importing a persona from ZIP."""
    zip_file = tmp_path / "persona.zip"
    zip_file.touch()
    
    args = argparse.Namespace(path=str(zip_file))
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.import_persona_archive") as mock_import:
        mock_import.return_value = {
            "name": "imported-persona",
            "chunks": 10,
            "path": str(temp_data_dir / "personas" / "imported-persona"),
        }
        handle_persona_import(args)


def test_handle_persona_import_nonexistent_path(temp_data_dir: Path):
    """Test importing from non-existent path fails."""
    args = argparse.Namespace(path="/nonexistent/persona.zip")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_import(args)
    
    # Should display error message


def test_handle_persona_import_empty_path(temp_data_dir: Path):
    """Test importing with empty path fails."""
    args = argparse.Namespace(path="")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_import(args)
    
    # Should display error message


def test_handle_persona_import_invalid_archive(temp_data_dir: Path, tmp_path: Path):
    """Test importing invalid archive fails."""
    zip_file = tmp_path / "invalid.zip"
    zip_file.write_text("not a valid zip")
    
    args = argparse.Namespace(path=str(zip_file))
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.import_persona_archive", side_effect=ValueError("Invalid archive")):
        handle_persona_import(args)
    
    # Should display error message


# Test persona export command


def test_handle_persona_export_success(temp_data_dir: Path, sample_personas, tmp_path: Path):
    """Test successfully exporting a persona."""
    output_path = tmp_path / "export.zip"
    
    args = argparse.Namespace(name="developer", output=str(output_path))
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.export_persona_package") as mock_export:
        mock_export.return_value = str(output_path)
        handle_persona_export(args)


def test_handle_persona_export_nonexistent_persona(temp_data_dir: Path, sample_personas):
    """Test exporting non-existent persona fails."""
    args = argparse.Namespace(name="nonexistent", output=None)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_export(args)
    
    # Should display error message


def test_handle_persona_export_empty_name(temp_data_dir: Path):
    """Test exporting with empty name fails."""
    args = argparse.Namespace(name="", output=None)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_export(args)
    
    # Should display error message


def test_handle_persona_export_default_output(temp_data_dir: Path, sample_personas):
    """Test exporting with default output path."""
    args = argparse.Namespace(name="developer", output=None)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir), \
         patch("asky.cli.persona_commands.export_persona_package") as mock_export:
        mock_export.return_value = str(temp_data_dir / "developer.zip")
        handle_persona_export(args)

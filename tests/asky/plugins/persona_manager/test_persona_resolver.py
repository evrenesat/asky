"""Tests for persona resolver functionality."""

from pathlib import Path

import pytest

from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import create_persona
from asky.plugins.persona_manager.resolver import (
    get_persona_aliases,
    list_all_aliases,
    list_available_personas,
    remove_persona_alias,
    resolve_persona_name,
    set_persona_alias,
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
    
    create_persona(
        data_dir=temp_data_dir,
        persona_name="analyst",
        description="Data analyst persona",
        behavior_prompt="You are a data analyst.",
    )


def test_resolve_persona_by_direct_name(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test resolving persona by direct name match."""
    result = resolve_persona_name("developer", kvstore, temp_data_dir)
    assert result == "developer"


def test_resolve_persona_by_alias(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test resolving persona by alias."""
    kvstore.set("alias:dev", "developer")
    
    result = resolve_persona_name("dev", kvstore, temp_data_dir)
    assert result == "developer"


def test_resolve_nonexistent_persona(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test resolving non-existent persona returns None."""
    result = resolve_persona_name("nonexistent", kvstore, temp_data_dir)
    assert result is None


def test_resolve_empty_identifier(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test resolving empty identifier returns None."""
    assert resolve_persona_name("", kvstore, temp_data_dir) is None
    assert resolve_persona_name("   ", kvstore, temp_data_dir) is None


def test_resolve_alias_takes_precedence(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that alias resolution takes precedence over direct name match."""
    kvstore.set("alias:writer", "developer")
    
    result = resolve_persona_name("writer", kvstore, temp_data_dir)
    assert result == "developer"


def test_resolve_broken_alias_falls_back_to_direct(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that broken alias (pointing to non-existent persona) falls back to direct name."""
    kvstore.set("alias:writer", "nonexistent")
    
    result = resolve_persona_name("writer", kvstore, temp_data_dir)
    assert result == "writer"


def test_list_available_personas(temp_data_dir: Path, sample_personas):
    """Test listing all available personas."""
    personas = list_available_personas(temp_data_dir)
    assert sorted(personas) == ["analyst", "developer", "writer"]


def test_list_available_personas_empty(temp_data_dir: Path):
    """Test listing personas when none exist."""
    personas = list_available_personas(temp_data_dir)
    assert personas == []


def test_get_persona_aliases_single(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test getting aliases for a persona with one alias."""
    kvstore.set("alias:dev", "developer")
    
    aliases = get_persona_aliases("developer", kvstore)
    assert aliases == ["dev"]


def test_get_persona_aliases_multiple(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test getting aliases for a persona with multiple aliases."""
    kvstore.set("alias:dev", "developer")
    kvstore.set("alias:coder", "developer")
    kvstore.set("alias:programmer", "developer")
    
    aliases = get_persona_aliases("developer", kvstore)
    assert sorted(aliases) == ["coder", "dev", "programmer"]


def test_get_persona_aliases_none(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test getting aliases for a persona with no aliases."""
    aliases = get_persona_aliases("developer", kvstore)
    assert aliases == []


def test_get_persona_aliases_filters_other_personas(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that get_persona_aliases only returns aliases for the specified persona."""
    kvstore.set("alias:dev", "developer")
    kvstore.set("alias:author", "writer")
    
    aliases = get_persona_aliases("developer", kvstore)
    assert aliases == ["dev"]


def test_set_persona_alias_success(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test successfully setting a persona alias."""
    set_persona_alias("dev", "developer", kvstore, temp_data_dir)
    
    assert kvstore.get("alias:dev") == "developer"


def test_set_persona_alias_nonexistent_persona(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that setting alias for non-existent persona raises error."""
    with pytest.raises(ValueError, match="Persona 'nonexistent' does not exist"):
        set_persona_alias("alias", "nonexistent", kvstore, temp_data_dir)


def test_set_persona_alias_conflicts_with_persona_name(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that alias conflicting with existing persona name raises error."""
    from asky.plugins.persona_manager.errors import InvalidAliasError
    
    with pytest.raises(InvalidAliasError, match="conflicts with existing persona"):
        set_persona_alias("writer", "developer", kvstore, temp_data_dir)


def test_set_persona_alias_updates_existing(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that setting an existing alias updates it."""
    kvstore.set("alias:dev", "developer")
    set_persona_alias("dev", "writer", kvstore, temp_data_dir)
    
    assert kvstore.get("alias:dev") == "writer"


def test_remove_persona_alias_success(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test successfully removing a persona alias."""
    kvstore.set("alias:dev", "developer")
    
    result = remove_persona_alias("dev", kvstore)
    assert result is True
    assert kvstore.get("alias:dev") is None


def test_remove_persona_alias_nonexistent(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test removing non-existent alias returns False."""
    result = remove_persona_alias("nonexistent", kvstore)
    assert result is False


def test_list_all_aliases_empty(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test listing aliases when none exist."""
    aliases = list_all_aliases(kvstore)
    assert aliases == []


def test_list_all_aliases_single(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test listing a single alias."""
    kvstore.set("alias:dev", "developer")
    
    aliases = list_all_aliases(kvstore)
    assert aliases == [("dev", "developer")]


def test_list_all_aliases_multiple(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test listing multiple aliases."""
    kvstore.set("alias:dev", "developer")
    kvstore.set("alias:author", "writer")
    kvstore.set("alias:coder", "developer")
    
    aliases = list_all_aliases(kvstore)
    assert aliases == [
        ("author", "writer"),
        ("coder", "developer"),
        ("dev", "developer"),
    ]


def test_list_all_aliases_sorted(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test that aliases are returned in sorted order."""
    kvstore.set("alias:zebra", "developer")
    kvstore.set("alias:alpha", "writer")
    kvstore.set("alias:beta", "analyst")
    
    aliases = list_all_aliases(kvstore)
    assert [alias for alias, _ in aliases] == ["alpha", "beta", "zebra"]


def test_alias_precedence_in_resolution(temp_data_dir: Path, kvstore: PluginKVStore, sample_personas):
    """Test complete alias precedence workflow."""
    kvstore.set("alias:dev", "developer")
    
    assert resolve_persona_name("dev", kvstore, temp_data_dir) == "developer"
    assert resolve_persona_name("developer", kvstore, temp_data_dir) == "developer"
    
    kvstore.set("alias:developer", "writer")
    
    assert resolve_persona_name("developer", kvstore, temp_data_dir) == "writer"

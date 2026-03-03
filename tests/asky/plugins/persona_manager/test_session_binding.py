"""Unit tests for session binding persistence module."""

from pathlib import Path
from typing import Dict

import pytest

from asky.plugins.persona_manager.session_binding import (
    bindings_path,
    get_session_binding,
    load_bindings,
    save_bindings,
    set_session_binding,
)


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory for testing."""
    data_dir = tmp_path / "test_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class TestBindingsPath:
    """Tests for bindings_path function."""

    def test_bindings_path_returns_correct_path(self, temp_data_dir: Path):
        """Test that bindings_path returns the correct file path."""
        expected = temp_data_dir / "session_bindings.toml"
        actual = bindings_path(temp_data_dir)
        assert actual == expected


class TestLoadBindings:
    """Tests for load_bindings function."""

    def test_load_bindings_empty_when_file_not_exists(self, temp_data_dir: Path):
        """Test that load_bindings returns empty dict when file doesn't exist."""
        bindings = load_bindings(temp_data_dir)
        assert bindings == {}

    def test_load_bindings_reads_existing_file(self, temp_data_dir: Path):
        """Test that load_bindings reads existing bindings from file."""
        test_bindings = {"1": "developer", "2": "writer"}
        save_bindings(temp_data_dir, test_bindings)
        
        loaded = load_bindings(temp_data_dir)
        assert loaded == test_bindings

    def test_load_bindings_handles_empty_file(self, temp_data_dir: Path):
        """Test that load_bindings handles empty TOML file."""
        path = bindings_path(temp_data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        
        bindings = load_bindings(temp_data_dir)
        assert bindings == {}

    def test_load_bindings_filters_empty_values(self, temp_data_dir: Path):
        """Test that load_bindings filters out empty session IDs or persona names."""
        path = bindings_path(temp_data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[binding]\n"1" = "developer"\n"" = "writer"\n"2" = ""\n', encoding="utf-8")
        
        bindings = load_bindings(temp_data_dir)
        assert bindings == {"1": "developer"}


class TestSaveBindings:
    """Tests for save_bindings function."""

    def test_save_bindings_creates_file(self, temp_data_dir: Path):
        """Test that save_bindings creates the bindings file."""
        test_bindings = {"1": "developer"}
        save_bindings(temp_data_dir, test_bindings)
        
        path = bindings_path(temp_data_dir)
        assert path.exists()

    def test_save_bindings_creates_parent_directory(self, tmp_path: Path):
        """Test that save_bindings creates parent directory if it doesn't exist."""
        data_dir = tmp_path / "nested" / "dir" / "structure"
        test_bindings = {"1": "developer"}
        
        save_bindings(data_dir, test_bindings)
        
        path = bindings_path(data_dir)
        assert path.exists()
        assert path.parent.exists()

    def test_save_bindings_writes_correct_content(self, temp_data_dir: Path):
        """Test that save_bindings writes correct TOML content."""
        test_bindings = {"1": "developer", "2": "writer"}
        save_bindings(temp_data_dir, test_bindings)
        
        loaded = load_bindings(temp_data_dir)
        assert loaded == test_bindings

    def test_save_bindings_overwrites_existing(self, temp_data_dir: Path):
        """Test that save_bindings overwrites existing bindings."""
        save_bindings(temp_data_dir, {"1": "developer"})
        save_bindings(temp_data_dir, {"2": "writer"})
        
        loaded = load_bindings(temp_data_dir)
        assert loaded == {"2": "writer"}

    def test_save_bindings_atomic_write(self, temp_data_dir: Path):
        """Test that save_bindings uses atomic write (temp file then replace)."""
        test_bindings = {"1": "developer"}
        save_bindings(temp_data_dir, test_bindings)
        
        path = bindings_path(temp_data_dir)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        
        assert path.exists()
        assert not temp_path.exists()


class TestGetSessionBinding:
    """Tests for get_session_binding function."""

    def test_get_session_binding_returns_none_when_not_bound(self, temp_data_dir: Path):
        """Test that get_session_binding returns None when session has no binding."""
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_get_session_binding_returns_persona_name(self, temp_data_dir: Path):
        """Test that get_session_binding returns the bound persona name."""
        save_bindings(temp_data_dir, {"1": "developer"})
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "developer"

    def test_get_session_binding_handles_string_session_id(self, temp_data_dir: Path):
        """Test that get_session_binding works with string session IDs."""
        save_bindings(temp_data_dir, {"1": "developer"})
        
        result = get_session_binding(temp_data_dir, "1")
        assert result == "developer"

    def test_get_session_binding_handles_int_session_id(self, temp_data_dir: Path):
        """Test that get_session_binding works with integer session IDs."""
        save_bindings(temp_data_dir, {"1": "developer"})
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "developer"

    def test_get_session_binding_returns_none_for_empty_session_id(self, temp_data_dir: Path):
        """Test that get_session_binding returns None for empty session ID."""
        result = get_session_binding(temp_data_dir, "")
        assert result is None

    def test_get_session_binding_returns_none_for_none_session_id(self, temp_data_dir: Path):
        """Test that get_session_binding returns None for None session ID."""
        result = get_session_binding(temp_data_dir, None)
        assert result is None

    def test_get_session_binding_returns_none_for_whitespace_session_id(self, temp_data_dir: Path):
        """Test that get_session_binding returns None for whitespace-only session ID."""
        result = get_session_binding(temp_data_dir, "   ")
        assert result is None


class TestSetSessionBinding:
    """Tests for set_session_binding function."""

    def test_set_session_binding_creates_new_binding(self, temp_data_dir: Path):
        """Test that set_session_binding creates a new binding."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "developer"

    def test_set_session_binding_updates_existing_binding(self, temp_data_dir: Path):
        """Test that set_session_binding updates an existing binding."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="writer")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "writer"

    def test_set_session_binding_removes_binding_when_none(self, temp_data_dir: Path):
        """Test that set_session_binding removes binding when persona_name is None."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name=None)
        
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_set_session_binding_removes_binding_when_empty_string(self, temp_data_dir: Path):
        """Test that set_session_binding removes binding when persona_name is empty string."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_set_session_binding_removes_binding_when_whitespace(self, temp_data_dir: Path):
        """Test that set_session_binding removes binding when persona_name is whitespace."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="   ")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_set_session_binding_handles_string_session_id(self, temp_data_dir: Path):
        """Test that set_session_binding works with string session IDs."""
        set_session_binding(temp_data_dir, session_id="1", persona_name="developer")
        
        result = get_session_binding(temp_data_dir, "1")
        assert result == "developer"

    def test_set_session_binding_handles_int_session_id(self, temp_data_dir: Path):
        """Test that set_session_binding works with integer session IDs."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "developer"

    def test_set_session_binding_ignores_empty_session_id(self, temp_data_dir: Path):
        """Test that set_session_binding ignores empty session ID."""
        set_session_binding(temp_data_dir, session_id="", persona_name="developer")
        
        bindings = load_bindings(temp_data_dir)
        assert bindings == {}

    def test_set_session_binding_ignores_none_session_id(self, temp_data_dir: Path):
        """Test that set_session_binding ignores None session ID."""
        set_session_binding(temp_data_dir, session_id=None, persona_name="developer")
        
        bindings = load_bindings(temp_data_dir)
        assert bindings == {}

    def test_set_session_binding_ignores_whitespace_session_id(self, temp_data_dir: Path):
        """Test that set_session_binding ignores whitespace-only session ID."""
        set_session_binding(temp_data_dir, session_id="   ", persona_name="developer")
        
        bindings = load_bindings(temp_data_dir)
        assert bindings == {}

    def test_set_session_binding_preserves_other_bindings(self, temp_data_dir: Path):
        """Test that set_session_binding preserves other session bindings."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=2, persona_name="writer")
        
        assert get_session_binding(temp_data_dir, 1) == "developer"
        assert get_session_binding(temp_data_dir, 2) == "writer"

    def test_set_session_binding_removes_only_specified_binding(self, temp_data_dir: Path):
        """Test that set_session_binding removes only the specified binding."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=2, persona_name="writer")
        set_session_binding(temp_data_dir, session_id=1, persona_name=None)
        
        assert get_session_binding(temp_data_dir, 1) is None
        assert get_session_binding(temp_data_dir, 2) == "writer"


class TestPersonaBindingPersistence:
    """Tests for persona binding persistence across operations."""

    def test_binding_persists_across_load_operations(self, temp_data_dir: Path):
        """Test that binding persists when loading bindings multiple times."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        
        result1 = get_session_binding(temp_data_dir, 1)
        result2 = get_session_binding(temp_data_dir, 1)
        
        assert result1 == "developer"
        assert result2 == "developer"

    def test_binding_persists_after_other_session_changes(self, temp_data_dir: Path):
        """Test that binding persists when other sessions are modified."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=2, persona_name="writer")
        set_session_binding(temp_data_dir, session_id=2, persona_name="editor")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "developer"


class TestPersonaReplacement:
    """Tests for persona replacement functionality."""

    def test_persona_replacement_updates_binding(self, temp_data_dir: Path):
        """Test that loading a new persona replaces the existing binding."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="writer")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "writer"

    def test_persona_replacement_multiple_times(self, temp_data_dir: Path):
        """Test that persona can be replaced multiple times."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="writer")
        set_session_binding(temp_data_dir, session_id=1, persona_name="editor")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "editor"


class TestPersonaUnbinding:
    """Tests for persona unbinding functionality."""

    def test_unbinding_clears_binding(self, temp_data_dir: Path):
        """Test that unbinding clears the persona binding."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name=None)
        
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_unbinding_nonexistent_binding_is_safe(self, temp_data_dir: Path):
        """Test that unbinding a non-existent binding doesn't cause errors."""
        set_session_binding(temp_data_dir, session_id=1, persona_name=None)
        
        result = get_session_binding(temp_data_dir, 1)
        assert result is None

    def test_unbinding_allows_rebinding(self, temp_data_dir: Path):
        """Test that after unbinding, a new persona can be bound."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        set_session_binding(temp_data_dir, session_id=1, persona_name=None)
        set_session_binding(temp_data_dir, session_id=1, persona_name="writer")
        
        result = get_session_binding(temp_data_dir, 1)
        assert result == "writer"


class TestCrossQueryPersistence:
    """Tests for persona binding persistence across multiple queries."""

    def test_binding_persists_across_multiple_get_operations(self, temp_data_dir: Path):
        """Test that binding persists across multiple get operations (simulating queries)."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        
        results = [get_session_binding(temp_data_dir, 1) for _ in range(5)]
        
        assert all(result == "developer" for result in results)

    def test_binding_persists_with_interleaved_operations(self, temp_data_dir: Path):
        """Test that binding persists with interleaved operations on different sessions."""
        set_session_binding(temp_data_dir, session_id=1, persona_name="developer")
        
        get_session_binding(temp_data_dir, 1)
        set_session_binding(temp_data_dir, session_id=2, persona_name="writer")
        get_session_binding(temp_data_dir, 2)
        result = get_session_binding(temp_data_dir, 1)
        
        assert result == "developer"

"""Tests for plugin KVStore functionality."""

import json
import sqlite3
from pathlib import Path

import pytest

from asky.plugins.kvstore import MAX_KEY_LENGTH, MAX_VALUE_SIZE_BYTES, PluginKVStore


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path for testing."""
    return tmp_path / "test.db"


@pytest.fixture
def kvstore(temp_db: Path) -> PluginKVStore:
    """Create a KVStore instance for testing."""
    return PluginKVStore("test_plugin", db_path=temp_db)


def test_kvstore_initialization_creates_table(temp_db: Path):
    """Test that KVStore initialization creates the required table."""
    store = PluginKVStore("test_plugin", db_path=temp_db)
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='plugin_kvstore'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_kvstore_requires_plugin_name(temp_db: Path):
    """Test that KVStore requires a non-empty plugin name."""
    with pytest.raises(ValueError, match="plugin_name cannot be empty"):
        PluginKVStore("", db_path=temp_db)
    
    with pytest.raises(ValueError, match="plugin_name cannot be empty"):
        PluginKVStore("   ", db_path=temp_db)


def test_set_and_get_string(kvstore: PluginKVStore):
    """Test storing and retrieving string values."""
    kvstore.set("key1", "value1")
    assert kvstore.get("key1") == "value1"


def test_set_and_get_integer(kvstore: PluginKVStore):
    """Test storing and retrieving integer values."""
    kvstore.set("count", 42)
    assert kvstore.get("count") == 42


def test_set_and_get_float(kvstore: PluginKVStore):
    """Test storing and retrieving float values."""
    kvstore.set("pi", 3.14159)
    assert kvstore.get("pi") == 3.14159


def test_set_and_get_boolean(kvstore: PluginKVStore):
    """Test storing and retrieving boolean values."""
    kvstore.set("enabled", True)
    assert kvstore.get("enabled") is True
    
    kvstore.set("disabled", False)
    assert kvstore.get("disabled") is False


def test_set_and_get_dict(kvstore: PluginKVStore):
    """Test storing and retrieving dictionary values."""
    data = {"name": "test", "count": 5, "nested": {"key": "value"}}
    kvstore.set("config", data)
    assert kvstore.get("config") == data


def test_set_and_get_list(kvstore: PluginKVStore):
    """Test storing and retrieving list values."""
    data = [1, 2, "three", {"four": 4}]
    kvstore.set("items", data)
    assert kvstore.get("items") == data


def test_set_and_get_none(kvstore: PluginKVStore):
    """Test storing and retrieving None values."""
    kvstore.set("empty", None)
    assert kvstore.get("empty") is None


def test_get_nonexistent_key_returns_default(kvstore: PluginKVStore):
    """Test that getting a non-existent key returns the default value."""
    assert kvstore.get("nonexistent") is None
    assert kvstore.get("nonexistent", "default") == "default"
    assert kvstore.get("nonexistent", 42) == 42


def test_set_updates_existing_key(kvstore: PluginKVStore):
    """Test that setting an existing key updates the value."""
    kvstore.set("key", "value1")
    assert kvstore.get("key") == "value1"
    
    kvstore.set("key", "value2")
    assert kvstore.get("key") == "value2"


def test_set_updates_value_type(kvstore: PluginKVStore):
    """Test that setting a key with a different type updates correctly."""
    kvstore.set("key", "string")
    assert kvstore.get("key") == "string"
    
    kvstore.set("key", 123)
    assert kvstore.get("key") == 123
    
    kvstore.set("key", {"dict": "value"})
    assert kvstore.get("key") == {"dict": "value"}


def test_delete_existing_key(kvstore: PluginKVStore):
    """Test deleting an existing key."""
    kvstore.set("key", "value")
    assert kvstore.get("key") == "value"
    
    result = kvstore.delete("key")
    assert result is True
    assert kvstore.get("key") is None


def test_delete_nonexistent_key(kvstore: PluginKVStore):
    """Test deleting a non-existent key returns False."""
    result = kvstore.delete("nonexistent")
    assert result is False


def test_list_keys_empty(kvstore: PluginKVStore):
    """Test listing keys when store is empty."""
    assert kvstore.list_keys() == []


def test_list_keys_returns_all_keys(kvstore: PluginKVStore):
    """Test listing all keys."""
    kvstore.set("key1", "value1")
    kvstore.set("key2", "value2")
    kvstore.set("key3", "value3")
    
    keys = kvstore.list_keys()
    assert sorted(keys) == ["key1", "key2", "key3"]


def test_list_keys_with_prefix(kvstore: PluginKVStore):
    """Test listing keys with a prefix filter."""
    kvstore.set("alias:dev", "developer")
    kvstore.set("alias:prod", "production")
    kvstore.set("config:timeout", "30")
    kvstore.set("config:retries", "3")
    
    alias_keys = kvstore.list_keys(prefix="alias:")
    assert sorted(alias_keys) == ["alias:dev", "alias:prod"]
    
    config_keys = kvstore.list_keys(prefix="config:")
    assert sorted(config_keys) == ["config:retries", "config:timeout"]


def test_clear_removes_all_keys(kvstore: PluginKVStore):
    """Test clearing all keys for a plugin."""
    kvstore.set("key1", "value1")
    kvstore.set("key2", "value2")
    kvstore.set("key3", "value3")
    
    count = kvstore.clear()
    assert count == 3
    assert kvstore.list_keys() == []


def test_clear_empty_store(kvstore: PluginKVStore):
    """Test clearing an empty store returns 0."""
    count = kvstore.clear()
    assert count == 0


def test_plugin_isolation(temp_db: Path):
    """Test that different plugins have isolated key spaces."""
    store1 = PluginKVStore("plugin1", db_path=temp_db)
    store2 = PluginKVStore("plugin2", db_path=temp_db)
    
    store1.set("key", "value1")
    store2.set("key", "value2")
    
    assert store1.get("key") == "value1"
    assert store2.get("key") == "value2"
    
    assert store1.list_keys() == ["key"]
    assert store2.list_keys() == ["key"]
    
    store1.delete("key")
    assert store1.get("key") is None
    assert store2.get("key") == "value2"


def test_key_length_validation(kvstore: PluginKVStore):
    """Test that keys exceeding max length are rejected."""
    valid_key = "a" * MAX_KEY_LENGTH
    kvstore.set(valid_key, "value")
    assert kvstore.get(valid_key) == "value"
    
    invalid_key = "a" * (MAX_KEY_LENGTH + 1)
    with pytest.raises(ValueError, match="Key length .* exceeds maximum"):
        kvstore.set(invalid_key, "value")


def test_empty_key_validation(kvstore: PluginKVStore):
    """Test that empty keys are rejected."""
    with pytest.raises(ValueError, match="Key cannot be empty"):
        kvstore.set("", "value")
    
    with pytest.raises(ValueError, match="Key cannot be empty"):
        kvstore.set("   ", "value")
    
    with pytest.raises(ValueError, match="Key cannot be empty"):
        kvstore.get("")
    
    with pytest.raises(ValueError, match="Key cannot be empty"):
        kvstore.delete("")


def test_value_size_limit(kvstore: PluginKVStore):
    """Test that values exceeding max size are rejected."""
    large_value = "x" * (MAX_VALUE_SIZE_BYTES + 1)
    
    with pytest.raises(ValueError, match="Value size exceeds maximum"):
        kvstore.set("key", large_value)


def test_unsupported_value_type(kvstore: PluginKVStore):
    """Test that unsupported value types are rejected."""
    class CustomClass:
        pass
    
    with pytest.raises(TypeError, match="Unsupported value type"):
        kvstore.set("key", CustomClass())
    
    with pytest.raises(TypeError, match="Unsupported value type"):
        kvstore.set("key", object())


def test_json_serialization_roundtrip(kvstore: PluginKVStore):
    """Test that complex JSON structures survive serialization."""
    complex_data = {
        "string": "value",
        "number": 42,
        "float": 3.14,
        "bool": True,
        "null": None,
        "list": [1, 2, 3],
        "nested": {
            "deep": {
                "value": "here"
            }
        }
    }
    
    kvstore.set("complex", complex_data)
    retrieved = kvstore.get("complex")
    
    assert retrieved == complex_data
    assert isinstance(retrieved["string"], str)
    assert isinstance(retrieved["number"], int)
    assert isinstance(retrieved["float"], float)
    assert isinstance(retrieved["bool"], bool)
    assert retrieved["null"] is None


def test_timestamps_are_set(temp_db: Path, kvstore: PluginKVStore):
    """Test that created_at and updated_at timestamps are set."""
    kvstore.set("key", "value")
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT created_at, updated_at FROM plugin_kvstore WHERE plugin_name = ? AND key = ?",
        ("test_plugin", "key"),
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    created_at, updated_at = row
    assert created_at is not None
    assert updated_at is not None
    assert created_at == updated_at


def test_updated_at_changes_on_update(temp_db: Path, kvstore: PluginKVStore):
    """Test that updated_at timestamp changes when value is updated."""
    kvstore.set("key", "value1")
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT created_at, updated_at FROM plugin_kvstore WHERE plugin_name = ? AND key = ?",
        ("test_plugin", "key"),
    )
    row1 = cursor.fetchone()
    created_at1, updated_at1 = row1
    conn.close()
    
    kvstore.set("key", "value2")
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT created_at, updated_at FROM plugin_kvstore WHERE plugin_name = ? AND key = ?",
        ("test_plugin", "key"),
    )
    row2 = cursor.fetchone()
    conn.close()
    
    created_at2, updated_at2 = row2
    
    assert created_at1 == created_at2
    assert updated_at2 >= updated_at1

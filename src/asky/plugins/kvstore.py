"""Plugin key-value storage abstraction with SQLite backend."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from asky.config import DB_PATH

MAX_KEY_LENGTH = 256
MAX_VALUE_SIZE_BYTES = 1024 * 1024  # 1MB


class PluginKVStore:
    """
    Key-value storage for plugin configuration and user preferences.
    
    Storage is scoped per plugin and persisted in SQLite.
    All keys are automatically prefixed with the plugin name to prevent conflicts.
    """

    def __init__(self, plugin_name: str, db_path: Optional[Path] = None):
        """
        Initialize KVStore for a specific plugin.
        
        Args:
            plugin_name: Unique identifier for the plugin
            db_path: Optional custom database path (defaults to main asky DB)
        """
        if not plugin_name or not plugin_name.strip():
            raise ValueError("plugin_name cannot be empty")
        
        self.plugin_name = plugin_name.strip()
        self.db_path = db_path or DB_PATH
        self._ensure_table()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path)

    def _ensure_table(self) -> None:
        """Create the plugin_kvstore table if it doesn't exist."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS plugin_kvstore (
                plugin_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (plugin_name, key)
            )
            """
        )
        
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_plugin_kvstore_plugin
            ON plugin_kvstore(plugin_name)
            """
        )
        
        conn.commit()
        conn.close()

    def _validate_key(self, key: str) -> None:
        """Validate key format and length."""
        if not key or not key.strip():
            raise ValueError("Key cannot be empty")
        
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(
                f"Key length ({len(key)}) exceeds maximum ({MAX_KEY_LENGTH})"
            )

    def _serialize_value(self, value: Any) -> tuple[str, str]:
        """
        Serialize value to JSON string and determine type.
        
        Returns:
            Tuple of (serialized_value, value_type)
        """
        if value is None:
            return json.dumps(None), "null"
        elif isinstance(value, bool):
            return json.dumps(value), "boolean"
        elif isinstance(value, int):
            return json.dumps(value), "integer"
        elif isinstance(value, float):
            return json.dumps(value), "float"
        elif isinstance(value, str):
            return json.dumps(value), "string"
        elif isinstance(value, (dict, list)):
            return json.dumps(value), "json"
        else:
            raise TypeError(
                f"Unsupported value type: {type(value).__name__}. "
                "Supported types: str, int, float, bool, dict, list, None"
            )

    def _deserialize_value(self, serialized: str, value_type: str) -> Any:
        """Deserialize JSON string back to Python value."""
        return json.loads(serialized)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get value for key, return default if not found.
        
        Args:
            key: The key to retrieve
            default: Value to return if key doesn't exist
            
        Returns:
            The stored value or default
        """
        self._validate_key(key)
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            SELECT value, value_type FROM plugin_kvstore
            WHERE plugin_name = ? AND key = ?
            """,
            (self.plugin_name, key),
        )
        
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return default
        
        serialized_value, value_type = row
        return self._deserialize_value(serialized_value, value_type)

    def set(self, key: str, value: Any) -> None:
        """
        Set value for key. Value must be JSON-serializable.
        
        Args:
            key: The key to set
            value: The value to store (must be JSON-serializable)
            
        Raises:
            ValueError: If key is invalid or value exceeds size limit
            TypeError: If value type is not supported
        """
        self._validate_key(key)
        
        serialized_value, value_type = self._serialize_value(value)
        
        if len(serialized_value.encode('utf-8')) > MAX_VALUE_SIZE_BYTES:
            raise ValueError(
                f"Value size exceeds maximum ({MAX_VALUE_SIZE_BYTES} bytes)"
            )
        
        now = datetime.now().isoformat()
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO plugin_kvstore 
            (plugin_name, key, value, value_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(plugin_name, key) DO UPDATE
            SET value = excluded.value,
                value_type = excluded.value_type,
                updated_at = excluded.updated_at
            """,
            (self.plugin_name, key, serialized_value, value_type, now, now),
        )
        
        conn.commit()
        conn.close()

    def delete(self, key: str) -> bool:
        """
        Delete key. Returns True if key existed.
        
        Args:
            key: The key to delete
            
        Returns:
            True if the key was deleted, False if it didn't exist
        """
        self._validate_key(key)
        
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            DELETE FROM plugin_kvstore
            WHERE plugin_name = ? AND key = ?
            """,
            (self.plugin_name, key),
        )
        
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted

    def list_keys(self, prefix: Optional[str] = None) -> List[str]:
        """
        List all keys, optionally filtered by prefix.
        
        Args:
            prefix: Optional prefix to filter keys
            
        Returns:
            List of keys matching the criteria
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        if prefix:
            cursor.execute(
                """
                SELECT key FROM plugin_kvstore
                WHERE plugin_name = ? AND key LIKE ?
                ORDER BY key ASC
                """,
                (self.plugin_name, f"{prefix}%"),
            )
        else:
            cursor.execute(
                """
                SELECT key FROM plugin_kvstore
                WHERE plugin_name = ?
                ORDER BY key ASC
                """,
                (self.plugin_name,),
            )
        
        keys = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return keys

    def clear(self) -> int:
        """
        Clear all keys for this plugin. Returns count of deleted keys.
        
        Returns:
            Number of keys that were deleted
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            DELETE FROM plugin_kvstore
            WHERE plugin_name = ?
            """,
            (self.plugin_name,),
        )
        
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return count

import pytest
import sqlite3
import os
import json
from pathlib import Path

from tests.integration.cli_recorded.helpers import (
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def seed_memory(db_path: Path, memory_text: str, tags: list[str] = None):
    """Seed a memory record directly in the DB for setup."""
    tags_json = json.dumps(tags or [])
    # Ensure table exists first
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                memory_text TEXT NOT NULL,
                tags TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )
        conn.execute(
            "INSERT INTO user_memories (memory_text, tags, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            (memory_text, tags_json)
        )
        conn.commit()


def test_memory_surface_exhaustive():
    """Test all memory surface items in one sequence to ensure DB state consistency."""
    run_cli_inprocess(["history", "list"])
    db_path = Path(os.environ["ASKY_DB_PATH"])
    
    # 1. Seed and List
    seed_memory(db_path, "Exhaustive test memory.", ["test"])
    result_list = run_cli_inprocess(["memory", "list"])
    assert "exhaustive test memory" in normalize_cli_output(result_list.stdout).lower()

    # 2. Delete single
    result_del = run_cli_inprocess(["memory", "delete", "1"])
    assert "deleted memory 1" in normalize_cli_output(result_del.stdout).lower()
    
    # 3. Clear all
    seed_memory(db_path, "Memory to clear.", ["temp"])
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("builtins.input", lambda _: "y")
        result_clear = run_cli_inprocess(["memory", "clear"])
        assert "deleted" in normalize_cli_output(result_clear.stdout).lower()


def test_elephant_mode(request):
    """Test -em / --elephant-mode flag."""
    run_cli_inprocess(["-ss", "elephant_test"])
    run_cli_inprocess(["-rs", "elephant_test", "--elephant-mode", "-off", "all", "--shortlist", "off", "Just say apple."])
    
    result = run_cli_inprocess(["session", "show", "elephant_test"])
    assert result.exit_code == 0

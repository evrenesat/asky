"""Tests for the user memory feature."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.memory.store import (
    delete_all_memories_from_db,
    delete_memory_from_db,
    get_all_memories,
    get_memory_by_id,
    has_any_memories,
    init_memory_table,
    save_memory,
    update_memory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "mem_test.db"
    conn = sqlite3.connect(db)
    init_memory_table(conn.cursor())
    conn.commit()
    conn.close()
    return db


def _insert_with_embedding(db: Path, text: str) -> int:
    """Insert a memory row and add a fake embedding BLOB so has_any_memories returns True."""
    mid = save_memory(db, text)
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute(
        "UPDATE user_memories SET embedding = ? WHERE id = ?",
        (b"\x00" * 16, mid),
    )
    conn.commit()
    conn.close()
    return mid


# ---------------------------------------------------------------------------
# Step 2: Storage Layer tests
# ---------------------------------------------------------------------------


class TestMemoryStore:
    def test_init_memory_table(self, tmp_path):
        """Table creation is idempotent."""
        db = tmp_path / "idempotent.db"
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        init_memory_table(cur)
        init_memory_table(cur)  # Second call must not raise
        conn.commit()
        conn.close()

    def test_save_and_get_memory(self, tmp_path):
        db = _make_db(tmp_path)
        mid = save_memory(db, "User prefers dark mode")
        mems = get_all_memories(db)
        assert len(mems) == 1
        assert mems[0]["id"] == mid
        assert mems[0]["memory_text"] == "User prefers dark mode"

    def test_get_memory_by_id(self, tmp_path):
        db = _make_db(tmp_path)
        mid = save_memory(db, "Name is Alice")
        row = get_memory_by_id(db, mid)
        assert row is not None
        assert row["memory_text"] == "Name is Alice"
        assert get_memory_by_id(db, 9999) is None

    def test_delete_memory(self, tmp_path):
        db = _make_db(tmp_path)
        mid = save_memory(db, "to delete")
        assert delete_memory_from_db(db, mid) is True
        assert get_all_memories(db) == []
        # Deleting non-existent returns False
        assert delete_memory_from_db(db, 9999) is False

    def test_delete_all_memories(self, tmp_path):
        db = _make_db(tmp_path)
        save_memory(db, "A")
        save_memory(db, "B")
        save_memory(db, "C")
        count = delete_all_memories_from_db(db)
        assert count == 3
        assert get_all_memories(db) == []

    def test_has_any_memories_false_when_empty(self, tmp_path):
        db = _make_db(tmp_path)
        assert has_any_memories(db) is False

    def test_has_any_memories_true_after_embed(self, tmp_path):
        db = _make_db(tmp_path)
        _insert_with_embedding(db, "User likes Python")
        assert has_any_memories(db) is True

    def test_has_any_memories_false_without_embedding(self, tmp_path):
        """Row without embedding does not count."""
        db = _make_db(tmp_path)
        save_memory(db, "No embedding yet")
        assert has_any_memories(db) is False

    def test_update_memory(self, tmp_path):
        db = _make_db(tmp_path)
        mid = save_memory(db, "Old fact", ["old"])
        success = update_memory(db, mid, "New fact", ["new"])
        assert success is True
        row = get_memory_by_id(db, mid)
        assert row["memory_text"] == "New fact"
        assert row["tags"] == ["new"]

    def test_save_memory_with_tags(self, tmp_path):
        db = _make_db(tmp_path)
        mid = save_memory(db, "User is a developer", ["preference", "work"])
        row = get_memory_by_id(db, mid)
        assert row["tags"] == ["preference", "work"]


# ---------------------------------------------------------------------------
# Step 4/6: Dedup and vector ops tests (mocked embeddings)
# ---------------------------------------------------------------------------


class TestDedup:
    def test_dedup_saves_update(self, tmp_path):
        """Near-duplicate text triggers update rather than new insert."""
        db = _make_db(tmp_path)
        fake_embedding = [0.1] * 384

        with patch(
            "asky.memory.vector_ops.EmbeddingClient"
        ) as MockEmbClient, patch(
            "asky.memory.vector_ops._get_chroma_collection", return_value=None
        ):
            mock_instance = MagicMock()
            mock_instance.embed_single.return_value = fake_embedding
            mock_instance.model = "mock-model"
            MockEmbClient.return_value = mock_instance
            MockEmbClient.serialize_embedding = MagicMock(return_value=b"\x00" * 16)
            MockEmbClient.deserialize_embedding = MagicMock(
                return_value=fake_embedding
            )

            from asky.memory.vector_ops import find_near_duplicate, store_memory_embedding
            from asky.config import RESEARCH_CHROMA_PERSIST_DIRECTORY, USER_MEMORY_CHROMA_COLLECTION

            # Insert first memory with embedding
            mid1 = save_memory(db, "I like Python")
            store_memory_embedding(
                db_path=db,
                chroma_dir=RESEARCH_CHROMA_PERSIST_DIRECTORY,
                memory_id=mid1,
                text="I like Python",
                collection_name=USER_MEMORY_CHROMA_COLLECTION,
            )

            # Near-duplicate should resolve to mid1
            dup_id = find_near_duplicate(
                db_path=db,
                chroma_dir=RESEARCH_CHROMA_PERSIST_DIRECTORY,
                text="I really like Python a lot",
                threshold=0.90,
                collection_name=USER_MEMORY_CHROMA_COLLECTION,
            )
            # With identical embeddings, cosine similarity = 1.0 >= 0.90
            assert dup_id == mid1

            # After updating, still one row
            update_memory(db, mid1, "I really like Python a lot")
            assert len(get_all_memories(db)) == 1


# ---------------------------------------------------------------------------
# Step 5: Recall pipeline tests
# ---------------------------------------------------------------------------


class TestRecallPipeline:
    def test_recall_returns_none_when_empty(self, tmp_path):
        db = _make_db(tmp_path)
        from asky.memory.recall import recall_memories_for_query

        result = recall_memories_for_query(
            query_text="What is my name?",
            top_k=5,
            min_similarity=0.35,
            db_path=db,
            chroma_dir=tmp_path / "chroma",
        )
        assert result is None

    def test_recall_returns_formatted_block(self, tmp_path):
        db = _make_db(tmp_path)
        fake_embedding = [0.5] * 384

        with patch(
            "asky.memory.vector_ops.EmbeddingClient"
        ) as MockEmbClient, patch(
            "asky.memory.vector_ops._get_chroma_collection", return_value=None
        ), patch(
            "asky.research.query_expansion.expand_query_deterministic",
            return_value=["name"],
        ):
            mock_instance = MagicMock()
            mock_instance.embed_single.return_value = fake_embedding
            mock_instance.model = "mock-model"
            MockEmbClient.return_value = mock_instance
            MockEmbClient.deserialize_embedding = MagicMock(
                return_value=fake_embedding
            )
            MockEmbClient.serialize_embedding = MagicMock(return_value=b"\x00" * 16)

            # Insert a memory with an embedding so has_any_memories is True
            mid = save_memory(db, "User name is Evren")
            conn = sqlite3.connect(db)
            c = conn.cursor()
            import struct
            raw = struct.pack(f"{len(fake_embedding)}f", *fake_embedding)
            c.execute(
                "UPDATE user_memories SET embedding = ?, embedding_model = ? WHERE id = ?",
                (raw, "mock-model", mid),
            )
            conn.commit()
            conn.close()

            from asky.memory.recall import recall_memories_for_query

            result = recall_memories_for_query(
                query_text="What is my name?",
                top_k=5,
                min_similarity=0.10,
                db_path=db,
                chroma_dir=tmp_path / "chroma",
            )
            assert result is not None
            assert "## User Memory" in result
            assert "Evren" in result


# ---------------------------------------------------------------------------
# Step 6: Tool registry tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_save_memory_tool_registered_in_default_registry(self):
        from asky.core.tool_registry_factory import create_tool_registry

        registry = create_tool_registry()
        assert "save_memory" in registry.get_tool_names()

    def test_save_memory_tool_registered_in_research_registry(self):
        from asky.core.tool_registry_factory import create_research_tool_registry

        registry = create_research_tool_registry()
        assert "save_memory" in registry.get_tool_names()

    def test_save_memory_tool_respects_tool_off(self):
        from asky.core.tool_registry_factory import create_tool_registry

        registry = create_tool_registry(disabled_tools={"save_memory"})
        assert "save_memory" not in registry.get_tool_names()

    def test_save_memory_in_available_tool_names(self):
        from asky.core.tool_registry_factory import get_all_available_tool_names

        assert "save_memory" in get_all_available_tool_names()


# ---------------------------------------------------------------------------
# Step 7: CLI flag tests
# ---------------------------------------------------------------------------


class TestCLIFlags:
    def _parse(self, argv: list[str]):
        with patch("sys.argv", ["asky"] + argv):
            from asky.cli.main import parse_args

            return parse_args()

    def test_cli_list_memories_flag(self):
        args = self._parse(["--list-memories"])
        assert args.list_memories is True

    def test_cli_delete_memory_flag(self):
        args = self._parse(["--delete-memory", "42"])
        assert args.delete_memory == 42

    def test_cli_clear_memories_flag(self):
        args = self._parse(["--clear-memories"])
        assert args.clear_memories is True

    def test_cli_elephant_mode_long_flag(self):
        args = self._parse(["--elephant-mode", "hello"])
        assert args.elephant_mode is True

    def test_cli_elephant_mode_short_flag(self):
        args = self._parse(["-em", "hello"])
        assert args.elephant_mode is True


# ---------------------------------------------------------------------------
# Step 3/8: Session memory_auto_extract persistence
# ---------------------------------------------------------------------------


class TestSessionAutoExtract:
    def test_session_memory_auto_extract_persistence(self, tmp_path):
        db = tmp_path / "ses_test.db"
        with patch("asky.storage.sqlite.DB_PATH", db):
            from asky.storage.sqlite import SQLiteHistoryRepository

            repo = SQLiteHistoryRepository()
            repo.init_db()
            sid = repo.create_session("model-x", name="elephant", memory_auto_extract=True)
            session = repo.get_session_by_id(sid)
            assert session.memory_auto_extract is True

    def test_set_session_memory_auto_extract(self, tmp_path):
        db = tmp_path / "ses_flag.db"
        with patch("asky.storage.sqlite.DB_PATH", db):
            from asky.storage.sqlite import SQLiteHistoryRepository

            repo = SQLiteHistoryRepository()
            repo.init_db()
            sid = repo.create_session("model-x", name="normal", memory_auto_extract=False)
            repo.set_session_memory_auto_extract(sid, True)
            session = repo.get_session_by_id(sid)
            assert session.memory_auto_extract is True


# ---------------------------------------------------------------------------
# Step 8: Auto-extraction tests
# ---------------------------------------------------------------------------


class TestAutoExtraction:
    def test_auto_extract_parses_json_response(self, tmp_path):
        """Mock LLM returning JSON array → memories saved via execute_save_memory."""
        db = _make_db(tmp_path)
        mock_llm = MagicMock(
            return_value={"content": '["User likes Python", "User works remotely"]'}
        )

        with patch(
            "asky.memory.tools.execute_save_memory"
        ) as mock_save:
            mock_save.side_effect = [
                {"status": "saved", "memory_id": 1},
                {"status": "saved", "memory_id": 2},
            ]

            from asky.memory.auto_extract import extract_and_save_memories_from_turn

            result = extract_and_save_memories_from_turn(
                query="I prefer Python and work from home",
                answer="Got it!",
                llm_client=mock_llm,
                model="mock-model",
                db_path=db,
                chroma_dir=tmp_path / "chroma",
            )

        assert result == [1, 2]
        assert mock_save.call_count == 2
        calls = [c.args[0]["memory"] for c in mock_save.call_args_list]
        assert "User likes Python" in calls
        assert "User works remotely" in calls

    def test_auto_extract_empty_response(self, tmp_path):
        """Mock LLM returning [] → no memories saved."""
        db = _make_db(tmp_path)
        mock_llm = MagicMock(return_value={"content": "[]"})

        with patch("asky.memory.tools.execute_save_memory") as mock_save:
            from asky.memory.auto_extract import extract_and_save_memories_from_turn

            result = extract_and_save_memories_from_turn(
                query="What time is it?",
                answer="It is noon.",
                llm_client=mock_llm,
                model="mock-model",
                db_path=db,
                chroma_dir=tmp_path / "chroma",
            )

        assert result == []
        mock_save.assert_not_called()

    def test_auto_extract_malformed_json_is_handled(self, tmp_path):
        """Malformed JSON does not raise; returns empty list."""
        db = _make_db(tmp_path)
        mock_llm = MagicMock(return_value={"content": "Not JSON"})

        with patch("asky.memory.tools.execute_save_memory") as mock_save:
            from asky.memory.auto_extract import extract_and_save_memories_from_turn

            result = extract_and_save_memories_from_turn(
                query="hello",
                answer="hi",
                llm_client=mock_llm,
                model="mock-model",
                db_path=db,
                chroma_dir=tmp_path / "chroma",
            )

        assert result == []
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Step 5b: Memory context injected into system prompt
# ---------------------------------------------------------------------------


class TestSystemPromptInjection:
    def test_memory_context_injected_into_system_prompt(self):
        """PreloadResolution with memory_context → build_messages injects it into system prompt."""
        from asky.api.client import AskyClient
        from asky.api.types import AskyConfig, PreloadResolution

        config = AskyConfig(model_alias="gf")
        client = AskyClient(config)

        preload = PreloadResolution()
        preload.memory_context = (
            "## User Memory\n"
            "The following are previously saved facts about this user:\n"
            "- User name is Evren"
        )

        messages = client.build_messages(
            query_text="hello",
            preload=preload,
        )

        assert len(messages) > 0
        sys_content = messages[0]["content"]
        assert "## User Memory" in sys_content
        assert "Evren" in sys_content

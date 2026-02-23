import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from asky.storage import (
    init_db,
    save_interaction,
    get_history,
    get_interaction_context,
    delete_messages,
    delete_sessions,
    create_session,
    save_message,
    get_session_messages,
)


@pytest.fixture
def temp_db_path(tmp_path):
    # Create a temporary database path
    db_file = tmp_path / "test_history.db"
    return db_file


@pytest.fixture
def mock_db_path(temp_db_path):
    # Mock the DB_PATH constant in all storage modules
    with (
        patch("asky.storage.sqlite.DB_PATH", temp_db_path),
        patch("asky.config.DB_PATH", temp_db_path),
    ):
        # Re-instantiate the repository with the mocked path
        from asky.storage import _repo

        _repo.db_path = temp_db_path
        yield temp_db_path


def test_init_db(mock_db_path):
    init_db()
    assert mock_db_path.exists()

    conn = sqlite3.connect(mock_db_path)
    c = conn.cursor()
    # Check for new unified messages table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    assert c.fetchone() is not None
    # Check for sessions table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
    assert c.fetchone() is not None
    conn.close()


def test_save_and_get_history(mock_db_path):
    init_db()
    save_interaction(
        query="test query",
        answer="test answer",
        model="test_model",
        query_summary="q sum",
        answer_summary="a sum",
    )

    rows = get_history(limit=1)
    assert len(rows) == 1

    # Access via attributes (Interaction dataclass)
    interaction = rows[0]
    assert interaction.session_id is None  # Non-session message
    assert interaction.role is None
    assert "test query" in interaction.content
    assert "test answer" in interaction.content
    # query_summary is removed from Interaction.
    # summary reflects the interaction summary (usually answer summary or last msg)
    assert interaction.summary == "a sum"
    assert interaction.model == "test_model"


def test_get_interaction_context(mock_db_path):
    init_db()
    # Use a query longer than the default threshold (160)
    save_interaction("q1" * 100, "a1", "m1", "qs1", "as1")

    # Get the ID of the inserted row
    rows = get_history(1)
    rid = rows[0].id

    context = get_interaction_context([rid])
    # Now that we use explicit message IDs, referencing the interaction ID (Answer ID)
    # might only return the answer context unless we expand logic.
    # But context usually implies Q+A.
    assert "Answer: as1" in context
    # We should expect Query too if smart expansion works.
    # If not, checks might need adjustment. For now keeping assertion conservative
    # or relying on get_interaction_context fix.
    assert "Query" in context

    context_full = get_interaction_context([rid], full=True)
    assert "a1" in context_full


def test_save_message(mock_db_path):
    init_db()
    session_id = create_session("model")
    save_message(session_id, "user", "test content", "test summary", 10)

    rows = get_session_messages(session_id)
    assert len(rows) == 1
    assert rows[0].content == "test content"
    assert rows[0].summary == "test summary"


def test_cleanup_db(mock_db_path, capsys):
    init_db()
    # Insert 3 records
    for i in range(3):
        save_interaction(f"q{i}", f"a{i}", "m")

    # Verify insert
    assert len(get_history(10)) == 3

    # Test deletion by ID
    rows = get_history(10)
    ids = [r.id for r in rows]
    target_id = ids[0]

    delete_messages(str(target_id))
    assert len(get_history(10)) == 2

    # Test delete all
    delete_messages(delete_all=True)
    assert len(get_history(10)) == 0


def test_cleanup_db_edge_cases(mock_db_path, capsys):
    init_db()
    ids = []
    for i in range(5):
        save_interaction(f"q{i}", f"a{i}", "m")

    rows = get_history(10)  # 5,4,3,2,1
    # Test reverse range 4-2
    # IDs are now likely 2, 4, 6, 8, 10
    # 4-2 deletes IDs 2, 3, 4.
    # 2=Interaction 1. 4=Interaction 2.
    # So 2 interactions deleted. 3 remaining.
    delete_messages("4-2")

    remaining = get_history(10)
    assert len(remaining) == 3

    # Test invalid range
    delete_messages("a-b")
    captured = capsys.readouterr()
    assert "Error: Invalid range format" in captured.out

    # Test invalid list
    delete_messages("1,a")
    captured = capsys.readouterr()
    assert "Error: Invalid list format" in captured.out

    # Test invalid ID
    delete_messages("abc")
    captured = capsys.readouterr()
    assert "Error: Invalid ID format" in captured.out


def test_delete_sessions(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    # Create 3 sessions
    sid1 = repo.create_session("model", name="s1")
    sid2 = repo.create_session("model", name="s2")
    sid3 = repo.create_session("model", name="s3")

    # Add messages to sid1
    repo.save_message(sid1, "user", "hi", "hi", 10)

    # Verify messages exist
    assert len(repo.get_session_messages(sid1)) == 1

    # Test delete session 1
    delete_sessions(str(sid1))
    assert repo.get_session_by_id(sid1) is None
    assert len(repo.get_session_messages(sid1)) == 0

    # Test delete all
    delete_sessions(delete_all=True)
    assert repo.get_session_by_id(sid2) is None
    assert repo.get_session_by_id(sid3) is None


def test_session_research_profile_roundtrip(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    sid = repo.create_session(
        "model",
        name="research",
        research_mode=True,
        research_source_mode="mixed",
        research_local_corpus_paths=["/books/a.epub", "/books/b.epub"],
    )
    loaded = repo.get_session_by_id(sid)
    assert loaded is not None
    assert loaded.research_mode is True
    assert loaded.research_source_mode == "mixed"
    assert loaded.research_local_corpus_paths == ["/books/a.epub", "/books/b.epub"]

    repo.update_session_research_profile(
        sid,
        research_mode=True,
        research_source_mode="web_only",
        research_local_corpus_paths=[],
    )
    updated = repo.get_session_by_id(sid)
    assert updated is not None
    assert updated.research_mode is True
    assert updated.research_source_mode == "web_only"
    assert updated.research_local_corpus_paths == []


def test_transcript_crud_and_prune(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()
    session_id = repo.create_session("model", name="xmpp:test@example.com")

    t1 = repo.create_transcript(
        session_id=session_id,
        jid="user@example.com/resource",
        audio_url="https://example.com/a1.m4a",
        audio_path="/tmp/a1.m4a",
        status="pending",
    )
    assert t1.session_transcript_id == 1
    assert t1.status == "pending"

    t2 = repo.create_transcript(
        session_id=session_id,
        jid="user@example.com/resource",
        audio_url="https://example.com/a2.m4a",
        audio_path="/tmp/a2.m4a",
        status="pending",
    )
    assert t2.session_transcript_id == 2

    updated = repo.update_transcript(
        session_id=session_id,
        session_transcript_id=2,
        status="completed",
        transcript_text="hello world",
        duration_seconds=1.2,
        used=True,
    )
    assert updated is not None
    assert updated.status == "completed"
    assert updated.used is True
    assert updated.transcript_text == "hello world"

    listed = repo.list_transcripts(session_id=session_id, limit=10)
    assert [item.session_transcript_id for item in listed] == [2, 1]

    got = repo.get_transcript(session_id=session_id, session_transcript_id=2)
    assert got is not None
    assert got.audio_url.endswith("a2.m4a")

    deleted = repo.prune_transcripts(session_id=session_id, keep=1)
    assert len(deleted) == 1
    assert deleted[0].session_transcript_id == 1

    remaining = repo.list_transcripts(session_id=session_id, limit=10)
    assert len(remaining) == 1
    assert remaining[0].session_transcript_id == 2

    i1 = repo.create_image_transcript(
        session_id=session_id,
        jid="user@example.com/resource",
        image_url="https://example.com/i1.jpg",
        image_path="/tmp/i1.jpg",
        status="pending",
    )
    assert i1.session_image_id == 1
    assert i1.status == "pending"

    i2 = repo.create_image_transcript(
        session_id=session_id,
        jid="user@example.com/resource",
        image_url="https://example.com/i2.jpg",
        image_path="/tmp/i2.jpg",
        status="pending",
    )
    assert i2.session_image_id == 2

    image_updated = repo.update_image_transcript(
        session_id=session_id,
        session_image_id=2,
        status="completed",
        transcript_text="image description",
        duration_seconds=0.7,
        used=True,
    )
    assert image_updated is not None
    assert image_updated.status == "completed"
    assert image_updated.used is True
    assert image_updated.transcript_text == "image description"

    image_listed = repo.list_image_transcripts(session_id=session_id, limit=10)
    assert [item.session_image_id for item in image_listed] == [2, 1]

    image_got = repo.get_image_transcript(session_id=session_id, session_image_id=2)
    assert image_got is not None
    assert image_got.image_url.endswith("i2.jpg")

    image_deleted = repo.prune_image_transcripts(session_id=session_id, keep=1)
    assert len(image_deleted) == 1
    assert image_deleted[0].session_image_id == 1

    image_remaining = repo.list_image_transcripts(session_id=session_id, limit=10)
    assert len(image_remaining) == 1
    assert image_remaining[0].session_image_id == 2


def test_room_session_binding_roundtrip(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()
    session_id = repo.create_session("model", name="room-session")

    repo.set_room_session_binding(
        room_jid="Room@conference.example.com",
        session_id=session_id,
    )
    binding = repo.get_room_session_binding(room_jid="room@conference.example.com")
    assert binding is not None
    assert binding.room_jid == "room@conference.example.com"
    assert binding.session_id == session_id

    listed = repo.list_room_session_bindings()
    assert len(listed) == 1
    assert listed[0].room_jid == "room@conference.example.com"


def test_session_override_files_roundtrip_and_copy(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()
    source_session = repo.create_session("model", name="source")
    target_session = repo.create_session("model", name="target")

    repo.save_session_override_file(
        session_id=source_session,
        filename="general.toml",
        content='[general]\ndefault_model = "a"\n',
    )
    repo.save_session_override_file(
        session_id=source_session,
        filename="user.toml",
        content='[user_prompts]\nfoo = "bar"\n',
    )

    loaded = repo.get_session_override_file(
        session_id=source_session,
        filename="GENERAL.toml",
    )
    assert loaded is not None
    assert loaded.filename == "general.toml"
    assert 'default_model = "a"' in loaded.content

    copied_count = repo.copy_session_override_files(
        source_session_id=source_session,
        target_session_id=target_session,
    )
    assert copied_count == 2

    target_files = repo.list_session_override_files(session_id=target_session)
    assert [item.filename for item in target_files] == ["general.toml", "user.toml"]


def test_init_db_deduplicates_legacy_duplicate_session_names(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    conn = sqlite3.connect(mock_db_path)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            model TEXT,
            created_at TEXT,
            compacted_summary TEXT
        )
        """
    )
    c.execute(
        "INSERT INTO sessions (name, model, created_at, compacted_summary) VALUES (?, ?, ?, ?)",
        ("dup_name", "model", "2026-02-20T10:00:00", None),
    )
    c.execute(
        "INSERT INTO sessions (name, model, created_at, compacted_summary) VALUES (?, ?, ?, ?)",
        ("dup_name", "model", "2026-02-21T10:00:00", None),
    )
    conn.commit()
    conn.close()

    repo = SQLiteHistoryRepository()
    repo.init_db()

    conn = sqlite3.connect(mock_db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sessions ORDER BY id ASC")
    names = [row[0] for row in c.fetchall()]
    conn.close()

    assert len(names) == 2
    assert len(set(names)) == 2
    assert "dup_name" in names


def test_clear_session_messages_preserves_transcripts(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository
    from asky.storage import clear_session_messages, get_session_messages

    repo = SQLiteHistoryRepository()
    init_db()
    session_id = repo.create_session("model", name="clear-test")

    # Add messages
    repo.save_message(session_id, "user", "msg1", "sum1", 10)
    repo.save_message(session_id, "assistant", "msg2", "sum2", 10)
    repo.compact_session(session_id, "Compacted")

    # Add transcript
    repo.create_transcript(
        session_id=session_id,
        jid="user@example.com",
        audio_url="url",
        audio_path="path",
        status="completed",
    )

    # Verify initial state
    assert len(get_session_messages(session_id)) == 2
    assert len(repo.list_transcripts(session_id=session_id)) == 1
    assert repo.get_session_by_id(session_id).compacted_summary == "Compacted"

    # Clear
    deleted = clear_session_messages(session_id)
    assert deleted == 2

    # Verify final state
    assert len(get_session_messages(session_id)) == 0
    assert len(repo.list_transcripts(session_id=session_id)) == 1
    assert repo.get_session_by_id(session_id).compacted_summary is None

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


def test_history_includes_session_bound_messages(mock_db_path):
    init_db()

    save_interaction("history query", "history answer", "m")

    session_id = create_session("m", name="session-one")
    save_message(session_id, "user", "session query", "session q sum", 1)
    assistant_id = save_message(
        session_id,
        "assistant",
        "session answer",
        "session a sum",
        1,
    )

    rows = get_history(limit=5)
    assert len(rows) >= 2
    matching = [row for row in rows if row.id == assistant_id]
    assert matching
    interaction = matching[0]
    assert interaction.session_id == session_id
    assert interaction.query == "session query"
    assert interaction.answer == "session answer"
    assert interaction.summary == "session a sum"


def test_get_interaction_context_expands_session_partner(mock_db_path):
    init_db()
    session_id = create_session("m", name="ctx-session")
    save_message(session_id, "user", "user in session", "user sum", 1)
    assistant_id = save_message(session_id, "assistant", "assistant in session", "", 1)

    context = get_interaction_context([assistant_id], full=False)
    assert "Query: user sum" in context
    assert "Answer: assistant in session" in context


def test_delete_messages_expands_within_session_scope(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    init_db()
    repo = SQLiteHistoryRepository()
    session_id = create_session("m", name="delete-session")
    user_id = save_message(session_id, "user", "session user", "session user sum", 1)
    assistant_id = save_message(
        session_id,
        "assistant",
        "session assistant",
        "session assistant sum",
        1,
    )

    deleted = delete_messages(str(assistant_id))
    assert deleted == 2
    assert repo.get_session_messages(session_id) == []
    assert repo.get_interaction_by_id(user_id) is None
    assert repo.get_interaction_by_id(assistant_id) is None


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


def test_session_shortlist_override_roundtrip(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    sid = repo.create_session("model", name="shortlist-test")
    loaded = repo.get_session_by_id(sid)
    assert loaded is not None
    assert loaded.shortlist_override is None

    repo.update_session_shortlist_override(sid, "on")
    updated = repo.get_session_by_id(sid)
    assert updated is not None
    assert updated.shortlist_override == "on"

    repo.update_session_shortlist_override(sid, "off")
    updated2 = repo.get_session_by_id(sid)
    assert updated2 is not None
    assert updated2.shortlist_override == "off"

    repo.update_session_shortlist_override(sid, None)
    cleared = repo.get_session_by_id(sid)
    assert cleared is not None
    assert cleared.shortlist_override is None


def test_session_query_defaults_roundtrip(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    sid = repo.create_session("model", name="defaults-test")
    loaded = repo.get_session_by_id(sid)
    assert loaded is not None
    assert loaded.query_defaults == {}

    repo.update_session_query_defaults(
        sid,
        {
            "model": "gf",
            "tool_off": ["web_search"],
            "pending_auto_name": True,
        },
    )
    updated = repo.get_session_by_id(sid)
    assert updated is not None
    assert updated.query_defaults == {
        "model": "gf",
        "tool_off": ["web_search"],
        "pending_auto_name": True,
    }


def test_update_session_name_ensures_uniqueness(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    sid1 = repo.create_session("model", name="target_name")
    sid2 = repo.create_session("model", name="other_name")

    repo.update_session_name(sid2, "target_name")

    s1 = repo.get_session_by_id(sid1)
    s2 = repo.get_session_by_id(sid2)
    assert s1 is not None
    assert s2 is not None
    assert s1.name == "target_name"
    assert s2.name != "target_name"


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

    # Add messages and compact (compaction deletes pre-compaction messages)
    repo.save_message(session_id, "user", "old1", "sum1", 10)
    repo.save_message(session_id, "assistant", "old2", "sum2", 10)
    repo.compact_session(session_id, "Compacted")

    # Add post-compaction messages
    repo.save_message(session_id, "user", "msg1", "sum1", 10)
    repo.save_message(session_id, "assistant", "msg2", "sum2", 10)

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


def test_uploaded_documents_dedupe_and_session_links(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()
    session_a = repo.create_session("model", name="upload-a")
    session_b = repo.create_session("model", name="upload-b")

    first = repo.upsert_uploaded_document(
        content_hash="abc123",
        file_path="/tmp/uploads/report.pdf",
        original_filename="report.pdf",
        file_extension=".pdf",
        mime_type="application/pdf",
        file_size=1024,
    )
    assert first.content_hash == "abc123"

    second = repo.upsert_uploaded_document(
        content_hash="abc123",
        file_path="/tmp/uploads/report_2.pdf",
        original_filename="report.pdf",
        file_extension=".pdf",
        mime_type="application/pdf",
        file_size=1024,
    )
    assert second.id == first.id
    assert second.file_path.endswith("report_2.pdf")

    repo.save_uploaded_document_url(
        url="https://example.com/files/report.pdf",
        document_id=first.id,
    )
    by_url = repo.get_uploaded_document_by_url(
        url="https://example.com/files/report.pdf"
    )
    assert by_url is not None
    assert by_url.id == first.id

    repo.link_session_uploaded_document(session_id=session_a, document_id=first.id)
    repo.link_session_uploaded_document(session_id=session_b, document_id=first.id)
    listed_a = repo.list_session_uploaded_documents(session_id=session_a)
    listed_b = repo.list_session_uploaded_documents(session_id=session_b)
    assert len(listed_a) == 1
    assert len(listed_b) == 1
    assert listed_a[0].id == listed_b[0].id

    cleared = repo.clear_session_uploaded_documents(session_id=session_a)
    assert cleared == 1
    assert repo.list_session_uploaded_documents(session_id=session_a) == []
    assert len(repo.list_session_uploaded_documents(session_id=session_b)) == 1


def test_delete_sessions_implicit_research_cleanup(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository
    from unittest.mock import patch, MagicMock

    repo = SQLiteHistoryRepository()
    init_db()

    # Create a session with some messages and an upload link
    sid = repo.create_session("model", name="cleanup-test")
    repo.save_message(sid, "user", "hi", "hi", 10)

    # Link an uploaded document
    doc = repo.upsert_uploaded_document(
        content_hash="h1",
        file_path="p1",
        original_filename="f1",
        file_extension=".txt",
        mime_type="text/plain",
        file_size=10,
    )
    repo.link_session_uploaded_document(session_id=sid, document_id=doc.id)

    assert len(repo.list_session_uploaded_documents(session_id=sid)) == 1

    # Mock VectorStore to avoid real Chroma calls or heavy imports during standard storage test
    with patch("asky.lazy_imports.call_attr") as mock_call_attr:
        mock_vs = MagicMock()
        mock_call_attr.return_value = mock_vs

        # Act: Delete the session
        delete_sessions(str(sid))

        # 1. Verify messages and session are gone
        assert repo.get_session_by_id(sid) is None
        assert repo.get_session_messages(sid) == []

        # 2. Verify research cleanup was called
        mock_call_attr.assert_called_with(
            "asky.research.vector_store", "get_vector_store"
        )
        mock_vs.delete_findings_by_session.assert_called_with(str(sid))

        # 3. Verify session upload links are also gone (in the same DB)
        assert repo.list_session_uploaded_documents(session_id=sid) == []


def test_delete_sessions_implicit_research_cleanup_failure_resilience(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository
    from unittest.mock import patch, MagicMock

    repo = SQLiteHistoryRepository()
    init_db()

    sid = repo.create_session("model", name="resilience-test")

    with patch("asky.lazy_imports.call_attr") as mock_call_attr:
        mock_vs = MagicMock()
        mock_vs.delete_findings_by_session.side_effect = Exception("Chroma boom")
        mock_call_attr.return_value = mock_vs

        # Act: Delete the session should NOT raise even if research cleanup fails
        delete_sessions(str(sid))

        # Verify session is still deleted despite the research cleanup failure
        assert repo.get_session_by_id(sid) is None


def test_delete_sessions_cleanup_continues_per_session_on_failure(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository
    from unittest.mock import patch, MagicMock

    repo = SQLiteHistoryRepository()
    init_db()

    sid1 = repo.create_session("model", name="batch-cleanup-1")
    sid2 = repo.create_session("model", name="batch-cleanup-2")

    with patch("asky.lazy_imports.call_attr") as mock_call_attr:
        mock_vs = MagicMock()

        def _delete_side_effect(session_id: str):
            if session_id == str(sid1):
                raise Exception("first cleanup failed")
            return 1

        mock_vs.delete_findings_by_session.side_effect = _delete_side_effect
        mock_call_attr.return_value = mock_vs

        delete_sessions(f"{sid1},{sid2}")

        # Cleanup attempted for both sessions even though first one failed
        attempted = [call.args[0] for call in mock_vs.delete_findings_by_session.call_args_list]
        assert attempted == [str(sid1), str(sid2)]
        assert repo.get_session_by_id(sid1) is None
        assert repo.get_session_by_id(sid2) is None


def test_delete_sessions_real_research_cleanup(mock_db_path):
    """Semi-real test verifying that findings are actually deleted from the DB
    and that we don't hit SQLite locking issues when both storage and vector_store
    touch the same file.
    """
    from asky.storage.sqlite import SQLiteHistoryRepository
    from asky.research.cache import ResearchCache
    from asky.research.vector_store import VectorStore
    from unittest.mock import patch, MagicMock

    # Reset singletons to avoid pollution
    ResearchCache._instance = None
    VectorStore._instance = None

    try:
        repo = SQLiteHistoryRepository()
        init_db()

        # Initialize research findings table in the same mock DB
        cache = ResearchCache(db_path=str(mock_db_path))
        cache.init_db()

        # Create the session in repo first to avoid ID-order assumptions
        sid = repo.create_session("model", name="real-cleanup-test")

        # Insert a finding via raw SQL for this session
        conn = sqlite3.connect(mock_db_path)
        c = conn.cursor()
        c.execute(
            "INSERT INTO research_findings (finding_text, session_id, created_at) VALUES (?, ?, ?)",
            ("fact1", str(sid), "2026-03-01T23:59:00"),
        )
        conn.commit()
        conn.close()

        # Bind vector cleanup to the same mocked DB file used by storage.
        vector_store = VectorStore(
            db_path=str(mock_db_path),
            chroma_persist_directory=str(mock_db_path.parent / "chroma"),
        )

        # Mock Chroma collection only to avoid env/network deps
        with (
            patch(
                "asky.research.vector_store.VectorStore._get_chroma_collection"
            ) as mock_chroma,
            patch("asky.lazy_imports.call_attr", return_value=vector_store),
        ):
            mock_chroma.return_value = MagicMock()
            # Act: Delete the session
            # This triggers the code that previously had lock issues
            delete_sessions(str(sid))

        # Verify session is gone
        assert repo.get_session_by_id(sid) is None

        # Verify research findings are gone via REAL DB CHECK
        conn = sqlite3.connect(mock_db_path)
        c = conn.cursor()
        c.execute(
            "SELECT count(*) FROM research_findings WHERE session_id = ?", (str(sid),)
        )
        count = c.fetchone()[0]
        conn.close()

        assert count == 0, f"Expected 0 findings for session {sid}, found {count}"

    finally:
        ResearchCache._instance = None
        VectorStore._instance = None

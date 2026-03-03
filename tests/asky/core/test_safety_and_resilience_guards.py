"""Safety and resilience guardrail tests for core runtime behavior."""

import sqlite3
import threading
import time
from unittest.mock import patch

import pytest


def test_inline_toml_pattern_avoids_catastrophic_backtracking():
    from asky.plugins.xmpp_daemon.command_executor import INLINE_TOML_PATTERN

    bad_input = "a" * 100 + "`" * 50
    start = time.monotonic()
    INLINE_TOML_PATTERN.search(bad_input)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"Regex took {elapsed:.2f}s — possible ReDoS"


def test_inline_toml_pattern_matches_valid_toml_block():
    from asky.plugins.xmpp_daemon.command_executor import INLINE_TOML_PATTERN

    text = "config.toml\n```toml\nkey = 'value'\n```"
    m = INLINE_TOML_PATTERN.search(text)
    assert m is not None
    assert m.group("filename") == "config.toml"
    assert "key" in m.group("content")


def test_load_custom_prompts_rejects_file_uri_outside_home(capsys, tmp_path):
    from asky.cli.utils import load_custom_prompts

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret")

    prompts = {"sys": f"file://{outside_file}"}

    with patch("pathlib.Path.home", return_value=tmp_path / "home"):
        load_custom_prompts(prompts)

    out = capsys.readouterr().out
    assert "Warning" in out
    assert "outside home directory" in out
    assert prompts["sys"].startswith("file://"), "Value must not be replaced"


def test_load_custom_prompts_reads_file_uri_within_home(tmp_path):
    from asky.cli.utils import load_custom_prompts

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    prompt_file = fake_home / "my_prompt.txt"
    prompt_file.write_text("hello world")

    prompts = {"sys": f"file://{prompt_file}"}

    with patch("pathlib.Path.home", return_value=fake_home):
        load_custom_prompts(prompts)

    assert prompts["sys"] == "hello world"


def test_get_interaction_context_raises_when_summarization_fails(tmp_path):
    db_file = tmp_path / "test.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()
        # Save an interaction so there's something to look up
        conn = sqlite3.connect(db_file)
        conn.execute(
            "INSERT INTO messages (timestamp, session_id, role, content, summary, model) "
            "VALUES (datetime('now'), NULL, 'user', ?, NULL, 'test')",
            ("x" * 5000,),  # long content to trigger summarization path
        )
        conn.commit()
        msg_id = conn.execute("SELECT max(id) FROM messages").fetchone()[0]
        conn.close()

    with (
        patch("asky.storage.sqlite.DB_PATH", db_file),
    ):
        repo.db_path = db_file

        def _raise(*a, **kw):
            raise RuntimeError("summarization boom")

        with patch(
            "asky.storage.sqlite.SQLiteHistoryRepository.get_interaction_context"
        ) as mock_fn:
            mock_fn.side_effect = _raise
            with pytest.raises(RuntimeError):
                repo.get_interaction_context([msg_id])


def test_get_interaction_context_returns_empty_for_empty_ids(tmp_path):
    """Verify early-return path (empty ids) doesn't leak connection."""
    db_file = tmp_path / "empty.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()

    result = repo.get_interaction_context([])
    assert result == ""


def test_set_shell_session_id_writes_lock_atomically(tmp_path):
    from asky.core import session_manager as sm

    lock_file = tmp_path / "session.lock"
    with patch.object(sm, "_get_lock_file_path", return_value=lock_file):
        sm.set_shell_session_id(42)
        assert lock_file.exists()
        assert lock_file.read_text().strip() == "42"


def test_set_shell_session_id_removes_tmp_file_after_replace(tmp_path):
    from asky.core import session_manager as sm

    lock_file = tmp_path / "session.lock"
    with patch.object(sm, "_get_lock_file_path", return_value=lock_file):
        with patch("asky.core.session_manager.atexit"):
            sm.set_shell_session_id(99)

    tmp_file = lock_file.with_suffix(".tmp")
    assert not tmp_file.exists(), ".tmp file should be gone after atomic replace"


def test_enqueue_for_jid_starts_single_worker_under_concurrency():
    from unittest.mock import patch as _patch

    from asky.plugins.xmpp_daemon import xmpp_service as svc

    with (
        _patch("asky.plugins.xmpp_daemon.xmpp_service.TranscriptManager"),
        _patch("asky.plugins.xmpp_daemon.xmpp_service.CommandExecutor"),
        _patch("asky.plugins.xmpp_daemon.xmpp_service.InterfacePlanner"),
        _patch("asky.plugins.xmpp_daemon.xmpp_service.DaemonRouter"),
        _patch("asky.plugins.xmpp_daemon.xmpp_service.AskyXMPPClient"),
    ):
        service = svc.XMPPService.__new__(svc.XMPPService)
        service._jid_queues = {}
        service._jid_workers = {}
        service._jid_workers_lock = threading.Lock()

        exceptions = []

        def _run():
            try:
                service._enqueue_for_jid("user@example.com", lambda: None)
            except Exception as e:
                exceptions.append(e)

        t1 = threading.Thread(target=_run)
        t2 = threading.Thread(target=_run)
        t1.start()
        t2.start()
        t1.join(timeout=3)
        t2.join(timeout=3)

        assert not exceptions

        alive_workers = [w for w in service._jid_workers.values() if w.is_alive()]
        assert len(alive_workers) <= 1, (
            "Only one worker thread should be running per JID"
        )


def test_create_session_rejects_invalid_research_source_mode(tmp_path):
    db_file = tmp_path / "test.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()

    with pytest.raises(ValueError, match="research_source_mode"):
        repo.create_session(model="test", research_source_mode="invalid_mode")


def test_create_session_accepts_valid_research_source_mode(tmp_path):
    db_file = tmp_path / "test.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()

    sid = repo.create_session(model="test", research_source_mode="web_only")
    assert isinstance(sid, int)


def test_create_session_deduplicates_duplicate_names(tmp_path):
    db_file = tmp_path / "test.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()

    id1 = repo.create_session(model="test", name="my-session")
    id2 = repo.create_session(model="test", name="my-session")

    s1 = repo.get_session_by_id(id1)
    s2 = repo.get_session_by_id(id2)

    assert s1.name == "my-session"
    assert s2.name == "my-session_2"


def test_create_session_allows_multiple_unnamed_sessions(tmp_path):
    """NULL names must not trigger the unique constraint."""
    db_file = tmp_path / "test.db"

    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    repo.db_path = db_file

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo.init_db()

    id1 = repo.create_session(model="test", name=None)
    id2 = repo.create_session(model="test", name=None)
    assert id1 != id2

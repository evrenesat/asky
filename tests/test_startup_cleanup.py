import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import sqlite3
import sys
from asky.research.cache import ResearchCache
from asky.cli.main import main


class TestStartupCleanup:
    """Integration tests for startup cleanup."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a fresh ResearchCache instance for testing."""
        ResearchCache._instance = None
        db_path = str(tmp_path / "test_startup.db")
        cache = ResearchCache(db_path=db_path, ttl_hours=24)
        yield cache
        cache.shutdown()
        ResearchCache._instance = None

    @pytest.fixture
    def mock_args(self):
        """Mock command line arguments."""
        with patch("sys.argv", ["asky", "test query"]):
            with patch("asky.cli.main.parse_args") as mock_parse:
                args = MagicMock()
                args.model = "gpt-4o"
                args.continue_ids = None
                args.summarize = False
                args.delete_messages = None
                args.delete_sessions = None
                args.all = False
                args.history = None
                args.print_ids = None
                args.print_session = None
                args.prompts = False
                args.verbose = False
                args.open = False
                args.sendmail = None
                args.subject = None
                args.push_data = None
                args.sticky_session = None
                args.resume_session = None
                args.session_end = False
                args.session_history = None
                args.research = False
                args.add_model = False
                args.edit_model = None
                args.query = ["test", "query"]
                args.reply = False
                args.session_from_message = None
                args.clean_session_research = None
                args.completion_script = None
                args.list_tools = False
                args.query_corpus = None
                args.query_corpus_max_sources = 20
                args.query_corpus_max_chunks = 3
                args.summarize_section = None
                args.section_source = None
                args.section_detail = "balanced"
                args.section_max_chunks = None
                args.list_memories = False
                args.delete_memory = None
                args.clear_memories = False
                args.shortlist = None
                args.turns = None
                args.elephant_mode = False

                mock_parse.return_value = args
                yield mock_parse

    def test_cleanup_on_startup(self, cache, mock_args, tmp_path):
        """Test that expired entries are cleaned up on startup."""
        # Insert an expired entry
        url = "http://expired.example.com"
        url_hash = cache._url_hash(url)
        expired_time = (datetime.now() - timedelta(hours=25)).isoformat()

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO research_cache
            (url, url_hash, content, title, summary_status, links_json,
             fetch_timestamp, expires_at, content_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', '[]', ?, ?, ?, ?, ?)
            """,
            (
                url,
                url_hash,
                "Content",
                "Title",
                expired_time,
                expired_time,
                "hash",
                expired_time,
                expired_time,
            ),
        )
        conn.commit()
        conn.close()

        # Verify it exists
        assert (
            cache.get_cached(url) is None
        )  # get_cached filters by expiry, so returns None

        # Verify it exists in DB directly
        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM research_cache WHERE url = ?", (url,))
        assert c.fetchone()[0] == 1
        conn.close()

        # Mock other dependencies to run main() minimalistically
        with (
            patch("asky.cli.main.chat.run_chat"),
            patch("asky.cli.main.setup_logging"),
            patch("asky.cli.main.init_db"),
            patch("asky.cli.main.utils.load_custom_prompts"),
            patch("asky.cli.main.utils.expand_query_text", return_value="test query"),
            patch("asky.cli.main._start_research_cache_cleanup_thread") as mock_start,
        ):
            # Force cleanup to run synchronously for deterministic assertion.
            dummy_thread = MagicMock()

            def run_cleanup_sync():
                from asky.cli.main import _run_research_cache_cleanup

                _run_research_cache_cleanup()
                return dummy_thread

            mock_start.side_effect = run_cleanup_sync

            # We need to ensure ResearchCache uses our test instance
            # Since main instantiates ResearchCache(), we need to patch it or ensure singleton works
            # The test fixture sets _instance = None, then creates one.
            # main() calls ResearchCache() which should return our instance if valid
            # BUT ResearchCache args in main are defaults (db_path=None).
            # Our fixture created one with specific db_path.
            # ResearchCache singleton logic: if _instance exists, return it.
            # So main() 'ResearchCache()' call will return 'cache' fixture instance.

            main()

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM research_cache WHERE url = ?", (url,))
        assert c.fetchone()[0] == 0
        conn.close()

    def test_cleanup_failure_does_not_crash_startup(self, cache, mock_args):
        """Test that cleanup failure logs error but continues startup."""
        with (
            patch.object(
                ResearchCache, "cleanup_expired", side_effect=Exception("DB Error")
            ),
            patch("asky.cli.main.chat.run_chat") as mock_run_chat,
            patch("asky.cli.main.setup_logging"),
            patch("asky.cli.main.init_db"),
            patch("asky.cli.main.utils.load_custom_prompts"),
            patch("asky.cli.main.utils.expand_query_text", return_value="test query"),
            patch("logging.getLogger") as mock_logger,
        ):
            main()

            # Should still run chat
            mock_run_chat.assert_called_once()

            # Should log warning
            mock_logger.return_value.warning.assert_called()

"""Tests for the research cache module."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest


class TestResearchCache:
    """Tests for ResearchCache class."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a fresh ResearchCache instance for each test."""
        # Reset singleton for testing
        from asky.research.cache import ResearchCache

        ResearchCache._instance = None

        db_path = str(tmp_path / "test_research.db")
        cache = ResearchCache(db_path=db_path, ttl_hours=24, summarization_workers=1)
        yield cache
        cache.shutdown()

    def test_init_creates_tables(self, cache):
        """Test that initialization creates required tables."""
        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()

        # Check research_cache table exists
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='research_cache'"
        )
        assert c.fetchone() is not None

        # Check content_chunks table exists
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='content_chunks'"
        )
        assert c.fetchone() is not None

        # Check link_embeddings table exists
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='link_embeddings'"
        )
        assert c.fetchone() is not None

        conn.close()

    def test_cache_url_stores_content(self, cache):
        """Test that cache_url stores content correctly."""
        url = "http://example.com"
        content = "Test content"
        title = "Test Title"
        links = [{"text": "Link 1", "href": "http://link1.com"}]

        # Disable background summarization for this test
        cache_id = cache.cache_url(
            url=url,
            content=content,
            title=title,
            links=links,
            trigger_summarization=False,
        )

        assert cache_id > 0

        # Verify content was stored
        cached = cache.get_cached(url)
        assert cached is not None
        assert cached["content"] == content
        assert cached["title"] == title
        assert cached["links"] == links
        assert cached["cached"] is True

    def test_cache_url_deduplicates(self, cache):
        """Test that caching same URL updates instead of duplicating."""
        url = "http://example.com"

        cache_id1 = cache.cache_url(
            url=url,
            content="Content 1",
            title="Title 1",
            links=[],
            trigger_summarization=False,
        )

        cache_id2 = cache.cache_url(
            url=url,
            content="Content 2",
            title="Title 2",
            links=[],
            trigger_summarization=False,
        )

        # Should update existing entry
        cached = cache.get_cached(url)
        assert cached["content"] == "Content 2"
        assert cached["title"] == "Title 2"

    def test_cache_url_content_change_clears_chunk_vectors(self, cache):
        """Test that content changes invalidate stale chunk vectors."""
        url = "http://example.com/chunks"
        links = [{"text": "Link 1", "href": "http://link1.com"}]
        cache_id = cache.cache_url(
            url=url,
            content="Original content",
            title="Title",
            links=links,
            trigger_summarization=False,
        )

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO content_chunks
            (cache_id, chunk_index, chunk_text, embedding, embedding_model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cache_id, 0, "Old chunk", b"1234", "old-model", datetime.now().isoformat()),
        )
        c.execute(
            """
            INSERT INTO link_embeddings
            (cache_id, link_text, link_url, embedding, embedding_model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cache_id,
                "Link 1",
                "http://link1.com",
                b"1234",
                "old-model",
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        cache.cache_url(
            url=url,
            content="Updated content",
            title="Title",
            links=links,
            trigger_summarization=False,
        )

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM content_chunks WHERE cache_id = ?", (cache_id,))
        chunk_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM link_embeddings WHERE cache_id = ?", (cache_id,))
        link_count = c.fetchone()[0]
        conn.close()

        assert chunk_count == 0
        assert link_count == 1

    def test_cache_url_links_change_clears_link_vectors(self, cache):
        """Test that link list changes invalidate stale link vectors."""
        url = "http://example.com/links"
        cache_id = cache.cache_url(
            url=url,
            content="Same content",
            title="Title",
            links=[{"text": "Old link", "href": "http://old-link.com"}],
            trigger_summarization=False,
        )

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO link_embeddings
            (cache_id, link_text, link_url, embedding, embedding_model, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cache_id,
                "Old link",
                "http://old-link.com",
                b"1234",
                "old-model",
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

        cache.cache_url(
            url=url,
            content="Same content",
            title="Title",
            links=[{"text": "New link", "href": "http://new-link.com"}],
            trigger_summarization=False,
        )

        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM link_embeddings WHERE cache_id = ?", (cache_id,))
        link_count = c.fetchone()[0]
        conn.close()

        assert link_count == 0

    def test_get_cached_returns_none_for_missing(self, cache):
        """Test that get_cached returns None for non-existent URLs."""
        result = cache.get_cached("http://nonexistent.com")
        assert result is None

    def test_get_cached_returns_none_for_expired(self, cache):
        """Test that get_cached returns None for expired entries."""
        # Manually insert an expired entry to test expiration check
        from datetime import datetime, timedelta
        import sqlite3

        url = "http://expired.example.com"
        url_hash = cache._url_hash(url)
        expired_time = (datetime.now() - timedelta(hours=1)).isoformat()

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
                expired_time,  # expires_at in the past
                "hash",
                expired_time,
                expired_time,
            ),
        )
        conn.commit()
        conn.close()

        # Should return None for expired entry
        result = cache.get_cached(url)
        assert result is None

    def test_get_links_only(self, cache):
        """Test that get_links_only returns only links."""
        url = "http://example.com"
        links = [
            {"text": "Link 1", "href": "http://link1.com"},
            {"text": "Link 2", "href": "http://link2.com"},
        ]

        cache.cache_url(
            url=url,
            content="Content",
            title="Title",
            links=links,
            trigger_summarization=False,
        )

        result = cache.get_links_only(url)
        assert result == links

    def test_get_summary_returns_status(self, cache):
        """Test that get_summary returns summary info with status."""
        url = "http://example.com"

        cache.cache_url(
            url=url,
            content="Content",
            title="Test Title",
            links=[],
            trigger_summarization=False,
        )

        result = cache.get_summary(url)
        assert result is not None
        assert result["title"] == "Test Title"
        assert result["summary_status"] == "pending"

    def test_get_content(self, cache):
        """Test that get_content returns full content."""
        url = "http://example.com"
        content = "Full content here"

        cache.cache_url(
            url=url,
            content=content,
            title="Title",
            links=[],
            trigger_summarization=False,
        )

        result = cache.get_content(url)
        assert result == content

    def test_cleanup_expired_removes_old_entries(self, cache):
        """Test that cleanup_expired removes expired entries."""
        from datetime import datetime, timedelta
        import sqlite3

        # Manually insert an expired entry
        url = "http://cleanup.example.com"
        url_hash = cache._url_hash(url)
        expired_time = (datetime.now() - timedelta(hours=1)).isoformat()

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
                expired_time,  # expires_at in the past
                "hash",
                expired_time,
                expired_time,
            ),
        )
        conn.commit()
        conn.close()

        # Cleanup should remove expired entry
        deleted = cache.cleanup_expired()
        assert deleted == 1

    def test_get_cache_stats(self, cache):
        """Test that get_cache_stats returns correct statistics."""
        # Add some entries
        cache.cache_url(
            url="http://example1.com",
            content="Content 1",
            title="Title 1",
            links=[],
            trigger_summarization=False,
        )
        cache.cache_url(
            url="http://example2.com",
            content="Content 2",
            title="Title 2",
            links=[],
            trigger_summarization=False,
        )

        stats = cache.get_cache_stats()
        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2
        assert stats["expired_entries"] == 0

    @patch("asky.summarization._summarize_content")
    def test_background_summarization_triggered(self, mock_summarize, cache):
        """Test that background summarization is triggered."""
        mock_summarize.return_value = "Test summary"

        cache.cache_url(
            url="http://example.com",
            content="Content to summarize",
            title="Title",
            links=[],
            trigger_summarization=True,
        )

        # Wait for background task
        time.sleep(0.5)

        # Check that summary was saved
        cached = cache.get_cached("http://example.com")
        # Summary might be completed or still processing depending on timing
        assert cached["summary_status"] in ["processing", "completed", "failed"]

    def test_url_hash_consistency(self, cache):
        """Test that URL hashing is consistent."""
        url = "http://example.com/path?query=1"
        hash1 = cache._url_hash(url)
        hash2 = cache._url_hash(url)
        assert hash1 == hash2

    def test_content_hash_detects_changes(self, cache):
        """Test that content hash detects changes."""
        hash1 = cache._content_hash("Content 1")
        hash2 = cache._content_hash("Content 2")
        hash3 = cache._content_hash("Content 1")

        assert hash1 != hash2
        assert hash1 == hash3


class TestResearchCacheSingleton:
    """Tests for ResearchCache singleton behavior."""

    def test_singleton_returns_same_instance(self, tmp_path):
        """Test that ResearchCache returns the same instance."""
        from asky.research.cache import ResearchCache

        ResearchCache._instance = None

        db_path = str(tmp_path / "singleton.db")
        cache1 = ResearchCache(db_path=db_path)
        cache2 = ResearchCache()

        assert cache1 is cache2
        cache1.shutdown()


class TestResearchFindings:
    """Tests for research findings (memory) functionality."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create a fresh ResearchCache instance for each test."""
        from asky.research.cache import ResearchCache

        ResearchCache._instance = None

        db_path = str(tmp_path / "test_findings.db")
        cache = ResearchCache(db_path=db_path, ttl_hours=24, summarization_workers=1)
        yield cache
        cache.shutdown()

    def test_findings_table_created(self, cache):
        """Test that research_findings table is created."""
        conn = sqlite3.connect(cache.db_path)
        c = conn.cursor()

        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='research_findings'"
        )
        assert c.fetchone() is not None
        conn.close()

    def test_save_finding_basic(self, cache):
        """Test saving a basic finding."""
        finding_id = cache.save_finding(
            finding_text="Climate change is causing sea levels to rise."
        )

        assert finding_id > 0

        # Verify it was saved
        finding = cache.get_finding(finding_id)
        assert finding is not None
        assert finding["finding_text"] == "Climate change is causing sea levels to rise."

    def test_save_finding_with_metadata(self, cache):
        """Test saving a finding with full metadata."""
        finding_id = cache.save_finding(
            finding_text="Python 3.12 introduced new performance improvements.",
            source_url="https://python.org/news",
            source_title="Python Release Notes",
            tags=["python", "performance", "3.12"],
            session_id="session123",
        )

        finding = cache.get_finding(finding_id)

        assert finding["source_url"] == "https://python.org/news"
        assert finding["source_title"] == "Python Release Notes"
        assert finding["tags"] == ["python", "performance", "3.12"]
        assert finding["session_id"] == "session123"

    def test_get_finding_not_found(self, cache):
        """Test getting a non-existent finding."""
        result = cache.get_finding(99999)
        assert result is None

    def test_get_all_findings_empty(self, cache):
        """Test getting findings when none exist."""
        findings = cache.get_all_findings()
        assert findings == []

    def test_get_all_findings_returns_recent_first(self, cache):
        """Test that findings are returned most recent first."""
        cache.save_finding(finding_text="First finding")
        cache.save_finding(finding_text="Second finding")
        cache.save_finding(finding_text="Third finding")

        findings = cache.get_all_findings()

        assert len(findings) == 3
        assert findings[0]["finding_text"] == "Third finding"
        assert findings[2]["finding_text"] == "First finding"

    def test_get_all_findings_respects_limit(self, cache):
        """Test that limit parameter works."""
        for i in range(10):
            cache.save_finding(finding_text=f"Finding {i}")

        findings = cache.get_all_findings(limit=3)
        assert len(findings) == 3

    def test_get_all_findings_filter_by_session(self, cache):
        """Test filtering findings by session."""
        cache.save_finding(finding_text="Session A finding", session_id="session_a")
        cache.save_finding(finding_text="Session B finding", session_id="session_b")
        cache.save_finding(finding_text="Another A finding", session_id="session_a")

        findings = cache.get_all_findings(session_id="session_a")

        assert len(findings) == 2
        for f in findings:
            assert f["session_id"] == "session_a"

    def test_delete_finding(self, cache):
        """Test deleting a finding."""
        finding_id = cache.save_finding(finding_text="To be deleted")

        # Verify it exists
        assert cache.get_finding(finding_id) is not None

        # Delete it
        result = cache.delete_finding(finding_id)
        assert result is True

        # Verify it's gone
        assert cache.get_finding(finding_id) is None

    def test_delete_finding_not_found(self, cache):
        """Test deleting a non-existent finding."""
        result = cache.delete_finding(99999)
        assert result is False

    def test_update_finding_embedding(self, cache):
        """Test updating a finding's embedding."""
        finding_id = cache.save_finding(finding_text="Test finding")

        # Initially no embedding
        finding = cache.get_finding(finding_id)
        assert finding["has_embedding"] is False

        # Update with embedding
        import struct
        fake_embedding = struct.pack("3f", 0.1, 0.2, 0.3)
        result = cache.update_finding_embedding(
            finding_id=finding_id,
            embedding=fake_embedding,
            model="test-model",
        )

        assert result is True

        # Verify embedding is set
        finding = cache.get_finding(finding_id)
        assert finding["has_embedding"] is True
        assert finding["embedding_model"] == "test-model"

    def test_get_findings_count(self, cache):
        """Test getting the total findings count."""
        assert cache.get_findings_count() == 0

        cache.save_finding(finding_text="Finding 1")
        cache.save_finding(finding_text="Finding 2")

        assert cache.get_findings_count() == 2

    def test_save_finding_with_empty_tags(self, cache):
        """Test saving a finding with empty tags list."""
        finding_id = cache.save_finding(
            finding_text="Finding with no tags",
            tags=[],
        )

        finding = cache.get_finding(finding_id)
        assert finding["tags"] == []

    def test_save_finding_with_none_tags(self, cache):
        """Test saving a finding with None tags."""
        finding_id = cache.save_finding(
            finding_text="Finding with None tags",
            tags=None,
        )

        finding = cache.get_finding(finding_id)
        assert finding["tags"] == []

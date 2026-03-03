"""Tests for the research tools module."""

from unittest.mock import patch, MagicMock

import pytest


class TestExtractLinks:
    """Tests for extract_links tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    @pytest.fixture
    def mock_fetch_document(self):
        """Mock shared URL retrieval helper."""
        with patch("asky.research.tools.fetch_url_document") as mock:
            yield mock

    def test_extract_links_no_urls(self):
        """Test that missing URLs returns error."""
        from asky.research.tools import execute_extract_links

        result = execute_extract_links({})
        assert "error" in result

        result = execute_extract_links({"urls": []})
        assert "error" in result

    def test_extract_links_from_cache(self, mock_cache):
        """Test extracting links from cached content."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [{"text": "Link 1", "href": "http://link1.com"}],
        }

        result = execute_extract_links({"urls": ["http://example.com"]})

        assert "http://example.com" in result
        assert result["http://example.com"]["cached"] is True
        assert len(result["http://example.com"]["links"]) == 1

    def test_extract_links_fetches_fresh(self, mock_cache, mock_fetch_document):
        """Test fetching and caching fresh content."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = None
        mock_cache.cache_url.return_value = 1

        mock_fetch_document.return_value = {
            "error": None,
            "content": "Main content",
            "title": "Title",
            "links": [{"text": "Link", "href": "http://link.com"}],
        }

        with patch("asky.research.tools._try_embed_links", return_value=False):
            result = execute_extract_links({"urls": ["http://example.com"]})

        assert "http://example.com" in result
        assert result["http://example.com"]["cached"] is False
        mock_cache.cache_url.assert_called_once()

    def test_extract_links_handles_fetch_error(self, mock_cache, mock_fetch_document):
        """Test handling of fetch errors."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = None
        mock_fetch_document.return_value = {
            "error": "Network error",
            "content": "",
            "title": "",
            "links": [],
        }

        result = execute_extract_links({"urls": ["http://example.com"]})

        assert "http://example.com" in result
        assert "error" in result["http://example.com"]

    def test_extract_links_supports_single_url(self, mock_cache):
        """Test that single 'url' parameter works."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [],
        }

        result = execute_extract_links({"url": "http://example.com"})

        assert "http://example.com" in result

    def test_extract_links_deduplicates_urls(self, mock_cache):
        """Test that duplicate URLs are deduplicated."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [],
        }

        result = execute_extract_links(
            {"urls": ["http://example.com", "http://example.com"]}
        )

        # Should only process once
        assert len(result) == 1

    def test_extract_links_preserves_input_order(self, mock_cache):
        """Test that URL deduplication preserves first-seen order."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [],
        }

        result = execute_extract_links(
            {"urls": ["http://b.com", "http://a.com", "http://b.com"]}
        )

        assert list(result.keys()) == ["http://b.com", "http://a.com"]

    def test_extract_links_limits_results(self, mock_cache):
        """Test that max_links limits results."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [{"text": f"Link {i}", "href": f"http://link{i}.com"} for i in range(100)],
        }

        result = execute_extract_links({"urls": ["http://example.com"], "max_links": 10})

        assert len(result["http://example.com"]["links"]) == 10

    def test_extract_links_rejects_local_targets(self):
        """Local filesystem URLs should be rejected."""
        from asky.research.tools import execute_extract_links

        result = execute_extract_links({"urls": ["local:///tmp/corpus/doc.txt"]})

        assert "local:///tmp/corpus/doc.txt" in result
        assert "Local filesystem targets are not supported" in result["local:///tmp/corpus/doc.txt"]["error"]

    def test_extract_links_with_query_ranking(self, mock_cache):
        """Test that query triggers relevance ranking."""
        from asky.research.tools import execute_extract_links

        mock_cache.get_cached.return_value = {
            "id": 1,
            "links": [
                {"text": "AI Article", "href": "http://ai.com"},
                {"text": "Weather", "href": "http://weather.com"},
            ],
        }

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.rank_links_by_relevance.return_value = [
                ({"text": "AI Article", "href": "http://ai.com"}, 0.95)
            ]
            mock_vs.return_value = mock_store

            with patch("asky.research.tools._try_embed_links", return_value=True):
                result = execute_extract_links(
                    {"urls": ["http://example.com"], "query": "artificial intelligence"}
                )

        # Should have relevance scores
        links = result["http://example.com"]["links"]
        assert len(links) == 1
        assert links[0].get("relevance") is not None


class TestGetLinkSummaries:
    """Tests for get_link_summaries tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_get_summaries_no_urls(self):
        """Test that missing URLs returns error."""
        from asky.research.tools import execute_get_link_summaries

        result = execute_get_link_summaries({})
        assert "error" in result

    def test_get_summaries_not_cached(self, mock_cache):
        """Test handling of non-cached URLs."""
        from asky.research.tools import execute_get_link_summaries

        mock_cache.get_summary.return_value = None

        result = execute_get_link_summaries({"urls": ["http://example.com"]})

        assert "error" in result["http://example.com"]

    def test_get_summaries_completed(self, mock_cache):
        """Test getting completed summaries."""
        from asky.research.tools import execute_get_link_summaries

        mock_cache.get_summary.return_value = {
            "title": "Test Title",
            "summary": "This is a test summary.",
            "summary_status": "completed",
        }

        result = execute_get_link_summaries({"urls": ["http://example.com"]})

        assert result["http://example.com"]["summary"] == "This is a test summary."
        assert result["http://example.com"]["title"] == "Test Title"

    @patch("asky.research.tools._summarize_content")
    def test_get_summaries_on_demand(self, mock_summarize, mock_cache):
        """Test that summaries are generated on-demand if not completed."""
        from asky.research.tools import execute_get_link_summaries

        mock_cache.get_summary.return_value = {
            "title": "Test Title",
            "summary": None,
            "summary_status": "pending",
        }
        mock_cache.get_content.return_value = "Content to summarize"
        mock_cache.get_cache_id.return_value = 123
        mock_summarize.return_value = "Generated summary"

        result = execute_get_link_summaries({"urls": ["http://example.com"]})

        assert result["http://example.com"]["summary"] == "Generated summary"
        mock_summarize.assert_called_once()
        mock_cache._update_summary_status.assert_any_call(123, "processing")
        mock_cache._save_summary.assert_called_once_with(123, "Generated summary")

    @patch("asky.research.tools._summarize_content")
    def test_get_summaries_failed_retry(self, mock_summarize, mock_cache):
        """Test that failed summaries are retried on-demand."""
        from asky.research.tools import execute_get_link_summaries

        mock_cache.get_summary.return_value = {
            "title": "Test Title",
            "summary": None,
            "summary_status": "failed",
        }
        mock_cache.get_content.return_value = "Content to retry"
        mock_cache.get_cache_id.return_value = 456
        mock_summarize.return_value = "Retried summary"

        result = execute_get_link_summaries({"urls": ["http://example.com"]})

        assert result["http://example.com"]["summary"] == "Retried summary"
        mock_summarize.assert_called_once()

    def test_get_summaries_rejects_local_targets(self):
        """Local filesystem URLs should be rejected."""
        from asky.research.tools import execute_get_link_summaries

        result = execute_get_link_summaries({"urls": ["local:///tmp/corpus/doc.txt"]})

        assert "local:///tmp/corpus/doc.txt" in result
        assert "Local filesystem targets are not supported" in result["local:///tmp/corpus/doc.txt"]["error"]


class TestGetRelevantContent:
    """Tests for get_relevant_content tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_get_relevant_no_urls(self):
        """Test that missing URLs returns error."""
        from asky.research.tools import execute_get_relevant_content

        result = execute_get_relevant_content({"query": "test"})
        assert "error" in result

    def test_get_relevant_no_query(self):
        """Test that missing query returns error."""
        from asky.research.tools import execute_get_relevant_content

        result = execute_get_relevant_content({"urls": ["http://example.com"]})
        assert "error" in result

    def test_get_relevant_not_cached(self, mock_cache):
        """Test handling of non-cached URLs."""
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached.return_value = None

        result = execute_get_relevant_content(
            {"urls": ["http://example.com"], "query": "test"}
        )

        assert "error" in result["http://example.com"]

    def test_get_relevant_returns_chunks(self, mock_cache):
        """Test getting relevant content chunks."""
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached.return_value = {
            "id": 1,
            "content": "Test content for chunking",
            "title": "Test Title",
        }

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.has_chunk_embeddings.return_value = True
            mock_store.search_chunks.return_value = [
                ("Relevant chunk about architecture decisions", 0.95),
                ("Operational timeline and milestone details", 0.85),
            ]
            mock_vs.return_value = mock_store

            result = execute_get_relevant_content(
                {"urls": ["http://example.com"], "query": "test query"}
            )

        assert "chunks" in result["http://example.com"]
        assert len(result["http://example.com"]["chunks"]) == 2
        assert result["http://example.com"]["chunks"][0]["relevance"] == 0.95

    def test_get_relevant_generates_embeddings_if_missing(self, mock_cache):
        """Test that embeddings are generated if missing."""
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached.return_value = {
            "id": 1,
            "content": "Test content",
            "title": "Test Title",
        }

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.has_chunk_embeddings.return_value = False
            mock_store.store_chunk_embeddings.return_value = 2
            mock_store.search_chunks.return_value = []
            mock_vs.return_value = mock_store

            with patch("asky.research.tools.chunk_text") as mock_chunk:
                mock_chunk.return_value = [(0, "Chunk 1"), (1, "Chunk 2")]

                execute_get_relevant_content(
                    {"urls": ["http://example.com"], "query": "test"}
                )

                mock_store.store_chunk_embeddings.assert_called_once()

    def test_get_relevant_fallback_on_error(self, mock_cache):
        """Test fallback to content preview on error."""
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached.return_value = {
            "id": 1,
            "content": "Test content " * 100,
            "title": "Test Title",
        }

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.has_chunk_embeddings.side_effect = Exception("DB error")
            mock_vs.return_value = mock_store

            result = execute_get_relevant_content(
                {"urls": ["http://example.com"], "query": "test"}
            )

        assert result["http://example.com"]["fallback"] is True
        assert "content_preview" in result["http://example.com"]

    def test_get_relevant_rejects_local_targets(self):
        """Local filesystem URLs should be rejected."""
        from asky.research.tools import execute_get_relevant_content

        result = execute_get_relevant_content(
            {"urls": ["local:///tmp/corpus/doc.txt"], "query": "policy"}
        )

        assert "local:///tmp/corpus/doc.txt" in result
        assert "Local filesystem targets are not supported" in result["local:///tmp/corpus/doc.txt"]["error"]

    def test_get_relevant_accepts_corpus_cache_handles(self, mock_cache):
        """Safe corpus handles should resolve through cache IDs."""
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 7,
            "content": "Learning has friction even with fast chips.",
            "title": "Book Section",
        }

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.has_chunk_embeddings.return_value = True
            mock_store.search_chunks.return_value = [
                ("Learning remains a slog despite hardware gains", 0.91),
            ]
            mock_vs.return_value = mock_store

            result = execute_get_relevant_content(
                {"corpus_urls": ["corpus://cache/7"], "query": "learning slog"}
            )

        assert "chunks" in result["corpus://cache/7"]
        mock_cache.get_cached_by_id.assert_called_once_with(7)

    def test_get_relevant_reports_invalid_corpus_handle(self, mock_cache):
        """Malformed corpus handles should return actionable errors."""
        from asky.research.tools import execute_get_relevant_content

        result = execute_get_relevant_content(
            {"corpus_urls": ["corpus://cache/not-a-number"], "query": "test"}
        )

        assert "corpus://cache/not-a-number" in result
        assert "Invalid corpus handle format" in result["corpus://cache/not-a-number"][
            "error"
        ]
        mock_cache.get_cached_by_id.assert_not_called()

    def test_get_relevant_accepts_legacy_section_scoped_source(self, mock_cache):
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 247,
            "content": "body",
            "title": "Book",
        }

        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
        ):
            mock_index.return_value = {
                "sections": [{"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 84000}],
                "canonical_sections": [{"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 84000}],
                "alias_map": {"why-learning-014": "why-learning-038", "why-learning-038": "why-learning-038"},
            }
            mock_slice.return_value = {
                "content": "learning bottlenecks in classrooms " * 80,
                "section": {"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 84000},
                "requested_section_id": "why-learning-014",
                "resolved_section_id": "why-learning-038",
                "auto_promoted": True,
                "truncated": False,
                "available_chunks": 1,
            }

            result = execute_get_relevant_content(
                {
                    "urls": ["corpus://cache/247/why-learning-014"],
                    "query": "learning bottlenecks",
                }
            )

        payload = result["corpus://cache/247/why-learning-014"]
        assert "chunks" in payload
        assert payload["section"]["auto_promoted"] is True
        assert payload["section"]["resolved_section_id"] == "why-learning-038"

    def test_get_relevant_accepts_section_ref_argument(self, mock_cache):
        from asky.research.tools import execute_get_relevant_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 11,
            "content": "body",
            "title": "Book",
        }

        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
        ):
            mock_index.return_value = {
                "sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 6000}],
                "canonical_sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 6000}],
                "alias_map": {"learning-038": "learning-038"},
            }
            mock_slice.return_value = {
                "content": "learning friction evidence " * 50,
                "section": {"id": "learning-038", "title": "WHY LEARNING", "char_count": 6000},
                "requested_section_id": "learning-038",
                "resolved_section_id": "learning-038",
                "auto_promoted": False,
                "truncated": False,
                "available_chunks": 1,
            }
            result = execute_get_relevant_content(
                {
                    "corpus_urls": ["corpus://cache/11"],
                    "query": "learning",
                    "section_ref": "corpus://cache/11#section=learning-038",
                }
            )

        assert "chunks" in result["corpus://cache/11"]
        assert result["corpus://cache/11"]["section"]["resolved_section_id"] == "learning-038"


class TestGetFullContent:
    """Tests for get_full_content tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_get_full_no_urls(self):
        """Test that missing URLs returns error."""
        from asky.research.tools import execute_get_full_content

        result = execute_get_full_content({})
        assert "error" in result

    def test_get_full_not_cached(self, mock_cache):
        """Test handling of non-cached URLs."""
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached.return_value = None

        result = execute_get_full_content({"urls": ["http://example.com"]})

        assert "error" in result["http://example.com"]

    def test_get_full_returns_content(self, mock_cache):
        """Test getting full content."""
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached.return_value = {
            "content": "Full page content here",
            "title": "Test Title",
        }

        result = execute_get_full_content({"urls": ["http://example.com"]})

        assert result["http://example.com"]["content"] == "Full page content here"
        assert result["http://example.com"]["title"] == "Test Title"
        assert result["http://example.com"]["content_length"] == len(
            "Full page content here"
        )

    def test_get_full_empty_content(self, mock_cache):
        """Test handling of empty cached content."""
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached.return_value = {
            "content": "",
            "title": "Empty Page",
        }

        result = execute_get_full_content({"urls": ["http://example.com"]})

        assert "error" in result["http://example.com"]

    def test_get_full_rejects_local_targets(self):
        """Local filesystem URLs should be rejected."""
        from asky.research.tools import execute_get_full_content

        result = execute_get_full_content({"urls": ["local:///tmp/corpus/doc.txt"]})

        assert "local:///tmp/corpus/doc.txt" in result
        assert "Local filesystem targets are not supported" in result["local:///tmp/corpus/doc.txt"]["error"]

    def test_get_full_accepts_corpus_cache_handles(self, mock_cache):
        """Full content retrieval should support corpus cache handles."""
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 11,
            "content": "Complete text",
            "title": "Cached Local Document",
        }

        result = execute_get_full_content({"corpus_urls": ["corpus://cache/11"]})

        assert result["corpus://cache/11"]["content"] == "Complete text"
        mock_cache.get_cached_by_id.assert_called_once_with(11)

    def test_get_full_supports_section_scoped_legacy_source(self, mock_cache):
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 247,
            "content": "book content",
            "title": "Book",
        }

        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
        ):
            mock_index.return_value = {
                "sections": [{"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 5000}],
                "canonical_sections": [{"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 5000}],
                "alias_map": {"why-learning-014": "why-learning-038"},
            }
            mock_slice.return_value = {
                "content": "section body",
                "section": {"id": "why-learning-038", "title": "WHY LEARNING", "char_count": 5000},
                "requested_section_id": "why-learning-014",
                "resolved_section_id": "why-learning-038",
                "auto_promoted": True,
            }
            result = execute_get_full_content(
                {"urls": ["corpus://cache/247/why-learning-014"]}
            )

        payload = result["corpus://cache/247/why-learning-014"]
        assert payload["content"] == "section body"
        assert payload["section"]["resolved_section_id"] == "why-learning-038"

    def test_get_full_supports_section_ref_argument(self, mock_cache):
        from asky.research.tools import execute_get_full_content

        mock_cache.get_cached_by_id.return_value = {
            "id": 88,
            "content": "book content",
            "title": "Book",
        }

        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
        ):
            mock_index.return_value = {
                "sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 7000}],
                "canonical_sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 7000}],
                "alias_map": {"learning-038": "learning-038"},
            }
            mock_slice.return_value = {
                "content": "section body text",
                "section": {"id": "learning-038", "title": "WHY LEARNING", "char_count": 7000},
                "requested_section_id": "learning-038",
                "resolved_section_id": "learning-038",
                "auto_promoted": False,
            }
            result = execute_get_full_content(
                {
                    "corpus_urls": ["corpus://cache/88"],
                    "section_ref": "corpus://cache/88#section=learning-038",
                }
            )

        assert result["corpus://cache/88"]["section"]["section_ref"].endswith(
            "#section=learning-038"
        )


class TestSectionTools:
    """Tests for local section tools."""

    @pytest.fixture
    def mock_cache(self):
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_list_sections_rejects_web_sources(self):
        from asky.research.tools import execute_list_sections

        result = execute_list_sections({"source": "https://example.com/article"})

        assert "https://example.com/article" in result
        assert "Web URLs are not supported" in result["https://example.com/article"]["error"]

    def test_list_sections_accepts_corpus_handle(self, mock_cache):
        from asky.research.tools import execute_list_sections

        mock_cache.get_cached_by_id.return_value = {
            "id": 7,
            "title": "Book",
            "content": "CHAPTER ONE\\n\\ntext\\n\\nCHAPTER TWO\\n\\ntext",
        }

        with patch("asky.research.tools.build_section_index") as mock_index:
            mock_index.return_value = {
                "sections": [
                    {"id": "chapter-one-001", "title": "CHAPTER ONE", "char_count": 1200, "is_toc": True},
                    {"id": "chapter-two-002", "title": "CHAPTER TWO", "char_count": 900},
                ],
                "canonical_sections": [
                    {"id": "chapter-two-002", "title": "CHAPTER TWO", "char_count": 900},
                ],
            }
            result = execute_list_sections({"source": "corpus://cache/7"})

        assert result["corpus://cache/7"]["section_count"] == 1
        assert result["corpus://cache/7"]["all_section_count"] == 2
        assert result["corpus://cache/7"]["sections"][0]["section_ref"].endswith(
            "#section=chapter-two-002"
        )
        mock_cache.get_cached_by_id.assert_called_once_with(7)

    def test_list_sections_include_toc_returns_all_rows(self, mock_cache):
        from asky.research.tools import execute_list_sections

        mock_cache.get_cached_by_id.return_value = {
            "id": 7,
            "title": "Book",
            "content": "body",
        }
        with patch("asky.research.tools.build_section_index") as mock_index:
            mock_index.return_value = {
                "sections": [
                    {"id": "chapter-one-001", "title": "CHAPTER ONE", "char_count": 10, "is_toc": True},
                    {"id": "chapter-two-002", "title": "CHAPTER TWO", "char_count": 1200, "is_toc": False},
                ],
                "canonical_sections": [
                    {"id": "chapter-two-002", "title": "CHAPTER TWO", "char_count": 1200, "is_toc": False},
                ],
            }
            result = execute_list_sections(
                {"source": "corpus://cache/7", "include_toc": True}
            )

        assert result["corpus://cache/7"]["section_count"] == 2
        assert "is_toc" in result["corpus://cache/7"]["sections"][0]

    def test_summarize_section_rejects_non_handle_source_in_mixed_mode(self, mock_cache):
        from asky.research.tools import execute_summarize_section

        mock_cache.get_cached.return_value = {"content": "body", "title": "Book"}
        result = execute_summarize_section(
            {
                "source": "local:///tmp/book.epub",
                "research_source_mode": "mixed",
                "section_query": "Preface",
            }
        )

        assert "error" in result
        assert "only corpus handles are accepted" in result["error"]

    def test_summarize_section_returns_summary_for_strict_match(self, mock_cache):
        from asky.research.tools import execute_summarize_section

        mock_cache.get_cached_by_id.return_value = {
            "id": 9,
            "title": "Book",
            "content": "body",
        }

        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.match_section_strict") as mock_match,
            patch("asky.research.tools.slice_section_content") as mock_slice,
            patch("asky.research.tools._summarize_content", return_value="Deep summary"),
        ):
            mock_index.return_value = {
                "sections": [
                    {
                        "id": "learning-001",
                        "title": "WHY LEARNING IS STILL A SLOG",
                        "char_count": 4200,
                    }
                ]
            }
            mock_match.return_value = {
                "matched": True,
                "confidence": 0.96,
                "section": mock_index.return_value["sections"][0],
                "suggestions": [],
            }
            mock_slice.return_value = {
                "content": "section text " * 60,
                "truncated": False,
                "available_chunks": 1,
                "section": mock_index.return_value["sections"][0],
                "resolved_section_id": "learning-001",
                "requested_section_id": "learning-001",
                "auto_promoted": False,
            }
            result = execute_summarize_section(
                {
                    "source": "corpus://cache/9",
                    "section_query": "WHY LEARNING IS STILL A SLOG",
                    "detail": "balanced",
                }
            )

        assert result["summary"] == "Deep summary"
        assert result["section"]["id"] == "learning-001"

    def test_summarize_section_auto_promotes_alias_id(self, mock_cache):
        from asky.research.tools import execute_summarize_section

        mock_cache.get_cached_by_id.return_value = {
            "id": 247,
            "title": "Book",
            "content": "body",
        }
        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
            patch("asky.research.tools._summarize_content", return_value="Deep summary"),
        ):
            mock_index.return_value = {
                "sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 84000}],
                "canonical_sections": [{"id": "learning-038", "title": "WHY LEARNING", "char_count": 84000}],
                "alias_map": {"learning-014": "learning-038"},
            }
            mock_slice.return_value = {
                "content": "section text " * 60,
                "truncated": False,
                "available_chunks": 1,
                "section": mock_index.return_value["sections"][0],
                "requested_section_id": "learning-014",
                "resolved_section_id": "learning-038",
                "auto_promoted": True,
            }
            result = execute_summarize_section(
                {
                    "source": "corpus://cache/247",
                    "section_id": "learning-014",
                }
            )

        assert result["auto_promoted"] is True
        assert result["resolved_section_id"] == "learning-038"

    def test_summarize_section_rejects_tiny_resolved_section(self, mock_cache):
        from asky.research.tools import execute_summarize_section

        mock_cache.get_cached_by_id.return_value = {
            "id": 247,
            "title": "Book",
            "content": "body",
        }
        with (
            patch("asky.research.tools.build_section_index") as mock_index,
            patch("asky.research.tools.slice_section_content") as mock_slice,
        ):
            mock_index.return_value = {
                "sections": [{"id": "learning-014", "title": "WHY LEARNING", "char_count": 62}],
                "canonical_sections": [{"id": "learning-014", "title": "WHY LEARNING", "char_count": 62}],
                "alias_map": {"learning-014": "learning-014"},
            }
            mock_slice.return_value = {
                "content": "tiny text",
                "truncated": False,
                "available_chunks": 1,
                "section": mock_index.return_value["sections"][0],
                "requested_section_id": "learning-014",
                "resolved_section_id": "learning-014",
                "auto_promoted": False,
            }
            result = execute_summarize_section(
                {
                    "source": "corpus://cache/247",
                    "section_id": "learning-014",
                }
            )

        assert "too small to summarize reliably" in result["error"]


class TestToolSchemas:
    """Tests for tool schemas."""

    def test_research_tool_schemas_structure(self):
        """Test that tool schemas have correct structure."""
        from asky.research.tools import RESEARCH_TOOL_SCHEMAS

        expected_tools = [
            "extract_links",
            "get_link_summaries",
            "get_relevant_content",
            "get_full_content",
            "save_finding",
            "query_research_memory",
            "list_sections",
            "summarize_section",
        ]

        tool_names = [schema["name"] for schema in RESEARCH_TOOL_SCHEMAS]

        for expected in expected_tools:
            assert expected in tool_names

        for schema in RESEARCH_TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "parameters" in schema
            assert schema["parameters"]["type"] == "object"


class TestSaveFinding:
    """Tests for save_finding tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_save_finding_no_text(self):
        """Test that missing finding text returns error."""
        from asky.research.tools import execute_save_finding

        result = execute_save_finding({})
        assert "error" in result

        result = execute_save_finding({"finding": ""})
        assert "error" in result

        result = execute_save_finding({"finding": "   "})
        assert "error" in result

    def test_save_finding_basic(self, mock_cache):
        """Test saving a basic finding."""
        from asky.research.tools import execute_save_finding

        mock_cache.save_finding.return_value = 1

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.store_finding_embedding.return_value = True
            mock_vs.return_value = mock_store

            result = execute_save_finding({"finding": "Test finding"})

        assert result["status"] == "saved"
        assert result["finding_id"] == 1
        assert result["embedded"] is True

    def test_save_finding_with_metadata(self, mock_cache):
        """Test saving a finding with full metadata."""
        from asky.research.tools import execute_save_finding

        mock_cache.save_finding.return_value = 1

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.store_finding_embedding.return_value = True
            mock_vs.return_value = mock_store

            result = execute_save_finding({
                "finding": "Test finding",
                "source_url": "http://example.com",
                "source_title": "Example",
                "tags": ["test", "example"]
            })

        mock_cache.save_finding.assert_called_once_with(
            finding_text="Test finding",
            source_url="http://example.com",
            source_title="Example",
            tags=["test", "example"],
            session_id=None,
        )

    def test_save_finding_with_session_scope(self, mock_cache):
        """Test saving a finding with a provided session scope."""
        from asky.research.tools import execute_save_finding

        mock_cache.save_finding.return_value = 1

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.store_finding_embedding.return_value = True
            mock_vs.return_value = mock_store

            execute_save_finding(
                {
                    "finding": "Scoped finding",
                    "session_id": "session-42",
                }
            )

        mock_cache.save_finding.assert_called_once_with(
            finding_text="Scoped finding",
            source_url=None,
            source_title=None,
            tags=[],
            session_id="session-42",
        )

    def test_save_finding_embedding_fails(self, mock_cache):
        """Test that finding is saved even if embedding fails."""
        from asky.research.tools import execute_save_finding

        mock_cache.save_finding.return_value = 1

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_vs.side_effect = Exception("Embedding API unavailable")

            result = execute_save_finding({"finding": "Test finding"})

        assert result["status"] == "saved"
        assert result["embedded"] is False
        assert "without embedding" in result["note"]

    def test_save_finding_tags_as_string(self, mock_cache):
        """Test that string tags are converted to list."""
        from asky.research.tools import execute_save_finding

        mock_cache.save_finding.return_value = 1

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.store_finding_embedding.return_value = True
            mock_vs.return_value = mock_store

            execute_save_finding({
                "finding": "Test finding",
                "tags": "single-tag"
            })

        # Tags should be converted to list
        call_args = mock_cache.save_finding.call_args
        assert call_args.kwargs["tags"] == ["single-tag"]


class TestQueryResearchMemory:
    """Tests for query_research_memory tool."""

    @pytest.fixture
    def mock_cache(self):
        """Create a mock ResearchCache."""
        with patch("asky.research.tools._get_cache") as mock:
            cache = MagicMock()
            mock.return_value = cache
            yield cache

    def test_query_memory_no_query(self):
        """Test that missing query returns error."""
        from asky.research.tools import execute_query_research_memory

        result = execute_query_research_memory({})
        assert "error" in result

        result = execute_query_research_memory({"query": ""})
        assert "error" in result

    def test_query_memory_semantic_search(self):
        """Test semantic search of findings."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.search_findings.return_value = [
                (
                    {
                        "id": 1,
                        "finding_text": "Test finding",
                        "source_url": "http://example.com",
                        "source_title": "Example",
                        "tags": ["test"],
                        "created_at": "2024-01-01",
                    },
                    0.95,
                )
            ]
            mock_vs.return_value = mock_store

            result = execute_query_research_memory({"query": "test"})

        assert result["count"] == 1
        assert result["search_type"] == "semantic"
        assert result["findings"][0]["finding"] == "Test finding"
        assert result["findings"][0]["relevance"] == 0.95

    def test_query_memory_fallback_on_no_results(self, mock_cache):
        """Test fallback to recent findings when no semantic results."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.search_findings.return_value = []
            mock_vs.return_value = mock_store

            mock_cache.get_all_findings.return_value = [
                {
                    "finding_text": "Recent finding",
                    "source_url": None,
                    "source_title": None,
                    "tags": [],
                    "created_at": "2024-01-01",
                }
            ]

            result = execute_query_research_memory(
                {"query": "test", "session_id": "session-x"}
            )

        assert result["search_type"] == "recent"
        assert "No semantically relevant" in result["note"]
        assert result["findings"][0]["finding"] == "Recent finding"
        mock_cache.get_all_findings.assert_called_once_with(
            limit=10,
            session_id="session-x",
        )

    def test_query_memory_fallback_on_error(self, mock_cache):
        """Test fallback when embedding API fails."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_vs.side_effect = Exception("API unavailable")

            mock_cache.get_all_findings.return_value = [
                {
                    "finding_text": "Fallback finding",
                    "source_url": None,
                    "source_title": None,
                    "tags": [],
                    "created_at": "2024-01-01",
                }
            ]

            result = execute_query_research_memory({"query": "test"})

        assert result["search_type"] == "fallback"
        assert "unavailable" in result["note"]

    def test_query_memory_no_findings(self, mock_cache):
        """Test when no findings exist."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.search_findings.return_value = []
            mock_vs.return_value = mock_store

            mock_cache.get_all_findings.return_value = []

            result = execute_query_research_memory({"query": "test"})

        assert result["findings"] == []
        assert "No findings in research memory" in result["note"]

    def test_query_memory_respects_limit(self):
        """Test that limit parameter is passed through."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.search_findings.return_value = []
            mock_vs.return_value = mock_store

            execute_query_research_memory({"query": "test", "limit": 5})

            mock_store.search_findings.assert_called_with(
                "test",
                top_k=5,
                session_id=None,
            )

    def test_query_memory_passes_session_id_to_semantic_search(self):
        """Test that session_id is propagated to semantic memory search."""
        from asky.research.tools import execute_query_research_memory

        with patch("asky.research.tools.get_vector_store") as mock_vs:
            mock_store = MagicMock()
            mock_store.search_findings.return_value = []
            mock_vs.return_value = mock_store

            execute_query_research_memory(
                {"query": "test", "limit": 3, "session_id": "session-abc"}
            )

            mock_store.search_findings.assert_called_once_with(
                "test",
                top_k=3,
                session_id="session-abc",
            )


class TestSanitizeUrl:
    """Tests for URL sanitization."""

    def test_sanitize_removes_backslashes(self):
        """Test that backslashes are removed."""
        from asky.research.tools import _sanitize_url

        assert _sanitize_url("http://ex.com/a\\(b\\)") == "http://ex.com/a(b)"

    def test_sanitize_handles_none(self):
        """Test that None returns empty string."""
        from asky.research.tools import _sanitize_url

        assert _sanitize_url(None) == ""

    def test_sanitize_handles_empty(self):
        """Test that empty string returns empty."""
        from asky.research.tools import _sanitize_url

        assert _sanitize_url("") == ""

    def test_sanitize_preserves_normal_urls(self):
        """Test that normal URLs are preserved."""
        from asky.research.tools import _sanitize_url

        url = "https://example.com/path?query=1&other=2"
        assert _sanitize_url(url) == url

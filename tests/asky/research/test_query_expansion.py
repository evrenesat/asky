"""Tests for pre-search query expansion."""

import json
import pytest
from unittest.mock import MagicMock, patch

from asky.research.query_expansion import (
    expand_query_deterministic,
    expand_query_with_llm,
    MIN_QUERY_LENGTH_FOR_EXPANSION,
    MAX_SUB_QUERIES,
)


class TestQueryExpansion:
    """Test suite for query expansion module."""

    def test_expand_query_deterministic_short(self):
        """Short queries should return only original query."""
        query = "What is Python?"
        assert len(query) < MIN_QUERY_LENGTH_FOR_EXPANSION
        result = expand_query_deterministic(query)
        assert result == [query]

    def test_expand_query_deterministic_long(self):
        """Long queries should return multiple sub-queries including original."""
        query = "Explain the difference between asyncio, threading, and multiprocessing in Python with examples."
        assert len(query) >= MIN_QUERY_LENGTH_FOR_EXPANSION

        # We mock YAKE to ensure deterministic results for the test
        with patch("asky.research.query_expansion._get_yake_module") as mock_get:
            mock_yake = MagicMock()
            mock_get.return_value = mock_yake
            mock_extractor = MagicMock()
            mock_yake.KeywordExtractor.return_value = mock_extractor

            # 6 keywords, grouped by 3 -> 2 sub-queries + original = 3 total
            mock_extractor.extract_keywords.return_value = [
                ("asyncio", 0.1),
                ("threading", 0.1),
                ("multiprocessing", 0.1),
                ("python examples", 0.1),
                ("concurrency", 0.1),
                ("parallelism", 0.1),
            ]

            result = expand_query_deterministic(query)

            assert result[0] == query
            assert len(result) > 1
            assert "asyncio threading multiprocessing" in result[1]
            assert "python examples concurrency parallelism" in result[2]
            assert len(result) <= MAX_SUB_QUERIES

    def test_expand_query_with_llm_success(self):
        """LLM expansion should return original + sub-queries from JSON."""
        query = "How to build a query expansion module in Python using YAKE?"
        mock_client = MagicMock()
        mock_client.get_completion.return_value = {
            "content": '["query expansion Python", "YAKE keyword extraction"]'
        }

        result = expand_query_with_llm(query, mock_client, "gpt-small")

        assert result[0] == query
        assert "query expansion Python" in result
        assert "YAKE keyword extraction" in result
        assert len(result) == 3

    def test_expand_query_with_llm_malformed_json_fallback(self):
        """Malformed JSON should fallback to deterministic expansion."""
        query = "How to build a query expansion module in Python using YAKE?"
        mock_client = MagicMock()
        mock_client.get_completion.return_value = {
            "content": "Here are some sub-questions: 1. Q1, 2. Q2"  # Not JSON
        }

        with patch(
            "asky.research.query_expansion.expand_query_deterministic"
        ) as mock_det:
            mock_det.return_value = [query, "sub1"]
            result = expand_query_with_llm(query, mock_client, "gpt-small")

            mock_det.assert_called_once_with(query)
            assert result == [query, "sub1"]

    def test_expand_query_with_llm_error_fallback(self):
        """LLM error should fallback to deterministic expansion."""
        query = "How to build a query expansion module in Python using YAKE?"
        mock_client = MagicMock()
        mock_client.get_completion.side_effect = Exception("API error")

        with patch(
            "asky.research.query_expansion.expand_query_deterministic"
        ) as mock_det:
            mock_det.return_value = [query, "sub1"]
            result = expand_query_with_llm(query, mock_client, "gpt-small")

            mock_det.assert_called_once_with(query)
            assert result == [query, "sub1"]

    def test_expand_query_with_llm_caps_at_max(self):
        """Result count should be capped at MAX_SUB_QUERIES."""
        query = "Some very long research query that needs many sub-questions..."
        mock_client = MagicMock()
        # Returns 10 sub-questions
        mock_client.get_completion.return_value = {
            "content": json.dumps([f"Sub {i}" for i in range(10)])
        }

        result = expand_query_with_llm(
            query, mock_client, "gpt-small", max_sub_queries=4
        )

        assert len(result) == 4
        assert result[0] == query

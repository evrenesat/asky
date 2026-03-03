"""Tests for post-retrieval evidence extraction."""

import json
import pytest
from unittest.mock import MagicMock, patch

from asky.research.evidence_extraction import (
    extract_evidence_from_chunks,
    format_evidence_context,
    EvidenceFact,
    MAX_EVIDENCE_CHUNKS,
)


class TestEvidenceExtraction:
    """Test suite for evidence extraction module."""

    def test_extract_evidence_success(self):
        """Verify successful fact extraction from chunks."""
        chunks = [
            {
                "text": "Python was created by Guido van Rossum.",
                "url": "https://python.org",
                "title": "Python Home",
            },
            {
                "text": "Python 3.0 was released in 2008.",
                "url": "https://python.org/3",
                "title": "History",
            },
        ]
        query = "Who created Python and when was 3.0 released?"

        mock_response = {
            "content": json.dumps(
                [
                    {
                        "fact": "Python was created by Guido van Rossum",
                        "relevance": "high",
                    },
                    {"fact": "Python 3.0 released in 2008", "relevance": "medium"},
                ]
            )
        }

        with patch("asky.research.evidence_extraction.get_llm_msg") as mock_get_llm:
            mock_get_llm.return_value = mock_response

            # Using a mock llm_client for compatibility
            results = extract_evidence_from_chunks(
                chunks, query, MagicMock(), "gpt-small"
            )

            # Since we have 2 chunks, and mock returns 2 facts each time (simulated)
            # Actually, the mock is called for EACH chunk.
            # So 2 chunks * 2 facts = 4 facts.
            assert len(results) == 4
            assert results[0].relevance == "high"
            assert "Guido van Rossum" in results[0].fact
            assert results[0].source_title in ["Python Home", "History"]

    def test_extract_evidence_malformed_json(self):
        """Verify graceful handling of malformed LLM JSON."""
        chunks = [{"text": "Some text", "url": "url1"}]
        query = "What is X?"

        mock_response = {"content": "Not JSON at all"}

        with patch("asky.research.evidence_extraction.get_llm_msg") as mock_get_llm:
            mock_get_llm.return_value = mock_response

            results = extract_evidence_from_chunks(
                chunks, query, MagicMock(), "gpt-small"
            )
            assert results == []

    def test_extract_evidence_caps_chunks(self):
        """Verify extraction caps total chunks processed."""
        # 15 chunks
        chunks = [{"text": f"Text {i}", "url": f"url{i}"} for i in range(15)]
        query = "Query"

        mock_response = {"content": "[]"}

        with patch("asky.research.evidence_extraction.get_llm_msg") as mock_get_llm:
            mock_get_llm.return_value = mock_response

            extract_evidence_from_chunks(
                chunks, query, MagicMock(), "gpt-small", max_chunks=5
            )
            # Should be called 5 times
            assert mock_get_llm.call_count == 5

    def test_extract_evidence_empty_input(self):
        """Verify empty input returns empty results."""
        assert extract_evidence_from_chunks([], "query", None, "model") == []
        assert extract_evidence_from_chunks([{"text": "..."}], "", None, "model") == []

    def test_format_evidence_context(self):
        """Verify evidence context formatting."""
        evidence = [
            EvidenceFact(fact="Fact 1", relevance="high", source_title="Title 1"),
            EvidenceFact(
                fact="Fact 2", relevance="low", source_url="https://example.com"
            ),
        ]

        formatted = format_evidence_context(evidence)
        assert "Structured Evidence Extracted from Sources:" in formatted
        assert "[HIGH] Fact 1 (Source: Title 1)" in formatted
        assert "[LOW] Fact 2 (Source: https://example.com)" in formatted

    def test_format_evidence_context_empty(self):
        """Verify empty evidence list formatting."""
        assert format_evidence_context([]) is None

"""Tests for corpus-aware shortlist context extraction and query enrichment."""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from asky.research.corpus_context import (
    build_corpus_candidates,
    build_corpus_enriched_queries,
    extract_corpus_context,
)
from asky.research.shortlist_types import CorpusContext


class FakeCache:
    """Stub ResearchCache that returns pre-configured content by target key."""

    def __init__(self, content_map: Optional[Dict[str, str]] = None):
        self._content_map = content_map or {}

    def get_content(self, url: str) -> Optional[str]:
        return self._content_map.get(url)


def _make_local_payload(
    ingested: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "enabled": bool(ingested),
        "ingested": ingested or [],
    }


def test_extract_corpus_context_empty_payload():
    result = extract_corpus_context(_make_local_payload(), cache=FakeCache())
    assert result is None


def test_extract_corpus_context_no_ingested_docs():
    payload = _make_local_payload(ingested=[])
    result = extract_corpus_context(payload, cache=FakeCache())
    assert result is None


def test_extract_corpus_context_single_doc():
    content = (
        "Machine Learning Fundamentals is a comprehensive guide covering "
        "supervised learning, unsupervised learning, neural networks, "
        "deep learning architectures, gradient descent optimization, "
        "and practical applications of artificial intelligence."
    )
    payload = _make_local_payload(
        ingested=[
            {
                "target": "local:///books/ml_fundamentals.pdf",
                "source_id": 42,
                "source_handle": "corpus://cache/42",
                "title": "Machine Learning Fundamentals",
                "content_chars": len(content),
            }
        ]
    )
    cache = FakeCache({"local:///books/ml_fundamentals.pdf": content})

    result = extract_corpus_context(payload, cache=cache)

    assert result is not None
    assert result.titles == ["Machine Learning Fundamentals"]
    assert result.source_handles == ["corpus://cache/42"]
    assert result.cache_ids == [42]
    assert len(result.keyphrases) > 0
    assert "local:///books/ml_fundamentals.pdf" in result.lead_texts


def test_extract_corpus_context_multi_doc():
    content_a = (
        "Advanced Python Programming covers decorators, metaclasses, "
        "async programming, type hints, and performance optimization "
        "techniques for building production-grade applications."
    )
    content_b = (
        "Database Systems: Design and Implementation discusses "
        "relational algebra, SQL query optimization, indexing strategies, "
        "transaction isolation levels, and distributed consensus protocols."
    )
    payload = _make_local_payload(
        ingested=[
            {
                "target": "local:///a.pdf",
                "source_id": 10,
                "source_handle": "corpus://cache/10",
                "title": "Advanced Python Programming",
                "content_chars": len(content_a),
            },
            {
                "target": "local:///b.pdf",
                "source_id": 11,
                "source_handle": "corpus://cache/11",
                "title": "Database Systems",
                "content_chars": len(content_b),
            },
        ]
    )
    cache = FakeCache(
        {"local:///a.pdf": content_a, "local:///b.pdf": content_b}
    )

    result = extract_corpus_context(payload, cache=cache)

    assert result is not None
    assert len(result.titles) == 2
    assert "Advanced Python Programming" in result.titles
    assert "Database Systems" in result.titles
    assert len(result.lead_texts) == 2
    assert len(result.keyphrases) > 0


def test_extract_corpus_context_cache_miss_still_returns_titles():
    payload = _make_local_payload(
        ingested=[
            {
                "target": "local:///missing.pdf",
                "source_id": 99,
                "source_handle": "corpus://cache/99",
                "title": "Missing Book",
                "content_chars": 0,
            }
        ]
    )
    cache = FakeCache()

    result = extract_corpus_context(payload, cache=cache)

    assert result is not None
    assert result.titles == ["Missing Book"]
    assert result.keyphrases == []
    assert result.lead_texts == {}


def test_build_corpus_enriched_queries_with_keyphrases():
    ctx = CorpusContext(
        titles=["Machine Learning Fundamentals"],
        keyphrases=["supervised learning", "neural networks", "deep learning"],
        lead_texts={"local:///ml.pdf": "content here"},
        source_handles=["corpus://cache/1"],
        cache_ids=[1],
    )

    queries = build_corpus_enriched_queries(ctx, "what is this book about?")

    assert len(queries) >= 2
    assert any("Machine Learning Fundamentals" in q for q in queries)
    assert any("supervised learning" in q for q in queries)
    assert any("what is this book about?" in q for q in queries)


def test_build_corpus_enriched_queries_no_keyphrases():
    ctx = CorpusContext(
        titles=["My Book"],
        keyphrases=[],
        lead_texts={},
        source_handles=[],
        cache_ids=[],
    )

    queries = build_corpus_enriched_queries(ctx, "summarize this")

    assert len(queries) >= 1
    assert any("My Book" in q for q in queries)


def test_build_corpus_enriched_queries_empty_user_query():
    ctx = CorpusContext(
        titles=["Data Science Handbook"],
        keyphrases=["statistics", "probability"],
        lead_texts={},
        source_handles=[],
        cache_ids=[],
    )

    queries = build_corpus_enriched_queries(ctx, "")

    assert len(queries) >= 1
    assert any("Data Science Handbook" in q for q in queries)


def test_build_corpus_candidates():
    ctx = CorpusContext(
        titles=["Book A", "Book B"],
        keyphrases=["topic one", "topic two"],
        lead_texts={
            "local:///a.pdf": "Content of book A about topic one and related subjects.",
            "local:///b.pdf": "Content of book B about topic two and more details.",
        },
        source_handles=["corpus://cache/1", "corpus://cache/2"],
        cache_ids=[1, 2],
    )

    candidates = build_corpus_candidates(ctx)

    assert len(candidates) == 2
    assert candidates[0].source_type == "corpus"
    assert candidates[0].url == "corpus://cache/1"
    assert candidates[0].title == "Book A"
    assert candidates[0].fetched_content == ctx.lead_texts["local:///a.pdf"]
    assert candidates[1].url == "corpus://cache/2"
    assert candidates[1].title == "Book B"


def test_build_corpus_candidates_empty_context():
    ctx = CorpusContext(
        titles=[],
        keyphrases=[],
        lead_texts={},
        source_handles=[],
        cache_ids=[],
    )

    candidates = build_corpus_candidates(ctx)
    assert candidates == []

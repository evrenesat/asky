"""Tests for pre-LLM source shortlisting."""

from typing import Any, Dict, List

from asky.research.source_shortlist import (
    build_search_query,
    extract_prompt_urls_and_query_text,
    format_shortlist_context,
    normalize_source_url,
    shortlist_prompt_sources,
)


class FakeEmbeddingClient:
    """Simple deterministic embedding stub for shortlist scoring tests."""

    def embed_single(self, text: str) -> List[float]:
        lowered = text.lower()
        if "ai" in lowered or "safety" in lowered:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_single(text) for text in texts]


def test_extract_prompt_urls_and_query_text():
    seed_urls, query_text = extract_prompt_urls_and_query_text(
        "Compare these https://example.com/a?x=1 and https://example.com/b."
    )
    assert seed_urls == ["https://example.com/a?x=1", "https://example.com/b"]
    assert query_text == "Compare these and"


def test_normalize_source_url_removes_tracking_params():
    normalized = normalize_source_url(
        "HTTPS://Example.com:443/news/?utm_source=test&b=2&a=1#section"
    )
    assert normalized == "https://example.com/news?a=1&b=2"


def test_build_search_query_prefers_keyphrases():
    query = build_search_query(
        "A long prompt body",
        ["ai safety", "model evals", "alignment"],
    )
    assert query == "ai safety model evals alignment"


def test_shortlist_prompt_sources_search_and_ranking(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_TOP_K", 2)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    def fake_search_executor(_args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "results": [
                {
                    "title": "AI Safety Benchmark",
                    "url": "https://docs.example.com/ai-safety",
                    "snippet": "benchmarking methods",
                },
                {
                    "title": "Garden Plants",
                    "url": "https://blog.example.com/plants",
                    "snippet": "watering tips",
                },
            ]
        }

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        if "ai-safety" in url:
            return {
                "title": "AI Safety Benchmark",
                "text": "AI safety methods and benchmark design details.",
                "date": "2026-01-15",
            }
        return {
            "title": "Garden Plants",
            "text": "Plant watering and soil management for home gardens.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Need sources about ai safety benchmark methods",
        research_mode=True,
        search_executor=fake_search_executor,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    assert payload["enabled"] is True
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["url"] == "https://docs.example.com/ai-safety"
    assert payload["candidates"][0]["final_score"] >= payload["candidates"][1][
        "final_score"
    ]


def test_shortlist_prompt_sources_uses_seed_urls_without_search(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    search_calls = {"count": 0}

    def fake_search_executor(_args: Dict[str, Any]) -> Dict[str, Any]:
        search_calls["count"] += 1
        return {"results": []}

    def fake_fetch_executor(_url: str) -> Dict[str, Any]:
        return {
            "title": "Seed Source",
            "text": "Seed URL content with enough text for shortlist scoring.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Read https://example.com/seed and summarize this source.",
        research_mode=True,
        search_executor=fake_search_executor,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    assert search_calls["count"] == 0
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["source_type"] == "seed"


def test_format_shortlist_context():
    context = format_shortlist_context(
        {
            "candidates": [
                {
                    "rank": 1,
                    "title": "Example Source",
                    "final_score": 0.88,
                    "url": "https://example.com",
                    "why_selected": ["semantic_similarity=0.85"],
                    "snippet": "Example snippet text.",
                }
            ]
        }
    )
    assert "Example Source" in context
    assert "score=0.880" in context
    assert "semantic_similarity=0.85" in context

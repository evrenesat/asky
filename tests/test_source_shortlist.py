"""Tests for pre-LLM source shortlisting."""

from unittest.mock import MagicMock
from typing import Any, Dict, List
import requests

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


class CachedFailureEmbeddingClient:
    """Embedding client stub that reports a cached load failure."""

    def has_model_load_failure(self) -> bool:
        return True

    def embed_single(self, text: str) -> List[float]:  # noqa: ARG002
        raise AssertionError("embed_single should not be called after cached failure")

    def embed(self, texts: List[str]) -> List[List[float]]:  # noqa: ARG002
        raise AssertionError("embed should not be called after cached failure")


def test_extract_prompt_urls_and_query_text():
    seed_urls, query_text = extract_prompt_urls_and_query_text(
        "Compare these https://example.com/a?x=1 and https://example.com/b."
    )
    assert seed_urls == ["https://example.com/a?x=1", "https://example.com/b"]
    assert query_text == "Compare these and"


def test_extract_prompt_urls_and_query_text_detects_bare_domain_urls():
    seed_urls, query_text = extract_prompt_urls_and_query_text(
        "Summarize adamj.eu/tech/2023/09/18/git-dont-create-gitkeep/ in detail."
    )
    assert seed_urls == ["https://adamj.eu/tech/2023/09/18/git-dont-create-gitkeep/"]
    assert query_text == "Summarize in detail."


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
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
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


def test_shortlist_expands_seed_links_and_ranks_them(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_MAX_PAGES", 1)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINKS_PER_PAGE", 10)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_TOP_K", 4)

    search_calls = {"count": 0}

    def fake_search_executor(_args: Dict[str, Any]) -> Dict[str, Any]:
        search_calls["count"] += 1
        return {"results": []}

    def fake_seed_link_extractor(_url: str) -> Dict[str, Any]:
        return {
            "links": [
                {"text": "AI Safety Notes", "href": "https://example.com/ai-safety"},
                {"text": "Garden Tips", "href": "https://example.com/garden"},
            ]
        }

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        if "ai-safety" in url:
            return {
                "title": "AI Safety Notes",
                "text": "AI safety benchmark methods and evaluation details.",
                "date": None,
            }
        if "garden" in url:
            return {
                "title": "Garden Tips",
                "text": "Home garden watering and pruning advice for spring.",
                "date": None,
            }
        return {
            "title": "Seed Home",
            "text": "Index page that links to topic-specific resources.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Review https://example.com for ai safety benchmark sources.",
        research_mode=True,
        search_executor=fake_search_executor,
        seed_link_extractor=fake_seed_link_extractor,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    assert search_calls["count"] == 0
    assert len(payload["candidates"]) >= 2
    assert payload["candidates"][0]["url"] == "https://example.com/ai-safety"
    assert any(item["source_type"] == "seed_link" for item in payload["candidates"])
    assert payload["trace"]["processed_candidates"]
    assert payload["trace"]["selected_candidates"]


def test_shortlist_status_callback_and_stats(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    status_updates = []

    def fake_fetch_executor(_url: str) -> Dict[str, Any]:
        return {
            "title": "Seed Source",
            "text": "Seed URL content with enough text for shortlist scoring.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Read https://example.com/seed and summarize this source.",
        research_mode=True,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
        status_callback=status_updates.append,
    )

    assert payload["stats"]["timings_ms"]["total"] >= 0
    assert payload["stats"]["metrics"]["fetch_calls"] == 1
    assert payload["trace"]["processed_candidates"][0]["url"] == "https://example.com/seed"
    assert status_updates
    assert status_updates[-1].startswith("Shortlist: selected")


def test_shortlist_filters_seed_utility_links(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_MAX_PAGES", 1)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINKS_PER_PAGE", 10)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    def fake_seed_link_extractor(_url: str) -> Dict[str, Any]:
        return {
            "links": [
                {"text": "Sign In", "href": "https://profile.example.com/signin"},
                {"text": "Edition", "href": "https://example.com/preference/edition/eur"},
                {"text": "World", "href": "https://example.com/world"},
            ]
        }

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        return {
            "title": "World",
            "text": f"Enough content for {url} shortlist scoring.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Review https://example.com for world coverage.",
        research_mode=True,
        seed_link_extractor=fake_seed_link_extractor,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    urls = [candidate["url"] for candidate in payload["candidates"]]
    assert "https://example.com/world" in urls
    assert all("signin" not in url for url in urls)
    assert all("/preference/" not in url for url in urls)


def test_shortlist_dedupes_by_canonical_final_url(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    def fake_search_executor(_args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "results": [
                {"url": "https://example.com/preference/edition/eur", "title": "Edition"},
                {"url": "https://example.com/europe", "title": "Europe"},
            ]
        }

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        return {
            "title": "Europe",
            "text": f"Enough content for {url} shortlist scoring.",
            "date": None,
            "final_url": "https://example.com/europe",
        }

    payload = shortlist_prompt_sources(
        user_prompt="Need Europe coverage with no explicit links",
        research_mode=True,
        search_executor=fake_search_executor,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["normalized_url"] == "https://example.com/europe"
    assert payload["stats"]["metrics"]["fetch_canonical_dedupe_skips"] == 1


def test_same_domain_bonus_requires_relevance_signal(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS", False)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_SHORT_TEXT_THRESHOLD", 1)

    def fake_fetch_executor(_url: str) -> Dict[str, Any]:
        return {
            "title": "Seed Source",
            "text": "Completely unrelated content with no matching phrases.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Check https://example.com/seed for quantumfoo signal",
        research_mode=True,
        fetch_executor=fake_fetch_executor,
        embedding_client=CachedFailureEmbeddingClient(),
    )

    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["final_score"] == 0.0
    assert "same_domain_as_seed" not in payload["candidates"][0]["why_selected"]


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


def test_format_shortlist_context_includes_explicit_seed_url_beyond_top_k():
    payload = {
        "seed_urls": ["https://example.com/target"],
        "candidates": [
            {
                "rank": 1,
                "title": "Top 1",
                "final_score": 0.9,
                "url": "https://example.com/one",
                "why_selected": ["semantic_similarity=0.90"],
                "snippet": "s1",
            },
            {
                "rank": 2,
                "title": "Top 2",
                "final_score": 0.8,
                "url": "https://example.com/two",
                "why_selected": ["semantic_similarity=0.80"],
                "snippet": "s2",
            },
            {
                "rank": 3,
                "title": "Top 3",
                "final_score": 0.7,
                "url": "https://example.com/three",
                "why_selected": ["semantic_similarity=0.70"],
                "snippet": "s3",
            },
            {
                "rank": 4,
                "title": "Top 4",
                "final_score": 0.6,
                "url": "https://example.com/four",
                "why_selected": ["semantic_similarity=0.60"],
                "snippet": "s4",
            },
            {
                "rank": 5,
                "title": "Top 5",
                "final_score": 0.5,
                "url": "https://example.com/five",
                "why_selected": ["semantic_similarity=0.50"],
                "snippet": "s5",
            },
            {
                "rank": 6,
                "title": "Target URL",
                "final_score": 0.4,
                "url": "https://example.com/target",
                "why_selected": ["semantic_similarity=0.40"],
                "snippet": "target snippet",
            },
        ],
    }
    context = format_shortlist_context(payload)
    assert "https://example.com/target" in context
    assert "Target URL" in context


def test_shortlist_skips_embedding_when_cached_failure(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)

    def fake_fetch_executor(_url: str) -> Dict[str, Any]:
        return {
            "title": "Seed Source",
            "text": "Seed URL content with enough text for shortlist scoring.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Read https://example.com/seed and summarize this source.",
        research_mode=True,
        fetch_executor=fake_fetch_executor,
        embedding_client=CachedFailureEmbeddingClient(),
    )

    assert len(payload["candidates"]) == 1
    assert "embedding_skipped:cached_model_load_failure" in payload["warnings"]


def test_shortlist_includes_seed_url_documents_with_errors(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 10)

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        if "ok" in url:
            return {
                "title": "Working Seed",
                "text": "Enough content for a successful fetch.",
                "date": None,
            }
        return {
            "title": "",
            "text": "",
            "warning": "fetch_error:simulated failure",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Use https://example.com/ok and https://example.com/fail",
        research_mode=False,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    docs = payload["seed_url_documents"]
    assert [doc["url"] for doc in docs] == [
        "https://example.com/ok",
        "https://example.com/fail",
    ]
    assert docs[0]["title"] == "Working Seed"
    assert docs[0]["content"]
    assert docs[0]["error"] == ""
    assert docs[1]["error"] == "simulated failure"


def test_shortlist_fetches_all_seed_urls_even_beyond_scoring_cap(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MAX_FETCH_URLS", 1)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 10)

    seen_urls: List[str] = []

    def fake_fetch_executor(url: str) -> Dict[str, Any]:
        seen_urls.append(url)
        return {
            "title": f"Title for {url}",
            "text": f"Shortlist content for {url} with enough characters.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt=(
            "Summarize https://example.com/seed-one and https://example.com/seed-two."
        ),
        research_mode=False,
        fetch_executor=fake_fetch_executor,
        embedding_client=FakeEmbeddingClient(),
    )

    assert "https://example.com/seed-one" in seen_urls
    assert "https://example.com/seed-two" in seen_urls
    assert len(payload["seed_url_documents"]) == 2
    assert payload["fetched_count"] == len(payload["candidates"])


def test_shortlist_trace_callback_propagates_to_custom_executors(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )
    observed = {"search": False, "fetch": False}

    def fake_search_executor(
        _args: Dict[str, Any],
        trace_callback=None,
    ) -> Dict[str, Any]:
        observed["search"] = trace_callback is not None
        return {
            "results": [
                {
                    "title": "A",
                    "url": "https://example.com/a",
                    "snippet": "snippet",
                }
            ]
        }

    def fake_fetch_executor(
        _url: str,
        trace_callback=None,
    ) -> Dict[str, Any]:
        observed["fetch"] = trace_callback is not None
        return {
            "title": "A",
            "text": "Enough shortlist content to be included in scoring.",
            "date": None,
        }

    payload = shortlist_prompt_sources(
        user_prompt="Find sources about AI safety",
        research_mode=True,
        search_executor=fake_search_executor,
        fetch_executor=fake_fetch_executor,
        trace_callback=lambda _event: None,
    )

    assert payload["enabled"] is True
    assert observed["search"] is True
    assert observed["fetch"] is True


def test_shortlist_default_fetch_emits_transport_error_metadata(monkeypatch):
    from asky.research import source_shortlist as shortlist_mod
    from asky import retrieval as retrieval_mod

    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)
    monkeypatch.setattr(
        shortlist_mod, "SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED", False
    )

    mock_response = MagicMock()
    mock_response.status_code = 403
    http_error = requests.exceptions.HTTPError(response=mock_response)
    monkeypatch.setattr(retrieval_mod.requests, "get", MagicMock(side_effect=http_error))

    trace_events: List[Dict[str, Any]] = []
    payload = shortlist_prompt_sources(
        user_prompt="Summarize https://example.com/blocked",
        research_mode=True,
        trace_callback=trace_events.append,
    )

    assert payload["enabled"] is True
    assert any(
        event.get("kind") == "transport_error"
        and event.get("tool_name") == "shortlist"
        and event.get("operation") == "shortlist_fetch"
        and event.get("status_code") == 403
        for event in trace_events
    )


def test_shortlist_uses_research_cache(monkeypatch):
    """Verify that source_shortlist skips fetching if URL is in ResearchCache."""
    from asky.research import source_shortlist as shortlist_mod
    
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)
    monkeypatch.setattr(shortlist_mod, "SOURCE_SHORTLIST_MIN_CONTENT_CHARS", 20)
    
    mock_cache = MagicMock()
    # Simulate a cache hit
    mock_cache.get_cached.return_value = {
        "content": "This is cached content from a previous run.",
        "title": "Cached Title",
        "url": "https://example.com/cached"
    }
    
    # Mock ResearchCache constructor to return our mock
    monkeypatch.setattr("asky.research.cache.ResearchCache", lambda: mock_cache)
    
    # Mock fetch_url_document to ensure it's NOT called
    mock_fetch = MagicMock()
    monkeypatch.setattr("asky.research.source_shortlist.fetch_url_document", mock_fetch)
    
    payload = shortlist_prompt_sources(
        user_prompt="Summarize https://example.com/cached",
        research_mode=True
    )
    
    assert payload["enabled"] is True
    # Should find 1 candidate (the seed URL)
    assert len(payload["candidates"]) == 1
    # fetch_url_document should NOT have been called due to cache hit
    mock_fetch.assert_not_called()
    # Cache hit content should be present
    assert payload["candidates"][0]["title"] == "Cached Title"
    assert "cached content" in payload["candidates"][0]["snippet"]

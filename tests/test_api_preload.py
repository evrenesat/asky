"""Tests for API preload seed URL context behavior."""

from typing import Any, Dict

from asky.api.preload import (
    format_seed_url_context,
    run_preload_pipeline,
    seed_url_context_allows_direct_answer,
)


def test_format_seed_url_context_full_content_within_budget():
    shortlist_payload = {
        "seed_url_documents": [
            {
                "url": "https://example.com/a",
                "resolved_url": "https://example.com/a",
                "title": "Doc A",
                "content": "Short content A.",
                "error": "",
                "warning": "",
            }
        ]
    }

    context = format_seed_url_context(
        shortlist_payload=shortlist_payload,
        model_config={"context_size": 100},
        research_mode=False,
    )

    assert context is not None
    assert "Seed URL Content from Query:" in context
    assert "Delivery status: full_content" in context
    assert "Doc A" in context


def test_format_seed_url_context_summarizes_and_truncates(monkeypatch):
    import asky.api.preload as preload_mod

    monkeypatch.setattr(
        preload_mod,
        "summarize_seed_content",
        lambda content, max_output_chars: f"summary:{content[:24]}",
    )
    shortlist_payload = {
        "seed_url_documents": [
            {
                "url": "https://example.com/a",
                "resolved_url": "https://example.com/a",
                "title": "Doc A",
                "content": "A" * 60,
                "error": "",
                "warning": "",
            },
            {
                "url": "https://example.com/b",
                "resolved_url": "https://example.com/b",
                "title": "Doc B",
                "content": "B" * 60,
                "error": "",
                "warning": "",
            },
        ]
    }

    context = format_seed_url_context(
        shortlist_payload=shortlist_payload,
        model_config={"context_size": 10},
        research_mode=False,
    )

    assert context is not None
    assert "Delivery status: summarized_due_budget" in context
    assert "Delivery status: summary_truncated_due_budget" in context


def test_format_seed_url_context_marks_fetch_error():
    shortlist_payload = {
        "seed_url_documents": [
            {
                "url": "https://example.com/fail",
                "resolved_url": "https://example.com/fail",
                "title": "",
                "content": "",
                "error": "timeout while fetching",
                "warning": "fetch_error:timeout while fetching",
            }
        ]
    }

    context = format_seed_url_context(
        shortlist_payload=shortlist_payload,
        model_config={"context_size": 100},
        research_mode=False,
    )

    assert context is not None
    assert "Delivery status: fetch_error" in context
    assert "timeout while fetching" in context


def test_format_seed_url_context_skips_research_mode():
    context = format_seed_url_context(
        shortlist_payload={"seed_url_documents": [{"url": "https://example.com"}]},
        model_config={"context_size": 100},
        research_mode=True,
    )
    assert context is None


def test_run_preload_pipeline_includes_seed_context_before_shortlist(monkeypatch):
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def shortlist_executor(**_kwargs: Any) -> Dict[str, Any]:
        return {
            "enabled": True,
            "seed_url_documents": [
                {
                    "url": "https://example.com/a",
                    "resolved_url": "https://example.com/a",
                    "title": "Doc A",
                    "content": "Alpha",
                    "error": "",
                    "warning": "",
                }
            ],
            "candidates": [{"url": "https://example.com/candidate"}],
            "warnings": [],
            "stats": {},
            "trace": {"processed_candidates": [], "selected_candidates": []},
        }

    preload = run_preload_pipeline(
        query_text="Summarize https://example.com/a",
        research_mode=False,
        model_config={"source_shortlist_enabled": True, "context_size": 100},
        lean=False,
        preload_local_sources=False,
        preload_shortlist=True,
        shortlist_executor=shortlist_executor,
        shortlist_formatter=lambda payload: "SHORTLIST_CONTEXT"
        if payload.get("enabled")
        else "",
        shortlist_stats_builder=lambda payload, elapsed_ms: {
            "enabled": payload.get("enabled"),
            "elapsed_ms": elapsed_ms,
        },
    )

    assert preload.seed_url_context is not None
    assert preload.seed_url_direct_answer_ready is True
    assert preload.combined_context is not None
    assert preload.combined_context.index("Seed URL Content from Query:") < preload.combined_context.index(
        "SHORTLIST_CONTEXT"
    )


def test_seed_url_context_allows_direct_answer_false_on_errors():
    ready = seed_url_context_allows_direct_answer(
        shortlist_payload={
            "seed_url_documents": [
                {
                    "url": "https://example.com/a",
                    "content": "",
                    "error": "fetch failed",
                }
            ]
        },
        model_config={"context_size": 100},
        research_mode=False,
    )
    assert ready is False

"""Tests for API preload seed URL context behavior."""

from typing import Any, Dict

from asky.api.preload import (
    _collect_preloaded_source_urls,
    _collect_source_handles,
    format_seed_url_context,
    run_preload_pipeline,
    seed_url_context_allows_direct_answer,
    shortlist_enabled_for_request,
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
        shortlist_formatter=lambda payload: (
            "SHORTLIST_CONTEXT" if payload.get("enabled") else ""
        ),
        shortlist_stats_builder=lambda payload, elapsed_ms: {
            "enabled": payload.get("enabled"),
            "elapsed_ms": elapsed_ms,
        },
    )

    assert preload.seed_url_context is not None
    assert preload.seed_url_direct_answer_ready is True
    assert preload.combined_context is not None
    assert preload.combined_context.index(
        "Seed URL Content from Query:"
    ) < preload.combined_context.index("SHORTLIST_CONTEXT")


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


def test_run_preload_pipeline_forwards_trace_callback_to_shortlist_executor():
    observed = {"trace_forwarded": False}

    def shortlist_executor(**kwargs: Any) -> Dict[str, Any]:
        observed["trace_forwarded"] = kwargs.get("trace_callback") is not None
        return {
            "enabled": True,
            "seed_url_documents": [],
            "candidates": [],
            "warnings": [],
            "stats": {},
            "trace": {"processed_candidates": [], "selected_candidates": []},
        }

    preload = run_preload_pipeline(
        query_text="test query",
        research_mode=False,
        model_config={"source_shortlist_enabled": True, "context_size": 100},
        lean=False,
        preload_local_sources=False,
        preload_shortlist=True,
        shortlist_executor=shortlist_executor,
        shortlist_formatter=lambda _payload: "",
        shortlist_stats_builder=lambda payload, elapsed_ms: {
            "enabled": payload.get("enabled"),
            "elapsed_ms": elapsed_ms,
        },
        trace_callback=lambda _event: None,
    )

    assert preload.shortlist_enabled is True
    assert observed["trace_forwarded"] is True


def test_shortlist_enabled_for_request_honors_request_override_on():
    enabled, reason = shortlist_enabled_for_request(
        lean=False,
        model_config={"source_shortlist_enabled": False},
        research_mode=False,
        shortlist_override="on",
    )
    assert enabled is True
    assert reason == "request_override_on"


def test_shortlist_enabled_for_request_honors_request_override_off():
    enabled, reason = shortlist_enabled_for_request(
        lean=False,
        model_config={"source_shortlist_enabled": True},
        research_mode=True,
        shortlist_override="off",
    )
    assert enabled is False
    assert reason == "request_override_off"


def test_shortlist_enabled_global_general_overrides_mode_specific(monkeypatch):
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "GENERAL_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(preload_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(preload_mod, "SOURCE_SHORTLIST_ENABLE_STANDARD_MODE", False)

    enabled, reason = shortlist_enabled_for_request(
        lean=False,
        model_config={},
        research_mode=False,
    )
    assert enabled is True
    assert reason == "global_general"


def test_shortlist_enabled_global_general_false_overrides_mode_specific(monkeypatch):
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "GENERAL_SHORTLIST_ENABLED", False)
    monkeypatch.setattr(preload_mod, "SOURCE_SHORTLIST_ENABLED", True)
    monkeypatch.setattr(preload_mod, "SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE", True)

    enabled, reason = shortlist_enabled_for_request(
        lean=False,
        model_config={},
        research_mode=True,
    )
    assert enabled is False
    assert reason == "global_general"


def test_collect_preloaded_source_urls_prefers_local_source_handles():
    urls = _collect_preloaded_source_urls(
        local_payload={
            "ingested": [
                {
                    "target": "local:///tmp/books/book.epub",
                    "source_handle": "corpus://cache/77",
                }
            ]
        },
        shortlist_payload={},
    )

    assert urls == ["corpus://cache/77"]


def test_collect_source_handles_maps_handle_and_target():
    handle_map = _collect_source_handles(
        {
            "ingested": [
                {
                    "target": "local:///tmp/books/book.epub",
                    "source_handle": "corpus://cache/88",
                }
            ]
        }
    )

    assert handle_map["corpus://cache/88"] == "corpus://cache/88"
    assert handle_map["local:///tmp/books/book.epub"] == "corpus://cache/88"


def test_run_preload_pipeline_lean_mode_suppresses_memory_recall(monkeypatch):
    import asky.api.preload as preload_mod
    from unittest.mock import MagicMock

    # 1. Enable memory recall globally
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", True)

    # 2. Mock recall_memories to track calls
    mock_recall = MagicMock(return_value="Some memory")
    monkeypatch.setattr(preload_mod, "recall_memories", mock_recall)

    # 3. Suppress other parts of the pipeline to isolate memory check
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def mock_executor(**_kwargs):
        return {"enabled": False, "ingested": []}

    # Run in LEAN mode
    run_preload_pipeline(
        query_text="Hi",
        research_mode=False,
        model_config={},
        lean=True,  # Lean mode ACTIVE
        preload_local_sources=False,
        preload_shortlist=False,
        local_ingestion_executor=mock_executor,
    )

    # Verify memory recall was NOT called
    assert mock_recall.called is False

    # Run in NON-LEAN mode
    run_preload_pipeline(
        query_text="Hi",
        research_mode=False,
        model_config={},
        lean=False,  # Lean mode INACTIVE
        preload_local_sources=False,
        preload_shortlist=False,
        local_ingestion_executor=mock_executor,
    )

    # Verify memory recall WAS called
    assert mock_recall.called is True


def test_run_preload_pipeline_evidence_extraction_skip_on_high_quality_shortlist(
    monkeypatch,
):
    import asky.api.preload as preload_mod
    from unittest.mock import MagicMock

    monkeypatch.setattr(preload_mod, "RESEARCH_EVIDENCE_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    # Mock extract_evidence to track calls
    mock_extract = MagicMock(return_value=[])
    monkeypatch.setattr(preload_mod, "extract_evidence", mock_extract)

    def shortlist_executor_good(**_kwargs):
        return {
            "enabled": True,
            "candidates": [
                {"url": "1"},
                {"url": "2"},
                {"url": "3"},
            ],  # 3 sources -> good
            "fetched_count": 3,
            "stats": {"metrics": {"fetch_calls": 3}},
            "seed_url_documents": [],
        }

    run_preload_pipeline(
        query_text="Hi",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=False,
        preload_shortlist=True,
        shortlist_executor=shortlist_executor_good,
    )

    # Should be skipped because has_good_shortlist is True (count >= THRESHOLD (3))
    assert mock_extract.called is False


def test_run_preload_pipeline_evidence_extraction_runs_on_low_quality_shortlist(
    monkeypatch,
):
    import asky.api.preload as preload_mod
    from unittest.mock import MagicMock

    monkeypatch.setattr(preload_mod, "RESEARCH_EVIDENCE_EXTRACTION_ENABLED", True)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    # Mock extract_evidence to track calls
    mock_extract = MagicMock(return_value=[])
    monkeypatch.setattr(preload_mod, "extract_evidence", mock_extract)

    # Mock retrieval to return some chunks so extraction isn't empty-skipped
    monkeypatch.setattr(
        preload_mod,
        "get_relevant_content",
        lambda _payload: {"url1": {"chunks": [{"text": "chunk1"}]}},
    )

    def shortlist_executor_poor(**_kwargs):
        return {
            "enabled": True,
            "candidates": [{"url": "1"}, {"url": "2"}],  # 2 sources -> poor
            "fetched_count": 2,
            "stats": {"metrics": {"fetch_calls": 2}},
            "seed_url_documents": [],
        }

    run_preload_pipeline(
        query_text="Hi",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=False,
        preload_shortlist=True,
        shortlist_executor=shortlist_executor_poor,
    )

    # Should run because has_good_shortlist is False (count < THRESHOLD (3))
    assert mock_extract.called is True

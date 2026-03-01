"""Integration tests for one-shot document summarization feature.

Tests verify the end-to-end flow from preload pipeline through prompt modification,
ensuring classification flows correctly through the entire system.
"""

import pytest
from unittest.mock import MagicMock, patch
from asky.api.preload import run_preload_pipeline
from asky.core.prompts import append_research_guidance
from asky.research.query_classifier import QueryClassification


def test_classification_in_preload_pipeline(monkeypatch):
    """Test that classification runs in preload pipeline and populates result."""
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "QUERY_CLASSIFICATION_ENABLED", True)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def mock_local_executor(**kwargs):
        return {
            "enabled": True,
            "ingested": [
                {"target": "doc1.txt", "source_handle": "corpus://1"},
                {"target": "doc2.txt", "source_handle": "corpus://2"},
                {"target": "doc3.txt", "source_handle": "corpus://3"},
            ],
        }

    preload = run_preload_pipeline(
        query_text="Summarize the key points across all documents",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=True,
        preload_shortlist=False,
        local_ingestion_executor=mock_local_executor,
    )

    assert preload.query_classification is not None
    assert preload.query_classification.mode == "one_shot"
    assert preload.query_classification.corpus_document_count == 3
    assert preload.query_classification.has_summarization_keywords is True


def test_system_prompt_modification_one_shot(monkeypatch):
    """Test that system prompt is modified correctly for one-shot mode."""
    classification = QueryClassification(
        mode="one_shot",
        confidence=0.9,
        reasoning="summarization request with small corpus",
        has_summarization_keywords=True,
        is_small_corpus=True,
        is_vague_query=False,
        corpus_document_count=5,
        document_threshold=10,
        aggressive_mode=False,
    )

    base_prompt = "You are a helpful research assistant."

    result = append_research_guidance(
        system_prompt=base_prompt,
        corpus_preloaded=True,
        local_kb_hint_enabled=True,
        section_tools_enabled=True,
        classification=classification,
    )

    assert "One-Shot Summarization Mode" in result
    assert "5 document(s)" in result
    assert "direct, comprehensive summary" in result
    assert "DO NOT ask clarifying questions" in result
    assert "Local Knowledge Base Guidance" in result
    assert "list_sections" in result
    assert base_prompt in result


def test_research_mode_preservation(monkeypatch):
    """Test that research mode behavior is preserved when classification returns research."""
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "QUERY_CLASSIFICATION_ENABLED", True)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def mock_local_executor(**kwargs):
        return {
            "enabled": True,
            "ingested": [
                {"target": f"doc{i}.txt", "source_handle": f"corpus://{i}"}
                for i in range(15)
            ],
        }

    preload = run_preload_pipeline(
        query_text="Summarize the documents",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=True,
        preload_shortlist=False,
        local_ingestion_executor=mock_local_executor,
    )

    assert preload.query_classification is not None
    assert preload.query_classification.mode == "research"
    assert preload.query_classification.corpus_document_count == 15
    assert preload.query_classification.is_small_corpus is False

    base_prompt = "You are a helpful research assistant."
    result = append_research_guidance(
        system_prompt=base_prompt,
        corpus_preloaded=True,
        classification=preload.query_classification,
    )

    assert "One-Shot Summarization Mode" not in result
    assert "pre-loaded" in result


def test_configuration_override_behavior(monkeypatch):
    """Test that force_research_mode configuration overrides classification."""
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "QUERY_CLASSIFICATION_ENABLED", True)
    monkeypatch.setattr(preload_mod, "QUERY_CLASSIFICATION_FORCE_RESEARCH_MODE", True)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def mock_local_executor(**kwargs):
        return {
            "enabled": True,
            "ingested": [
                {"target": "doc1.txt", "source_handle": "corpus://1"},
                {"target": "doc2.txt", "source_handle": "corpus://2"},
            ],
        }

    preload = run_preload_pipeline(
        query_text="Summarize the key points",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=True,
        preload_shortlist=False,
        local_ingestion_executor=mock_local_executor,
    )

    assert preload.query_classification is not None
    assert preload.query_classification.mode == "research"
    assert "force_research_mode" in preload.query_classification.reasoning


def test_backward_compatibility_classification_disabled(monkeypatch):
    """Test that disabling classification preserves existing behavior."""
    import asky.api.preload as preload_mod

    monkeypatch.setattr(preload_mod, "QUERY_CLASSIFICATION_ENABLED", False)
    monkeypatch.setattr(preload_mod, "USER_MEMORY_ENABLED", False)
    monkeypatch.setattr(preload_mod, "QUERY_EXPANSION_ENABLED", False)

    def mock_local_executor(**kwargs):
        return {
            "enabled": True,
            "ingested": [
                {"target": "doc1.txt", "source_handle": "corpus://1"},
            ],
        }

    preload = run_preload_pipeline(
        query_text="Summarize the documents",
        research_mode=True,
        model_config={},
        lean=False,
        preload_local_sources=True,
        preload_shortlist=False,
        local_ingestion_executor=mock_local_executor,
    )

    assert preload.query_classification is None

    base_prompt = "You are a helpful research assistant."
    result = append_research_guidance(
        system_prompt=base_prompt,
        corpus_preloaded=True,
        classification=None,
    )

    assert "One-Shot Summarization Mode" not in result
    assert "pre-loaded" in result

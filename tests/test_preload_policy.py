"""Unit tests for the preload shortlist policy engine."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from asky.api.preload_policy import (
    INTENT_AMBIGUOUS,
    INTENT_LOCAL,
    INTENT_WEB,
    SOURCE_DETERMINISTIC,
    SOURCE_INTERFACE_MODEL,
    SOURCE_FALLBACK,
    PreloadPolicyEngine,
    resolve_shortlist_intent,
)


def test_resolve_shortlist_intent_deterministic():
    """Verify deterministic intent classification patterns."""
    # Web intent
    assert resolve_shortlist_intent("What is the latest news?") == INTENT_WEB
    assert resolve_shortlist_intent("Check the weather in London") == INTENT_WEB
    assert resolve_shortlist_intent("Search for recent AI breakthroughs") == INTENT_WEB
    assert resolve_shortlist_intent("Browse http://example.com") == INTENT_WEB
    assert resolve_shortlist_intent("current stock prices") == INTENT_WEB

    # Local intent
    assert resolve_shortlist_intent("Summarize this document") == INTENT_LOCAL
    assert resolve_shortlist_intent("Find key points in the files") == INTENT_LOCAL
    assert resolve_shortlist_intent("Look at my local corpus") == INTENT_LOCAL
    assert resolve_shortlist_intent("analyze the pdf") == INTENT_LOCAL
    assert resolve_shortlist_intent("what is in these documents?") == INTENT_LOCAL

    # Ambiguous
    assert resolve_shortlist_intent("Hello") == INTENT_AMBIGUOUS
    assert resolve_shortlist_intent("What is 2+2?") == INTENT_AMBIGUOUS
    assert resolve_shortlist_intent("Tell me a joke") == INTENT_AMBIGUOUS

    # Mixed (ambiguous)
    assert (
        resolve_shortlist_intent("Latest news from my local documents")
        == INTENT_AMBIGUOUS
    )


def test_preload_policy_engine_deterministic_always_skips_local_only():
    """Verify research_source_mode=local_only always disables shortlist."""
    engine = PreloadPolicyEngine()
    decision = engine.decide("Latest news", research_source_mode="local_only")
    assert not decision.enabled
    assert decision.reason == "research_source_mode_local_only"
    assert decision.source == SOURCE_DETERMINISTIC
    assert decision.intent == INTENT_LOCAL


def test_preload_policy_engine_deterministic_web_local():
    """Verify deterministic decisions in policy engine."""
    engine = PreloadPolicyEngine()

    # Web intent
    decision = engine.decide("What is the latest news?")
    assert decision.enabled
    assert decision.reason == "deterministic_web_intent"
    assert decision.source == SOURCE_DETERMINISTIC
    assert decision.intent == INTENT_WEB

    # Local intent
    decision = engine.decide("Summarize these files")
    assert not decision.enabled
    assert decision.reason == "deterministic_local_intent"
    assert decision.source == SOURCE_DETERMINISTIC
    assert decision.intent == INTENT_LOCAL


@patch("asky.api.preload_policy.get_llm_msg")
@patch("asky.api.preload_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_preload_policy_engine_interface_model_success(mock_get_llm_msg):
    """Verify interface-model fallback on successful decision."""
    mock_get_llm_msg.return_value = {
        "content": json.dumps(
            {
                "shortlist_enabled": True,
                "reason": "semantic_web_intent",
                "intent": "web",
            }
        )
    }

    engine = PreloadPolicyEngine(model_alias="gpt4", system_prompt="Policy prompt")
    decision = engine.decide("Am I ambiguous enough?")

    assert decision.enabled
    assert decision.reason == "semantic_web_intent"
    assert decision.source == SOURCE_INTERFACE_MODEL
    assert decision.intent == INTENT_WEB


@patch("asky.api.preload_policy.get_llm_msg")
@patch("asky.api.preload_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_preload_policy_engine_interface_model_parse_fallback(mock_get_llm_msg):
    """Verify fail-safe off on interface model parse failure."""
    mock_get_llm_msg.return_value = {"content": "Not a JSON block"}

    engine = PreloadPolicyEngine(model_alias="gpt4", system_prompt="Policy prompt")
    decision = engine.decide("Am I ambiguous enough?")

    assert not decision.enabled
    assert "parse_failure" in decision.reason
    assert decision.source == SOURCE_FALLBACK
    assert decision.intent == INTENT_AMBIGUOUS


@patch("asky.api.preload_policy.get_llm_msg")
@patch("asky.api.preload_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_preload_policy_engine_interface_model_crash_fallback(mock_get_llm_msg):
    """Verify exception bubbles up if interface model crashes."""
    mock_get_llm_msg.side_effect = requests.exceptions.RequestException("API down")

    engine = PreloadPolicyEngine(model_alias="gpt4", system_prompt="Policy prompt")
    decision = engine.decide("Am I ambiguous enough?")

    assert not decision.enabled
    assert "interface_model_transport_error" in decision.reason
    assert decision.source == SOURCE_FALLBACK
    assert decision.intent == INTENT_AMBIGUOUS


def test_preload_policy_engine_no_model_fallback():
    """Verify fail-safe off when no planner is available."""
    # Ambiguous query but no model_alias provided
    engine = PreloadPolicyEngine(model_alias=None)
    decision = engine.decide("Hello")

    assert not decision.enabled
    assert decision.reason == "ambiguous_no_planner_fallback"
    assert decision.source == SOURCE_FALLBACK
    assert decision.intent == INTENT_AMBIGUOUS

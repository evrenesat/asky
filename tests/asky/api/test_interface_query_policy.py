"""Unit tests for the plain-query interface helper policy engine."""

import json
from unittest.mock import MagicMock, patch

import pytest
from asky.api.interface_query_policy import (
    InterfaceQueryPolicyDecision,
    InterfaceQueryPolicyEngine,
)


def test_interface_query_policy_engine_no_model_fallback():
    """Engine should return fallback decision when no model is configured."""
    engine = InterfaceQueryPolicyEngine(model_alias=None, system_prompt="test")
    decision = engine.decide("test query")
    assert decision.source == "fallback"
    assert "interface_model_not_configured" in decision.reason


@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_interface_query_policy_engine_success(mock_get_llm_msg):
    """Engine should parse valid JSON response correctly."""
    mock_get_llm_msg.return_value = {
        "content": json.dumps(
            {
                "shortlist_enabled": False,
                "web_tools_mode": "search_only",
                "prompt_enrichment": "enhanced query",
                "memory_action": {"scope": "global", "memory": "user likes python", "tags": ["pref"]},
                "reason": "minimal_context_needed",
            }
        )
    }

    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test prompt")
    decision = engine.decide("how to code?")

    assert decision.shortlist_enabled is False
    assert decision.web_tools_mode == "search_only"
    assert decision.prompt_enrichment == "enhanced query"
    assert decision.memory_action == {"scope": "global", "memory": "user likes python", "tags": ["pref"]}
    assert decision.reason == "minimal_context_needed"
    assert decision.source == "interface_model"


@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_interface_query_policy_engine_invalid_mode_fallback(mock_get_llm_msg):
    """Engine should fallback to 'full' if web_tools_mode is invalid."""
    mock_get_llm_msg.return_value = {
        "content": '{"web_tools_mode": "invalid_mode", "shortlist_enabled": true}'
    }

    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test prompt")
    decision = engine.decide("test")

    assert decision.web_tools_mode == "full"
    assert decision.shortlist_enabled is True


@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_interface_query_policy_engine_parse_fallback(mock_get_llm_msg):
    """Engine should return fallback on invalid JSON."""
    mock_get_llm_msg.return_value = {"content": "not a json"}

    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test prompt")
    decision = engine.decide("test")

    assert decision.source == "fallback"
    assert "interface_model_parse_failure" in decision.reason


@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_interface_query_policy_engine_transport_error(mock_get_llm_msg):
    """Engine should return fallback on LLM transport error."""
    mock_get_llm_msg.side_effect = Exception("API down")

    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test prompt")
    decision = engine.decide("test")

    assert decision.source == "fallback"
    assert "interface_model_transport_error" in decision.reason

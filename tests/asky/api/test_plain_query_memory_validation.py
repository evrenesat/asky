
import pytest
import json
from unittest.mock import MagicMock, patch
from asky.api.interface_query_policy import InterfaceQueryPolicyEngine

@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_memory_action_validation_requires_global_scope(mock_get_llm):
    # Case 1: scope is 'session' -> should be rejected (memory_action=None)
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {"memory": "user likes coffee", "scope": "session"},
            "reason": "test"
        })
    }
    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test")
    decision = engine.decide("query")
    assert decision.memory_action is None

    # Case 2: scope is 'global' -> should be accepted
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {"memory": "user likes tea", "scope": "global", "tags": ["pref"]},
            "reason": "test"
        })
    }
    decision = engine.decide("query")
    assert decision.memory_action == {"memory": "user likes tea", "scope": "global", "tags": ["pref"]}

    # Case 3: scope missing -> should be rejected
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {"memory": "user likes water"},
            "reason": "test"
        })
    }
    decision = engine.decide("query")
    assert decision.memory_action is None

@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_memory_action_sanitization_discards_extra_keys(mock_get_llm):
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {
                "memory": "fact", 
                "scope": "global", 
                "session_id": 123, 
                "extra": "bad"
            },
            "reason": "test"
        })
    }
    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test")
    decision = engine.decide("query")
    # Only allowed keys: memory, tags, scope
    assert "session_id" not in decision.memory_action
    assert "extra" not in decision.memory_action
    assert decision.memory_action["memory"] == "fact"
    assert decision.memory_action["scope"] == "global"
    assert decision.memory_action["tags"] == []

@patch("asky.api.interface_query_policy.get_llm_msg")
@patch("asky.api.interface_query_policy.MODELS", {"gpt4": {"id": "gpt-4"}})
def test_memory_action_tag_normalization(mock_get_llm):
    # Tags as string
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {"memory": "fact", "scope": "global", "tags": "a, b, "},
            "reason": "test"
        })
    }
    engine = InterfaceQueryPolicyEngine(model_alias="gpt4", system_prompt="test")
    decision = engine.decide("query")
    assert decision.memory_action["tags"] == ["a", "b"]

    # Tags as list with empty strings
    mock_get_llm.return_value = {
        "content": json.dumps({
            "memory_action": {"memory": "fact", "scope": "global", "tags": ["a", "", "b"]},
            "reason": "test"
        })
    }
    decision = engine.decide("query")
    assert decision.memory_action["tags"] == ["a", "b"]

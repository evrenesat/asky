"""Interface planner prompt and parsing behavior tests."""

from asky.config import MODELS
from asky.daemon.interface_planner import ACTION_QUERY, InterfacePlanner


def _any_model_alias() -> str:
    return next(iter(MODELS.keys()))


def test_planner_injects_command_reference_when_enabled(monkeypatch):
    captured = {}

    def _fake_get_llm(model_id, messages, use_tools, model_alias, **kwargs):
        captured["model_id"] = model_id
        captured["messages"] = messages
        captured["use_tools"] = use_tools
        captured["model_alias"] = model_alias
        return {
            "content": '{"action_type":"query","command_text":"","query_text":"hello"}'
        }

    monkeypatch.setattr("asky.daemon.interface_planner.get_llm_msg", _fake_get_llm)
    planner = InterfacePlanner(
        _any_model_alias(),
        system_prompt="BASE PROMPT",
        command_reference="COMMAND REF",
        include_command_reference=True,
    )

    action = planner.plan("hello")
    assert action.action_type == ACTION_QUERY
    assert action.query_text == "hello"
    system_content = captured["messages"][0]["content"]
    assert "BASE PROMPT" in system_content
    assert "Allowed remote command reference:" in system_content
    assert "COMMAND REF" in system_content
    assert captured["use_tools"] is False


def test_planner_skips_command_reference_when_disabled(monkeypatch):
    captured = {}

    def _fake_get_llm(model_id, messages, use_tools, model_alias, **kwargs):
        captured["messages"] = messages
        return {
            "content": '{"action_type":"query","command_text":"","query_text":"hello"}'
        }

    monkeypatch.setattr("asky.daemon.interface_planner.get_llm_msg", _fake_get_llm)
    planner = InterfacePlanner(
        _any_model_alias(),
        system_prompt="BASE PROMPT",
        command_reference="COMMAND REF",
        include_command_reference=False,
    )

    planner.plan("hello")
    system_content = captured["messages"][0]["content"]
    assert system_content == "BASE PROMPT"


def test_planner_invalid_json_falls_back_to_query(monkeypatch):
    def _fake_get_llm(model_id, messages, use_tools, model_alias, **kwargs):
        return {"content": "not-json"}

    monkeypatch.setattr("asky.daemon.interface_planner.get_llm_msg", _fake_get_llm)
    planner = InterfacePlanner(
        _any_model_alias(),
        system_prompt="BASE PROMPT",
        command_reference="",
        include_command_reference=True,
    )

    action = planner.plan("hello world")
    assert action.action_type == ACTION_QUERY
    assert action.query_text == "hello world"
    assert action.reason == "planner_parse_fallback"


def test_planner_parses_chat_action(monkeypatch):
    from asky.daemon.interface_planner import ACTION_CHAT

    def _fake_get_llm(model_id, messages, use_tools, model_alias, **kwargs):
        return {
            "content": '{"action_type":"chat","command_text":"","query_text":"hi there"}'
        }

    monkeypatch.setattr("asky.daemon.interface_planner.get_llm_msg", _fake_get_llm)
    planner = InterfacePlanner(
        _any_model_alias(),
        system_prompt="BASE PROMPT",
    )

    action = planner.plan("hi")
    assert action.action_type == ACTION_CHAT
    assert action.query_text == "hi there"

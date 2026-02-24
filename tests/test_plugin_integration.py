from __future__ import annotations

from unittest.mock import MagicMock, patch

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.api.types import PreloadResolution, SessionResolution
from asky.core.engine import ConversationEngine
from asky.core.registry import ToolRegistry
from asky.core.tool_registry_factory import (
    create_research_tool_registry,
    create_tool_registry,
)
from asky.plugins.hook_types import DaemonServerSpec
from asky.plugins.hooks import HookRegistry


class _Runtime:
    def __init__(self, hooks: HookRegistry):
        self.hooks = hooks

    def shutdown(self) -> None:
        return None


def test_tool_registry_build_hook_can_register_standard_tool():
    hooks = HookRegistry()

    def _register(payload):
        payload.registry.register(
            "plugin_echo",
            {
                "name": "plugin_echo",
                "description": "echo",
                "parameters": {"type": "object", "properties": {}},
            },
            lambda _args: {"ok": True},
        )

    hooks.register("TOOL_REGISTRY_BUILD", _register, plugin_name="plug")
    registry = create_tool_registry(hook_registry=hooks)

    assert "plugin_echo" in registry.get_tool_names()


def test_tool_registry_build_hook_can_register_research_tool():
    hooks = HookRegistry()

    def _register(payload):
        payload.registry.register(
            "plugin_research_tool",
            {
                "name": "plugin_research_tool",
                "description": "extra",
                "parameters": {"type": "object", "properties": {}},
            },
            lambda _args: {"ok": True},
        )

    hooks.register("TOOL_REGISTRY_BUILD", _register, plugin_name="plug")
    registry = create_research_tool_registry(hook_registry=hooks)

    assert "plugin_research_tool" in registry.get_tool_names()


@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution(research_mode=False, notices=[])),
)
def test_run_turn_emits_lifecycle_hooks(
    mock_resolve,
    mock_preload,
    mock_run_messages,
):
    hooks = HookRegistry()
    fired = []

    hooks.register(
        "SESSION_RESOLVED",
        lambda payload: fired.append("SESSION_RESOLVED"),
        plugin_name="plug",
    )
    hooks.register(
        "PRE_PRELOAD",
        lambda payload: fired.append("PRE_PRELOAD"),
        plugin_name="plug",
    )
    hooks.register(
        "POST_PRELOAD",
        lambda payload: fired.append("POST_PRELOAD"),
        plugin_name="plug",
    )
    hooks.register(
        "SYSTEM_PROMPT_EXTEND",
        lambda prompt: prompt + "\n\n[plugin prompt]",
        plugin_name="plug",
    )
    hooks.register(
        "TURN_COMPLETED",
        lambda payload: fired.append("TURN_COMPLETED"),
        plugin_name="plug",
    )

    client = AskyClient(
        AskyConfig(model_alias="gf"),
        plugin_runtime=_Runtime(hooks),
    )

    result = client.run_turn(AskyTurnRequest(query_text="hello", save_history=False))
    prepared_messages = mock_run_messages.call_args.args[0]

    assert result.final_answer == "Final"
    assert "[plugin prompt]" in prepared_messages[0]["content"]
    assert fired == [
        "SESSION_RESOLVED",
        "PRE_PRELOAD",
        "POST_PRELOAD",
        "TURN_COMPLETED",
    ]


def test_engine_and_registry_emit_llm_and_tool_hooks():
    hooks = HookRegistry()
    events = []

    hooks.register(
        "PRE_LLM_CALL",
        lambda payload: events.append("PRE_LLM_CALL"),
        plugin_name="plug",
    )
    hooks.register(
        "POST_LLM_RESPONSE",
        lambda payload: events.append("POST_LLM_RESPONSE"),
        plugin_name="plug",
    )

    def _mutate_tool_args(payload):
        payload.arguments["text"] = "patched"
        events.append("PRE_TOOL_EXECUTE")

    def _mutate_tool_result(payload):
        payload.result["post"] = "ok"
        events.append("POST_TOOL_EXECUTE")

    hooks.register("PRE_TOOL_EXECUTE", _mutate_tool_args, plugin_name="plug")
    hooks.register("POST_TOOL_EXECUTE", _mutate_tool_result, plugin_name="plug")

    registry = ToolRegistry(hook_registry=hooks)
    registry.register(
        "echo",
        {
            "name": "echo",
            "description": "echo",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        },
        lambda args: {"echo": args.get("text")},
    )

    engine = ConversationEngine(
        model_config={"id": "test", "alias": "test", "context_size": 2048},
        tool_registry=registry,
        hook_registry=hooks,
        max_turns=3,
    )

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]

    first = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "echo", "arguments": '{"text": "original"}'},
            }
        ],
    }
    second = {"role": "assistant", "content": "done"}

    with (
        patch("asky.core.engine.get_llm_msg", side_effect=[first, second]),
        patch("asky.core.engine.count_tokens", return_value=10),
    ):
        final_answer = engine.run(messages)

    assert final_answer == "done"
    assert events.count("PRE_LLM_CALL") == 2
    assert events.count("POST_LLM_RESPONSE") == 2
    assert events.count("PRE_TOOL_EXECUTE") == 1
    assert events.count("POST_TOOL_EXECUTE") == 1


def test_daemon_server_register_hook_collects_servers(monkeypatch):
    hooks = HookRegistry()

    hooks.register(
        "DAEMON_SERVER_REGISTER",
        lambda payload: payload.servers.append(
            DaemonServerSpec(name="extra", start=lambda: None, stop=lambda: None)
        ),
        plugin_name="plug",
    )

    from asky.daemon import service as daemon_service

    monkeypatch.setattr(daemon_service, "init_db", lambda: None)
    monkeypatch.setattr(daemon_service, "TranscriptManager", MagicMock())
    monkeypatch.setattr(daemon_service, "CommandExecutor", MagicMock())
    monkeypatch.setattr(daemon_service, "InterfacePlanner", MagicMock())
    monkeypatch.setattr(daemon_service, "VoiceTranscriber", MagicMock())
    monkeypatch.setattr(daemon_service, "ImageTranscriber", MagicMock())
    monkeypatch.setattr(daemon_service, "DaemonRouter", MagicMock())
    mock_client = MagicMock()
    monkeypatch.setattr(daemon_service, "AskyXMPPClient", MagicMock(return_value=mock_client))

    service = daemon_service.XMPPDaemonService(plugin_runtime=_Runtime(hooks))
    assert any(spec.name == "extra" for spec in service._plugin_servers)

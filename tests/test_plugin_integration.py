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
    from asky.plugins.hook_types import DaemonTransportSpec

    hooks = HookRegistry()

    hooks.register(
        "DAEMON_SERVER_REGISTER",
        lambda payload: payload.servers.append(
            DaemonServerSpec(name="extra", start=lambda: None, stop=lambda: None)
        ),
        plugin_name="plug",
    )
    hooks.register(
        "DAEMON_TRANSPORT_REGISTER",
        lambda payload: payload.transports.append(
            DaemonTransportSpec(name="mock", run=lambda: None, stop=lambda: None)
        ),
        plugin_name="mock_transport",
    )

    from asky.daemon import service as daemon_service

    monkeypatch.setattr(daemon_service, "init_db", lambda: None)

    service = daemon_service.DaemonService(plugin_runtime=_Runtime(hooks))
    assert any(spec.name == "extra" for spec in service._plugin_servers)


def test_tray_menu_register_hook_collects_plugin_entries():
    """TRAY_MENU_REGISTER hook passes status/action entry lists to subscribers."""
    from asky.daemon.tray_protocol import TrayPluginEntry
    from asky.plugins.hook_types import TRAY_MENU_REGISTER, TrayMenuRegisterContext

    hooks = HookRegistry()
    hooks.register(
        TRAY_MENU_REGISTER,
        lambda ctx: (
            ctx.status_entries.append(TrayPluginEntry(get_label=lambda: "s1")),
            ctx.action_entries.append(
                TrayPluginEntry(get_label=lambda: "a1", on_action=lambda: None)
            ),
        ),
        plugin_name="test_plugin",
    )

    status_entries = []
    action_entries = []
    ctx = TrayMenuRegisterContext(
        status_entries=status_entries,
        action_entries=action_entries,
        start_service=lambda: None,
        stop_service=lambda: None,
        is_service_running=lambda: False,
        on_error=lambda _: None,
    )
    hooks.invoke(TRAY_MENU_REGISTER, ctx)

    assert len(status_entries) == 1
    assert status_entries[0].get_label() == "s1"
    assert len(action_entries) == 1
    assert action_entries[0].get_label() == "a1"


def test_dependency_issue_recorded_for_disabled_dep(tmp_path):
    """PluginManager records DependencyIssue when a required dep is disabled."""
    import tomlkit

    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "base_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            },
            "dependent_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
                "dependencies": ["missing_dep"],
            },
            "missing_dep": {
                "enabled": False,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            },
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    issues = manager.get_dependency_issues()
    assert len(issues) == 1
    assert issues[0].plugin_name == "dependent_plugin"
    assert issues[0].dep_name == "missing_dep"
    assert issues[0].reason == "disabled"


def test_dependency_issue_recorded_for_unknown_dep(tmp_path):
    """PluginManager records DependencyIssue when a required dep is not in roster."""
    import tomlkit

    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "dependent_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
                "dependencies": ["nonexistent_plugin"],
            },
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    issues = manager.get_dependency_issues()
    assert len(issues) == 1
    assert issues[0].plugin_name == "dependent_plugin"
    assert issues[0].dep_name == "nonexistent_plugin"
    assert issues[0].reason == "not_found"


def test_enable_plugin_persists_to_toml(tmp_path):
    """enable_plugin() updates the in-memory manifest and writes plugins.toml."""
    import tomlkit

    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "my_plugin": {
                "enabled": False,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            }
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    result = manager.enable_plugin("my_plugin")
    assert result is True
    assert manager._manifests["my_plugin"].enabled is True

    written = tomlkit.loads(roster_path.read_text(encoding="utf-8"))
    assert written["plugin"]["my_plugin"]["enabled"] is True


def test_handle_dependency_issues_emits_warnings_for_non_interactive(
    tmp_path, monkeypatch
):
    """Non-interactive context: dependency issues become warning strings."""
    import tomlkit

    from asky.daemon.launch_context import LaunchContext, set_launch_context
    from asky.plugins.manager import PluginManager
    from asky.plugins.runtime import _handle_dependency_issues

    set_launch_context(LaunchContext.DAEMON_FOREGROUND)
    try:
        roster = {
            "plugin": {
                "dep_plugin": {
                    "enabled": False,
                    "module": "asky.plugins.base",
                    "class": "AskyPlugin",
                },
                "consumer_plugin": {
                    "enabled": True,
                    "module": "asky.plugins.base",
                    "class": "AskyPlugin",
                    "dependencies": ["dep_plugin"],
                },
            }
        }
        roster_path = tmp_path / "plugins.toml"
        roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

        manager = PluginManager(config_dir=tmp_path)
        manager.load_roster()

        warnings = _handle_dependency_issues(manager)
        assert len(warnings) == 1
        assert "consumer_plugin" in warnings[0]
        assert "dep_plugin" in warnings[0]
    finally:
        set_launch_context(LaunchContext.INTERACTIVE_CLI)


def test_daemon_runs_without_transport(monkeypatch):
    """Sidecar-only mode: no transport registered, daemon blocks on event until stop()."""
    import threading

    hooks = HookRegistry()
    started = []
    stopped = []

    hooks.register(
        "DAEMON_SERVER_REGISTER",
        lambda payload: payload.servers.append(
            DaemonServerSpec(
                name="sidecar",
                start=lambda: started.append(True),
                stop=lambda: stopped.append(True),
            )
        ),
        plugin_name="plug",
    )

    from asky.daemon import service as daemon_service

    monkeypatch.setattr(daemon_service, "init_db", lambda: None)

    service = daemon_service.DaemonService(plugin_runtime=_Runtime(hooks))
    assert service._transport is None

    def _run():
        service.run_foreground()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # Give run_foreground time to reach the wait()
    import time; time.sleep(0.05)
    assert service._running
    service.stop()
    t.join(timeout=2)
    assert not t.is_alive()
    assert started == [True]
    assert stopped == [True]

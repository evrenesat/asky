from __future__ import annotations

import pytest

from asky.plugins.hooks import HookRegistry


def test_hook_registration_order_priority_then_name_then_index():
    registry = HookRegistry()
    calls = []

    registry.register(
        "TOOL_REGISTRY_BUILD",
        lambda payload: calls.append("bravo"),
        plugin_name="bravo",
        priority=100,
    )
    registry.register(
        "TOOL_REGISTRY_BUILD",
        lambda payload: calls.append("alpha"),
        plugin_name="alpha",
        priority=100,
    )
    registry.register(
        "TOOL_REGISTRY_BUILD",
        lambda payload: calls.append("zero"),
        plugin_name="zeta",
        priority=10,
    )

    registry.invoke("TOOL_REGISTRY_BUILD", object())

    assert calls == ["zero", "alpha", "bravo"]


def test_invoke_chain_applies_transform_in_order():
    registry = HookRegistry()
    registry.register(
        "SYSTEM_PROMPT_EXTEND",
        lambda value: value + " + one",
        plugin_name="p1",
        priority=100,
    )
    registry.register(
        "SYSTEM_PROMPT_EXTEND",
        lambda value: value + " + two",
        plugin_name="p2",
        priority=100,
    )

    result = registry.invoke_chain("SYSTEM_PROMPT_EXTEND", "base")
    assert result == "base + one + two"


def test_hook_callback_error_isolated():
    registry = HookRegistry()
    calls = []

    def _boom(_payload):
        raise RuntimeError("boom")

    registry.register("TURN_COMPLETED", _boom, plugin_name="p1", priority=100)
    registry.register(
        "TURN_COMPLETED",
        lambda payload: calls.append("ok"),
        plugin_name="p2",
        priority=100,
    )

    registry.invoke("TURN_COMPLETED", object())
    assert calls == ["ok"]


def test_freeze_blocks_future_registration():
    registry = HookRegistry()
    registry.freeze()

    with pytest.raises(RuntimeError):
        registry.register(
            "TOOL_REGISTRY_BUILD",
            lambda payload: None,
            plugin_name="plugin",
        )

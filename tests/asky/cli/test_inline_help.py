from unittest.mock import patch, MagicMock

import asky.cli.inline_help as inline_help_mod
from asky.cli.inline_help import (
    _dedupe_and_sort_hints,
    _collect_builtin_pre_dispatch_hints,
    collect_pre_dispatch_hints,
    collect_post_turn_hints,
    mark_hints_seen_for_session,
    render_inline_hints,
)
from asky.plugins.base import CLIHint


class MockArgs:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_dedupe_and_sort_hints():
    hints = [
        CLIHint("id1", "Msg 1", priority=10),
        CLIHint("id2", "Msg 2", priority=20),
        CLIHint("id3", "Msg 3", priority=5),
        CLIHint("id2", "Msg 2 duplicate", priority=30),  # Higher priority for same id overrides
    ]

    seen = {"id1"}
    
    # id1 seen but it's per_invocation by default, so it's not filtered out unless frequency="per_session"
    res = _dedupe_and_sort_hints(hints, seen)
    
    assert len(res) == 2  # capped at MAX_INLINE_HINTS_PER_EMISSION=2
    # The sorted order should be id2 (priority 30), then id1 (priority 10) or id3 (priority 5)
    assert res[0].id == "id2"
    assert res[0].message == "Msg 2 duplicate"
    assert res[1].id == "id1"


def test_dedupe_filters_seen_per_session():
    hints = [
        CLIHint("id1", "Msg 1", priority=10, frequency="per_session"),
        CLIHint("id2", "Msg 2", priority=20),
    ]

    seen = {"id1"}
    
    res = _dedupe_and_sort_hints(hints, seen)
    
    assert len(res) == 1
    assert res[0].id == "id2"


def test_builtin_research_mode_hints():
    # local_only
    args = MockArgs(research=True, research_source_mode="local_only")
    hints = _collect_builtin_pre_dispatch_hints(args)
    assert len(hints) == 1
    assert hints[0].id == "research_local_only"
    
    # mixed
    args = MockArgs(research=True, research_source_mode="mixed")
    hints = _collect_builtin_pre_dispatch_hints(args)
    assert len(hints) == 1
    assert hints[0].id == "research_mixed"
    
    # web_only
    args = MockArgs(research=True, research_source_mode="web_only")
    hints = _collect_builtin_pre_dispatch_hints(args)
    assert len(hints) == 1
    assert hints[0].id == "research_web_only"
    
    # not research
    args = MockArgs(research=False)
    hints = _collect_builtin_pre_dispatch_hints(args)
    assert len(hints) == 0


def test_collect_pre_dispatch_hints_plugin():
    args = MockArgs(research=False)
    pm = MagicMock()
    pm.collect_cli_hint_contributions.return_value = [
        ("plugin_x", CLIHint("plugin_hint", "Hello from plugin", priority=100))
    ]
    
    hints = collect_pre_dispatch_hints(args, plugin_manager=pm)
    assert len(hints) == 1
    assert hints[0].id == "plugin_hint"
    pm.collect_cli_hint_contributions.assert_called_once()
    context = pm.collect_cli_hint_contributions.call_args[0][0]
    assert context.phase == "pre_dispatch"


def test_collect_post_turn_hints():
    args = MockArgs()
    turn_req = MagicMock()
    turn_res = MagicMock()
    
    def side_effect(hook_name, context):
        context.hints.append(CLIHint("post_turn_hint", "Wow", priority=80))

    hooks_mock = MagicMock()
    hooks_mock.invoke.side_effect = side_effect
    runtime_mock = MagicMock()
    runtime_mock.hooks = hooks_mock
    
    hints = collect_post_turn_hints(turn_req, turn_res, args, plugin_runtime=runtime_mock)
    
    assert len(hints) == 1
    assert hints[0].id == "post_turn_hint"
    hooks_mock.invoke.assert_called_once()


def test_per_session_hint_persisted_after_late_session_resolution(monkeypatch):
    seen_ids: set[str] = set()

    def fake_get_seen(_session_id):
        return set(seen_ids)

    def fake_mark_seen(_session_id, hint_ids):
        seen_ids.update(hint_ids)

    monkeypatch.setattr(inline_help_mod, "_get_seen_hint_ids", fake_get_seen)
    monkeypatch.setattr(inline_help_mod, "_mark_hints_as_seen", fake_mark_seen)

    console = MagicMock()
    hint = CLIHint(
        "research_local_only",
        "Research mode is local-only.",
        frequency="per_session",
    )

    # First invocation: no session id known yet, so hint is shown.
    rendered_first = render_inline_hints(console, [hint], session_id=None)
    assert [h.id for h in rendered_first] == ["research_local_only"]

    # Session id becomes available after turn completion; persist seen state.
    mark_hints_seen_for_session(42, rendered_first)

    # Next invocation in the same session: hint should now be suppressed.
    rendered_second = render_inline_hints(console, [hint], session_id=42)
    assert rendered_second == []

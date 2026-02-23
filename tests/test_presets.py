"""Tests for command preset expansion."""

from asky.cli.presets import expand_preset_invocation, list_presets_text


def test_expand_preset_positional_and_extra(monkeypatch):
    monkeypatch.setattr(
        "asky.cli.presets.COMMAND_PRESETS",
        {"deep": "--shortlist on summarize $1 then $2"},
    )

    expansion = expand_preset_invocation(r"\deep alpha beta gamma")
    assert expansion.matched is True
    assert expansion.error is None
    assert expansion.command_tokens == [
        "--shortlist",
        "on",
        "summarize",
        "alpha",
        "then",
        "beta",
        "gamma",
    ]


def test_expand_preset_all_args_token(monkeypatch):
    monkeypatch.setattr(
        "asky.cli.presets.COMMAND_PRESETS",
        {"daily": "Give me daily briefing about $*"},
    )
    expansion = expand_preset_invocation(r'\daily "machine learning" trends')
    assert expansion.matched is True
    assert expansion.error is None
    assert expansion.command_tokens == [
        "Give",
        "me",
        "daily",
        "briefing",
        "about",
        "machine learning",
        "trends",
    ]


def test_unknown_preset_error(monkeypatch):
    monkeypatch.setattr("asky.cli.presets.COMMAND_PRESETS", {})
    expansion = expand_preset_invocation(r"\missing foo")
    assert expansion.matched is True
    assert "Unknown preset" in str(expansion.error)


def test_presets_list_render(monkeypatch):
    monkeypatch.setattr(
        "asky.cli.presets.COMMAND_PRESETS",
        {"b": "second", "a": "first"},
    )
    text = list_presets_text()
    assert "Command Presets:" in text
    assert r"\a -> first" in text
    assert r"\b -> second" in text

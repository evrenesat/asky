"""Tests for CLI completion helpers."""

import argparse

import pytest

from asky.cli import completion


@pytest.fixture(autouse=True)
def clear_completion_caches():
    completion._get_model_aliases.cache_clear()
    completion._get_recent_history_hints.cache_clear()
    completion._get_recent_answer_hints.cache_clear()
    completion._get_recent_session_hints.cache_clear()


def test_complete_history_ids_supports_comma_lists(monkeypatch):
    monkeypatch.setattr(
        completion,
        "_get_recent_history_hints",
        lambda: {"120": "query one", "12": "query two", "7": "query three"},
    )
    args = argparse.Namespace()
    assert completion.complete_history_ids("1", args) == {
        "120": "query one",
        "12": "query two",
    }
    assert completion.complete_history_ids("120,", args) == {
        "120,12": "query two",
        "120,7": "query three",
    }
    assert completion.complete_history_ids("120,1", args) == {"120,12": "query two"}


def test_complete_single_history_id(monkeypatch):
    monkeypatch.setattr(
        completion,
        "_get_recent_history_hints",
        lambda: {"91": "ninety one", "9": "nine", "5": "five"},
    )
    args = argparse.Namespace()
    assert completion.complete_single_history_id("9", args) == {
        "91": "ninety one",
        "9": "nine",
    }


def test_complete_answer_ids_supports_comma_lists(monkeypatch):
    monkeypatch.setattr(
        completion,
        "_get_recent_answer_hints",
        lambda: {
            "318": "answer one",
            "answer_one__id_318": "answer one",
            "316": "answer two",
            "answer_two__id_316": "answer two",
            "214": "answer three",
            "answer_three__id_214": "answer three",
        },
    )
    args = argparse.Namespace()
    assert completion.complete_answer_ids("3", args) == {
        "318": "answer one",
        "316": "answer two",
    }
    assert completion.complete_answer_ids("answer", args) == {
        "answer_one__id_318": "answer one",
        "answer_two__id_316": "answer two",
        "answer_three__id_214": "answer three",
    }
    assert completion.complete_answer_ids("318,", args) == {
        "318,316": "answer two",
        "318,answer_two__id_316": "answer two",
        "318,214": "answer three",
        "318,answer_three__id_214": "answer three",
    }


def test_complete_single_answer_id(monkeypatch):
    monkeypatch.setattr(
        completion,
        "_get_recent_answer_hints",
        lambda: {
            "318": "answer one",
            "answer_one__id_318": "answer one",
            "316": "answer two",
            "answer_two__id_316": "answer two",
            "214": "answer three",
            "answer_three__id_214": "answer three",
        },
    )
    args = argparse.Namespace()
    assert completion.complete_single_answer_id("31", args) == {
        "318": "answer one",
        "316": "answer two",
    }
    assert completion.complete_single_answer_id("answer_", args) == {
        "answer_one__id_318": "answer one",
        "answer_two__id_316": "answer two",
        "answer_three__id_214": "answer three",
    }


def test_parse_answer_selector_token():
    assert completion.parse_answer_selector_token("318") == 318
    assert completion.parse_answer_selector_token("hello_world__id_318") == 318
    assert completion.parse_answer_selector_token("hello_world") is None


def test_parse_history_selector_token():
    assert completion.parse_history_selector_token("123") == 123
    assert completion.parse_history_selector_token("project_brief__hid_123") == 123
    assert completion.parse_history_selector_token("project_brief") is None


def test_parse_session_selector_token():
    assert completion.parse_session_selector_token("12") == 12
    assert completion.parse_session_selector_token("alpha_plan__sid_12") == 12
    assert completion.parse_session_selector_token("alpha_plan") is None


def test_complete_session_tokens_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        completion,
        "_get_recent_session_hints",
        lambda: {
            "alpha_plan__sid_44": "session #44 | Alpha Plan | 2026-02-08 13:00",
            "roadmap__sid_12": "session #12 | roadmap | 2026-02-08 10:00",
        },
    )
    args = argparse.Namespace()
    assert completion.complete_session_tokens("al", args) == {
        "alpha_plan__sid_44": "session #44 | Alpha Plan | 2026-02-08 13:00"
    }
    assert completion.complete_session_tokens("R", args) == {
        "roadmap__sid_12": "session #12 | roadmap | 2026-02-08 10:00"
    }


def test_complete_model_aliases(monkeypatch):
    monkeypatch.setattr(completion, "_get_model_aliases", lambda: ["gf", "gpt5", "or"])
    args = argparse.Namespace()
    assert completion.complete_model_aliases("g", args) == ["gf", "gpt5"]


def test_build_completion_script_for_bash_and_zsh():
    bash_script = completion.build_completion_script("bash")
    zsh_script = completion.build_completion_script("zsh")

    assert "#compdef asky ask" in bash_script
    assert "_ARGCOMPLETE=1" in bash_script
    assert "register-python-argcomplete" not in bash_script

    assert "#compdef asky ask" in zsh_script
    assert "_ARGCOMPLETE_SHELL=\"zsh\"" in zsh_script


def test_build_completion_script_rejects_unknown_shell():
    with pytest.raises(ValueError):
        completion.build_completion_script("fish")

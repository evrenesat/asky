import pytest
from unittest.mock import patch, MagicMock
from asky.cli import expand_query_text


@pytest.fixture
def mock_prompts():
    with patch(
        "asky.cli.utils.USER_PROMPTS", {"ex": "Explain this:", "sum": "Summarize /cp"}
    ):
        yield


def test_expand_query_text_no_slashes():
    assert expand_query_text("hello world") == "hello world"


@patch("pyperclip.paste")
def test_expand_query_text_cp(mock_paste):
    mock_paste.return_value = "clipboard content"
    assert expand_query_text("check this: /cp") == "check this: clipboard content"


@patch("pyperclip.paste")
def test_expand_query_text_prompt(mock_paste, mock_prompts):
    assert expand_query_text("/ex quantum") == "Explain this: quantum"


@patch("pyperclip.paste")
def test_expand_query_text_nested(mock_paste, mock_prompts):
    mock_paste.return_value = "my clipboard"
    # /sum expands to "Summarize /cp", then /cp expands to "my clipboard"
    assert expand_query_text("/sum") == "Summarize my clipboard"


@patch("pyperclip.paste")
def test_expand_query_text_multiple(mock_paste, mock_prompts):
    mock_paste.return_value = "CLIP"
    assert expand_query_text("/ex some code: /cp") == "Explain this: some code: CLIP"


def test_expand_query_text_non_matching_slash():
    assert (
        expand_query_text("this /not_a_cmd should stay")
        == "this /not_a_cmd should stay"
    )


@patch("pyperclip.paste")
def test_expand_query_text_empty_clipboard(mock_paste):
    mock_paste.return_value = ""
    assert expand_query_text("clip: /cp") == "clip: /cp"

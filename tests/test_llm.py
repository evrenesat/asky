import pytest
import json
import requests
from unittest.mock import patch, MagicMock
from asearch.llm import (
    parse_textual_tool_call,
    construct_system_prompt,
    extract_calls,
    get_llm_msg,
    generate_summaries,
    run_conversation_loop,
    count_tokens,
)


def test_parse_textual_tool_call_valid():
    text = 'to=functions.web_search\n{"q": "test"}'
    result = parse_textual_tool_call(text)
    assert result is not None
    assert result["name"] == "web_search"
    assert '"q": "test"' in result["arguments"]


def test_count_tokens():
    messages = [
        {"role": "user", "content": "1234"},  # 4 chars
        {"role": "assistant", "content": "5678"},  # 4 chars
    ]
    # (4 + 4) // 4 = 2
    assert count_tokens(messages) == 2


def test_parse_textual_tool_call_invalid():
    assert parse_textual_tool_call("random text") is None
    assert parse_textual_tool_call("to=functions.web_search\nnot json") is None


def test_construct_system_prompt_modes():
    # Basic
    p1 = construct_system_prompt(0, False, False)
    assert "DEEP RESEARCH mode" not in p1
    assert "DEEP DIVE mode" not in p1
    assert "always use web_search" not in p1

    # Deep Research
    p2 = construct_system_prompt(5, False, False)
    assert "DEEP RESEARCH mode" in p2
    assert "at least 5" in p2

    # Deep Dive
    p3 = construct_system_prompt(0, True, False)
    assert "DEEP DIVE mode" in p3
    assert "DEEP RESEARCH mode" not in p3

    # Force Search
    p4 = construct_system_prompt(0, False, True)
    assert "always use web_search" in p4


def test_extract_calls_native():
    msg = {
        "tool_calls": [
            {"id": "call_1", "function": {"name": "test", "arguments": "{}"}}
        ]
    }
    calls = extract_calls(msg, 1)
    assert len(calls) == 1
    assert calls[0]["id"] == "call_1"


def test_extract_calls_textual_fallback():
    msg = {"content": 'to=functions.web_search\n{"q": "test"}'}
    calls = extract_calls(msg, 1)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "web_search"
    assert calls[0]["id"] == "textual_call_1"


@patch("asearch.llm.requests.post")
def test_get_llm_msg_success(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}]
    }
    mock_post.return_value = mock_response

    msg = get_llm_msg("q34", [{"role": "user", "content": "Hi"}])
    assert msg["content"] == "Hello"


@patch("asearch.llm.requests.post")
def test_get_llm_msg_verbose(mock_post, capsys):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}]
    }
    mock_post.return_value = mock_response

    get_llm_msg("q34", [{"role": "user", "content": "Hi"}], verbose=True)
    captured = capsys.readouterr()
    assert "[DEBUG] Sending to LLM" in captured.out
    assert "Last message sent:" in captured.out
    assert "Hi" in captured.out


@patch("asearch.llm.requests.post")
def test_get_llm_msg_rate_limit_retry(mock_post):
    # First call returns 429, second returns success
    response_429 = MagicMock()
    response_429.status_code = 429
    error_429 = requests.exceptions.HTTPError(response=response_429)

    response_200 = MagicMock()
    response_200.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Success"}}]
    }

    # Side effect: raise error first, then return success
    # Note: request.post returns response object, so we need to mock that process
    # But usually we wrap the call. Here strict mocking:
    # get_llm_msg calls requests.post...
    # to simulate exception then success, we can use side_effect with an iterable

    mock_post.side_effect = [error_429, response_200]

    # We need to mock time.sleep to avoid waiting in tests
    with patch("asearch.llm.time.sleep"):
        msg = get_llm_msg("q34", [])
        assert msg["content"] == "Success"

    assert mock_post.call_count == 2


@patch("asearch.llm.requests.post")
def test_get_llm_msg_retry_after(mock_post):
    # Test that Retry-After header is respected
    response_429 = MagicMock()
    response_429.status_code = 429
    response_429.headers = {"Retry-After": "5"}
    error_429 = requests.exceptions.HTTPError(response=response_429)

    response_200 = MagicMock()
    response_200.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Success"}}]
    }

    mock_post.side_effect = [error_429, response_200]

    with patch("asearch.llm.time.sleep") as mock_sleep:
        msg = get_llm_msg("q34", [])
        assert msg["content"] == "Success"
        mock_sleep.assert_called_with(5)


@patch("asearch.llm.get_llm_msg")
@patch("asearch.llm.dispatch_tool_call")
def test_run_conversation_loop_basic(mock_dispatch, mock_get_msg):
    # Mock LLM sequence:
    # 1. Tool call (web search)
    # 2. Final answer

    msg_tool_call = {
        "content": None,
        "tool_calls": [
            {"id": "call_1", "function": {"name": "web_search", "arguments": "{}"}}
        ],
    }

    msg_final = {"content": "Final Answer"}

    mock_get_msg.side_effect = [msg_tool_call, msg_final]

    mock_dispatch.return_value = {"results": "search results"}

    messages = [{"role": "system", "content": "System Prompt"}]
    model_config = {"id": "test_model", "max_chars": 1000}

    final_answer = run_conversation_loop(model_config, messages, summarize=False)

    assert final_answer == "Final Answer"
    assert mock_get_msg.call_count == 2
    assert mock_dispatch.call_count == 1

    # Check that tool output was appended to messages
    assert len(messages) == 3
    # The loop breaks when no calls are returned. The final message IS NOT appended to messages list in the code.
    # It just returns final_answer.
    # So messages should contain: System, Tool Call (from LLM), Tool Result.
    # Let's verify messages content
    assert messages[1] == msg_tool_call
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_1"


@patch("asearch.llm.get_llm_msg")
def test_generate_summaries(mock_get_msg):
    # Mock responses for query summary and answer summary
    # 1. Query summary
    # 2. Answer summary

    mock_get_msg.side_effect = [
        {"content": "Short query"},
        {"content": "Short answer summary"},
    ]

    q_sum, a_sum = generate_summaries("Long query " * 10, "Long answer " * 100)

    assert q_sum == "Short query"
    assert a_sum == "Short answer summary"
    assert mock_get_msg.call_count == 2


@patch("asearch.llm.get_llm_msg")
def test_generate_summaries_short_query(mock_get_msg):
    # If query is short, it shouldn't call LLM for query summary
    mock_get_msg.return_value = {"content": "Answer summary"}

    q_sum, a_sum = generate_summaries("Short", "Long answer")

    assert q_sum == ""  # Code logic: if len(query) <= MAX, q_sum = ""?
    # Wait, let's check code.
    # if len(query) > QUERY_SUMMARY_MAX_CHARS: ... else: query_summary = "" ?
    # Actually looking at logic: query_summary = "" initially.
    # IF too long -> summarize.
    # So if short, it remains "".
    # Wait, that might be a bug or intended?
    # user probably wants the query itself if it's short?
    # Let's check `generate_summaries` implementation in `llm.py`:
    # query_summary = ""
    # if len(query) > ...: ...
    # It returns query_summary. So if short, it returns empty string?
    # Let's re-read llm.py Step 24.
    # query_summary = ""
    # if len(query) > QUERY_SUMMARY_MAX_CHARS: ...
    # return query_summary, answer_summary
    # Yes, it returns empty string if query is short.
    # That seems like a potential bug or feature (maybe storage handles empty summary by using query?).
    # In `storage.py`, `save_interaction`:
    # `q_text = q_sum if q_sum else query`
    # So yes, empty implementation is fine.

    assert q_sum == ""
    assert a_sum == "Answer summary"
    assert mock_get_msg.call_count == 1

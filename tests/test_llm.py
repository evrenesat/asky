import pytest
import json
import requests
from unittest.mock import patch, MagicMock
from asky.core import (
    parse_textual_tool_call,
    construct_system_prompt,
    extract_calls,
    get_llm_msg,
    generate_summaries,
    count_tokens,
    ConversationEngine,
)
from asky.rendering import render_to_browser


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
    p1 = construct_system_prompt()
    assert "DEEP RESEARCH mode" not in p1
    assert "DEEP DIVE mode" not in p1
    assert "always use web_search" not in p1


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


@patch("asky.core.api_client.requests.post")
def test_get_llm_msg_success(mock_post):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}]
    }
    mock_post.return_value = mock_response

    msg = get_llm_msg("q34", [{"role": "user", "content": "Hi"}])
    assert msg["content"] == "Hello"


@patch("asky.core.api_client.requests.post")
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
    with patch("asky.core.api_client.time.sleep"):
        msg = get_llm_msg("q34", [])
        assert msg["content"] == "Success"

    assert mock_post.call_count == 2


@patch("asky.core.api_client.requests.post")
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

    with patch("asky.core.api_client.time.sleep") as mock_sleep:
        msg = get_llm_msg("q34", [])
        assert msg["content"] == "Success"
        mock_sleep.assert_called_with(5)


@patch("asky.core.engine.get_llm_msg")
@patch("asky.core.engine.ToolRegistry.dispatch")
def test_conversation_engine_run_basic(mock_dispatch, mock_get_msg):
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

    # Use ConversationEngine directly
    # Ideally we'd mock creating the registry, but we can pass a mocked registry
    registry = MagicMock()
    registry.dispatch.return_value = {"results": "search results"}
    # Need get_schemas to return list
    registry.get_schemas.return_value = []

    engine = ConversationEngine(
        model_config=model_config,
        tool_registry=registry,
        summarize=False,
    )
    final_answer = engine.run(messages)

    assert final_answer == "Final Answer"
    assert mock_get_msg.call_count == 2

    # Verify dispatch called on the registry instance we passed
    assert registry.dispatch.call_count == 1

    # Check that tool output and final assistant answer were appended to messages
    # Messages: System, Tool Call, Tool Result, Final Assistant Answer
    assert len(messages) == 4
    assert messages[1] == msg_tool_call
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_1"
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == "Final Answer"


@patch("asky.core.engine.get_llm_msg")
def test_generate_summaries(mock_get_msg):
    # Mock responses for query summary and answer summary
    # 1. Query summary
    # 2. Answer summary

    mock_get_msg.side_effect = [
        {"content": "Short query"},
        {"content": "Short answer summary"},
    ]

    # Use a query longer than the default threshold (160)
    q_sum, a_sum = generate_summaries("Long query " * 20, "Long answer " * 100)

    assert q_sum == "Short query"
    assert a_sum == "Short answer summary"
    assert mock_get_msg.call_count == 2


@patch("asky.core.engine.get_llm_msg")
def test_generate_summaries_short_query(mock_get_msg):
    # If query is short, it shouldn't call LLM for query summary
    mock_get_msg.return_value = {"content": "Answer summary"}

    q_sum, a_sum = generate_summaries("Short", "Long answer " * 50)

    assert q_sum == "Short"
    assert a_sum == "Answer summary"
    assert mock_get_msg.call_count == 1


@patch("asky.core.engine.get_llm_msg")
def test_generate_summaries_short_answer(mock_get_msg):
    # Short answer should return answer as-is without LLM call
    mock_get_msg.return_value = {"content": "Summary"}

    q_sum, a_sum = generate_summaries("Long query " * 20, "ShortAns")

    assert q_sum == "Summary"
    assert a_sum == "ShortAns"
    assert mock_get_msg.call_count == 1


@patch("asky.rendering.webbrowser.open")
@patch("asky.rendering._save_to_archive")
@patch("asky.rendering._create_html_content")
def test_render_to_browser(mock_create_html, mock_save_to_archive, mock_browser_open):
    # Setup mocks
    mock_create_html.return_value = "<html>Content</html>"
    mock_save_to_archive.return_value = "/path/to/archive/file.html"

    # Call the function
    render_to_browser("Test Markdown", filename_hint="my_hint")

    # Assertions
    mock_create_html.assert_called_with("Test Markdown")
    # Now passes markdown_content for title extraction
    mock_save_to_archive.assert_called_with(
        "<html>Content</html>", "Test Markdown", "my_hint"
    )
    mock_browser_open.assert_called_with("file:///path/to/archive/file.html")


@patch("asky.core.engine.get_llm_msg")
@patch("asky.core.engine.ToolRegistry.dispatch")
def test_conversation_engine_tool_usage_tracking(mock_dispatch, mock_get_msg):
    # Test that engine correctly tracks tool usage with standard OpenAI-style tool calls
    from asky.core.engine import ConversationEngine

    msg_tool_call = {
        "content": None,
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "web_search", "arguments": "{}"},
            }
        ],
    }

    msg_final = {"content": "Final Answer"}

    mock_get_msg.side_effect = [msg_tool_call, msg_final]
    mock_dispatch.return_value = {"results": "search results"}

    usage_tracker = MagicMock()
    model_config = {"id": "test_model", "alias": "test"}
    registry = MagicMock()
    # Ensure tool schemas return valid list
    registry.get_schemas.return_value = []
    # Needs to return dispatch result
    registry.dispatch.return_value = {"results": "search results"}

    engine = ConversationEngine(
        model_config=model_config,
        tool_registry=registry,
        usage_tracker=usage_tracker,
    )

    messages = [{"role": "user", "content": "search"}]
    engine.run(messages)

    # assertion: usage_tracker.record_tool_usage should be called with "web_search"
    usage_tracker.record_tool_usage.assert_called_with("web_search")


@patch("asky.core.engine.get_llm_msg")
@patch("asky.core.engine.ToolRegistry.dispatch")
def test_run_conversation_loop_max_turns_graceful_exit(mock_dispatch, mock_get_msg):
    # Test graceful exit when MAX_TURNS is reached
    # We'll patch MAX_TURNS to 2 inside the test
    from asky.core.engine import ConversationEngine
    import asky.core.engine as engine_mod

    # Mock LLM sequence:
    # 1. Turn 1: Tool call
    # 2. Turn 2: Tool call (Hitting limit)
    # 3. Graceful Exit: Final Answer (use_tools=False)

    msg_tool_call_1 = {
        "content": None,
        "tool_calls": [
            {"id": "call_1", "function": {"name": "test", "arguments": "{}"}}
        ],
    }

    msg_tool_call_2 = {
        "content": None,
        "tool_calls": [
            {"id": "call_2", "function": {"name": "test", "arguments": "{}"}}
        ],
    }

    msg_forced_final = {"content": "Forced Final Answer"}

    # The loop will call get_llm_msg multiple times:
    # 1. Turn 1
    # 2. Turn 2
    # 3. Graceful Exit call
    mock_get_msg.side_effect = [msg_tool_call_1, msg_tool_call_2, msg_forced_final]

    mock_dispatch.return_value = {"result": "ok"}

    # Patch MAX_TURNS locally
    with patch.object(engine_mod, "MAX_TURNS", new=2):
        model_config = {"id": "test", "alias": "test"}

        # Configure registry mock to avoid JSON serialization issues
        registry_mock = MagicMock()
        registry_mock.dispatch.return_value = {"result": "ok"}
        registry_mock.get_schemas.return_value = []

        engine = ConversationEngine(
            model_config=model_config, tool_registry=registry_mock
        )
        # We need a real registry or mock that supports dispatch if we didn't mock dispatch separately,
        # but we mocked dispatch, so it's fine.
        # Ideally capture messages to check injection

        messages = [{"role": "user", "content": "start"}]
        final_answer = engine.run(messages)

        assert final_answer == "Forced Final Answer"

        # Verify calls
        # 1. Turn 1
        # 2. Turn 2
        # 3. Final forced call
        assert mock_get_msg.call_count == 3

        # Verify the final call had use_tools=False
        # checking the kwargs of the last call
        args, kwargs = mock_get_msg.call_args
        assert kwargs["use_tools"] is False

        # Verify the injected message
        # The messages list passed to the final call is mutable and has the final answer appended after the call returns.
        # So the injected instruction is at index -2.
        final_messages = args[1]
        assert final_messages[-1]["role"] == "user"
        assert "Provide your final answer" in final_messages[-1]["content"]


@patch("asky.core.engine.get_llm_msg")
@patch("asky.core.engine.ToolRegistry.dispatch")
def test_graceful_exit_replaces_system_prompt(mock_dispatch, mock_get_msg):
    # Test that graceful exit replaces the system prompt with a tool-free version
    from asky.core.engine import ConversationEngine
    import asky.core.engine as engine_mod

    msg_tool_call = {
        "content": None,
        "tool_calls": [
            {"id": "call_1", "function": {"name": "test", "arguments": "{}"}}
        ],
    }
    msg_forced_final = {"content": "Forced Final Answer"}

    # Turn 1: Tool call, Turn 2: Graceful Exit
    mock_get_msg.side_effect = [msg_tool_call, msg_forced_final]
    mock_dispatch.return_value = {"result": "ok"}

    with patch.object(engine_mod, "MAX_TURNS", new=1):
        model_config = {"id": "test", "alias": "test"}
        registry_mock = MagicMock()
        registry_mock.dispatch.return_value = {"result": "ok"}
        registry_mock.get_schemas.return_value = []

        engine = ConversationEngine(
            model_config=model_config, tool_registry=registry_mock
        )

        messages = [
            {"role": "system", "content": "ORIGINAL SYSTEM PROMPT WITH web_search"}
        ]
        engine.run(messages)

        # Verify calls
        assert mock_get_msg.call_count == 2

        # Check the messages passed to the second call (graceful exit)
        # kwargs are used for use_tools=False
        args, kwargs = mock_get_msg.call_args_list[1]
        exit_messages = args[1]

        # Find the system message in exit_messages
        system_msg = next(m for m in exit_messages if m["role"] == "system")

        # Verify it was replaced and does not contain "web_search"
        assert "ORIGINAL SYSTEM PROMPT" not in system_msg["content"]
        assert "web_search" not in system_msg["content"]
        assert "final answer" in system_msg["content"].lower()
        # Verify it includes the "no longer available" instruction from our new prompt
        assert "no longer available" in system_msg["content"].lower()

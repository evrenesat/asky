import pytest
from unittest.mock import MagicMock, patch
from asky.core.api_client import UsageTracker
from asky.core.engine import create_default_tool_registry, generate_summaries
from asky.config import SUMMARIZATION_MODEL


def test_generate_summaries_uses_tracker():
    tracker = UsageTracker()

    # Mock _summarize_content to simulate usage addition
    with patch("asky.summarization._summarize_content") as mock_summarize:
        mock_summarize.return_value = "Summary"

        # We also need to mock get_llm_msg because generate_summaries passes it
        # But wait, generate_summaries calls _summarize_content which calls get_llm_msg.
        # However, _summarize_content is what uses the tracker if we look at implementation.
        # Actually in _summarize_content, it calls get_llm_msg(..., usage_tracker=tracker).

        # So we should verify that generate_summaries passes the tracker to _summarize_content.

        generate_summaries(
            "long query " * 100, "long answer " * 100, usage_tracker=tracker
        )

        # Check that _summarize_content was called with usage_tracker=tracker
        assert mock_summarize.call_count > 0
        call_kwargs = mock_summarize.call_args.kwargs
        assert call_kwargs["usage_tracker"] == tracker


def test_registry_binds_summarization_tracker():
    tracker = UsageTracker()
    registry = create_default_tool_registry(summarization_tracker=tracker)

    # Get the executor for 'get_url_content'
    # Note: registry._executors is private but we can access it for testing or use dispatch
    # But dispatch doesn't take usage_tracker anymore.
    # We want to verify that when the tool executes, it uses the tracker.

    with (
        patch("asky.core.engine.execute_get_url_content") as mock_get_content,
        patch("asky.summarization._summarize_content") as mock_summarize,
    ):
        mock_get_content.return_value = {"http://example.com": "Long content"}
        mock_summarize.return_value = "Summary"

        # Dispatch a call with subscribe=True (which triggers summarization)
        # Note: the tool param is 'summarize'
        call = {
            "function": {
                "name": "get_url_content",
                "arguments": '{"urls": ["http://example.com"], "summarize": true}',
            }
        }

        registry.dispatch(call)

        # Verify _summarize_content called with our tracker
        assert mock_summarize.call_count == 1
        assert mock_summarize.call_args.kwargs["usage_tracker"] == tracker

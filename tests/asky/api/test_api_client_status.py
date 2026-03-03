import unittest
from unittest.mock import MagicMock, patch
import requests
import logging
from asky.core.api_client import get_llm_msg


class TestApiClientStatus(unittest.TestCase):
    @patch("asky.core.api_client.requests.post")
    @patch("asky.core.api_client.time.sleep")  # Mock sleep to avoid waiting
    def test_status_callback_trigger(self, mock_sleep, mock_post):
        """Test that status_callback is triggered on 429 and cleared on success."""
        # Setup mock response for 429
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.headers = {"Retry-After": "1"}
        error_429 = requests.exceptions.HTTPError(response=mock_response_429)

        # Setup mock response for success
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Success"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        # Side effect: Raise 429 first, then return 200
        mock_post.side_effect = [error_429, mock_response_200]

        # Mock callback
        mock_callback = MagicMock()

        # Run get_llm_msg
        get_llm_msg(
            model_id="test-model",
            messages=[{"role": "user", "content": "Hello"}],
            status_callback=mock_callback,
            model_alias="test-alias",
        )

        # Verification
        # 1. Check if callback was called with a string message (retry warning)
        args_list = mock_callback.call_args_list
        found_warning = False
        for args, _ in args_list:
            if args[0] and "Rate limit exceeded" in args[0]:
                found_warning = True
                break

        self.assertTrue(
            found_warning, "Callback should have been called with rate limit warning"
        )

        # 2. Check if callback was called with None (clearing status)
        mock_callback.assert_called_with(None)

    @patch("asky.core.api_client.requests.post")
    def test_trace_callback_emits_transport_request_and_response(self, mock_post):
        """Trace callback should receive request/response transport metadata."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"ok":true}'
        mock_response.text = '{"ok":true}'
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Success"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_post.return_value = mock_response

        trace_callback = MagicMock()
        result = get_llm_msg(
            model_id="test-model",
            messages=[{"role": "user", "content": "Hello"}],
            model_alias="test-alias",
            trace_callback=trace_callback,
            trace_context={"source": "main_model"},
        )

        self.assertEqual(result["content"], "Success")
        events = [call.args[0] for call in trace_callback.call_args_list]
        kinds = {event.get("kind") for event in events}
        self.assertIn("transport_request", kinds)
        self.assertIn("transport_response", kinds)
        response_events = [
            event for event in events if event.get("kind") == "transport_response"
        ]
        self.assertEqual(response_events[0]["status_code"], 200)
        self.assertEqual(response_events[0]["response_type"], "text")

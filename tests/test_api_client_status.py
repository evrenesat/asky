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

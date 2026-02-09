import unittest
from unittest.mock import MagicMock, patch
import requests
from asky.core.engine import ConversationEngine
from asky.core.exceptions import ContextOverflowError
from asky.core.registry import ToolRegistry


class TestContextOverflow(unittest.TestCase):
    def setUp(self):
        self.model_config = {
            "id": "test-model",
            "alias": "test",
            "context_size": 1000,
            "api_key": "fake-key",
            "base_url": "http://fake-url",
        }
        self.registry = ToolRegistry()
        self.engine = ConversationEngine(
            model_config=self.model_config, tool_registry=self.registry, verbose=True
        )

    @patch("asky.core.api_client.requests.post")
    def test_400_error_handling(self, mock_post):
        # Mock a 400 Bad Request response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "400 Client Error: Bad Request", response=mock_response
        )
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "test"}]
        with self.assertRaises(ContextOverflowError) as exc_info:
            self.engine.run(messages)
        self.assertEqual(exc_info.exception.status_code, 400)

    def test_check_and_compact_logic(self):
        # Setup logic
        # context_size = 1000
        # threshold default is likely around 80%? We need to mock config

        # Patching 'asky.core.engine.SESSION_COMPACTION_THRESHOLD' because it's imported directly
        with patch(
            "asky.core.engine.SESSION_COMPACTION_THRESHOLD", 50
        ):  # 50% = 500 tokens
            # Create messages that exceed 500 tokens.
            # 1 token approx 4 chars. so > 2000 chars.

            long_content = "a" * 2500  # ~625 tokens

            messages = [
                {"role": "system", "content": "sys"},  # Keep
                {"role": "user", "content": "user1"},  # Drop
                {"role": "assistant", "content": "ass1"},  # Drop
                {"role": "user", "content": long_content},  # Keep (last msg)
            ]

            compacted = self.engine.check_and_compact(messages)

            # Should have system and last user message
            self.assertEqual(len(compacted), 2)
            self.assertEqual(compacted[0]["content"], "sys")
            self.assertEqual(compacted[1]["content"], long_content)

    def test_compaction_called_in_run(self):
        with patch.object(
            self.engine, "check_and_compact", return_value=[]
        ) as mock_compact:
            # We also need to mock get_llm_msg to avoid network calls and error handling
            with patch(
                "asky.core.engine.get_llm_msg", return_value={"content": "response"}
            ):
                messages = [{"role": "user", "content": "test"}]
                self.engine.run(messages)
                mock_compact.assert_called()

    def test_smart_compaction_with_cache(self):
        # Mock ResearchCache.get_summary to return a summary
        # Patching correct location for ResearchCache
        with patch("asky.core.engine.ResearchCache") as mock_cache_cls:
            mock_cache_instance = MagicMock()
            mock_cache_cls.return_value = mock_cache_instance
            mock_cache_instance.get_summary.return_value = {
                "summary": "This is a summary."
            }

            # Re-init engine to pick up mocked cache
            self.engine = ConversationEngine(
                model_config=self.model_config,
                tool_registry=self.registry,
                verbose=True,
            )

            # Create a large tool message with a URL content
            import json

            long_content = "x" * 2000
            tool_data = {
                "https://example.com/long-article": {
                    "content": long_content,
                    "title": "Long Article",
                }
            }
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "tool", "content": json.dumps(tool_data)},
            ]

            # Threshold low to force compaction
            with patch("asky.core.engine.SESSION_COMPACTION_THRESHOLD", 10):
                compacted = self.engine.check_and_compact(messages)

                # Verify message count is SAME (non-destructive)
                self.assertEqual(len(compacted), 2)

                # Verify content was replaced with summary
                compacted_tool_msg = compacted[1]
                compacted_data = json.loads(compacted_tool_msg["content"])

                self.assertIn(
                    "[COMPACTED]",
                    compacted_data["https://example.com/long-article"]["content"],
                )
                self.assertIn(
                    "This is a summary",
                    compacted_data["https://example.com/long-article"]["content"],
                )


if __name__ == "__main__":
    unittest.main()

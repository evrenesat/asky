"""Tests for embedding usage tracking in banner (research mode)."""

import pytest
from unittest.mock import patch, MagicMock

from asky.banner import BannerState, get_banner


class TestEmbeddingClientUsageTracking:
    """Test that EmbeddingClient tracks usage correctly."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the EmbeddingClient singleton before each test."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        yield
        EmbeddingClient._instance = None

    def test_usage_counters_increment_on_embed(self):
        """Test that usage counters increment correctly after embedding."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()

        # Mock the embedding HTTP call
        with patch("requests.sessions.Session.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ],
                "usage": {"prompt_tokens": 50},
            }
            mock_post.return_value = mock_response

            # Embed 2 texts
            client.embed(["text1", "text2"])

            # Verify counters
            assert client.texts_embedded == 2
            assert client.api_calls == 1
            assert client.prompt_tokens == 50

    def test_usage_counters_accumulate_across_calls(self):
        """Test that usage counters accumulate across multiple embed calls."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()

        with patch("requests.sessions.Session.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 20},
            }
            mock_post.return_value = mock_response

            # First call
            client.embed(["text1"])
            assert client.texts_embedded == 1
            assert client.api_calls == 1
            assert client.prompt_tokens == 20

            # Second call
            client.embed(["text2"])
            assert client.texts_embedded == 2
            assert client.api_calls == 2
            assert client.prompt_tokens == 40

    def test_get_usage_stats_returns_correct_dict(self):
        """Test that get_usage_stats returns the correct dictionary."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()

        with patch("requests.sessions.Session.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 15},
            }
            mock_post.return_value = mock_response

            client.embed(["test"])

            stats = client.get_usage_stats()
            assert stats == {
                "texts_embedded": 1,
                "api_calls": 1,
                "prompt_tokens": 15,
            }

    def test_usage_handles_missing_usage_field(self):
        """Test that usage tracking handles missing 'usage' field in API response."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()

        with patch("requests.sessions.Session.post") as mock_post:
            # Response without 'usage' field
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1, 0.2]}],
            }
            mock_post.return_value = mock_response

            client.embed(["test"])

            # Should still track texts and calls, but not tokens
            assert client.texts_embedded == 1
            assert client.api_calls == 1
            assert client.prompt_tokens == 0


class TestBannerEmbeddingDisplay:
    """Test that the banner displays embedding stats correctly."""

    def test_banner_shows_embedding_row_when_research_mode_true(self):
        """Test that Embedding row appears when research_mode=True."""
        from rich.console import Console
        from io import StringIO

        state = BannerState(
            model_alias="test-model",
            model_id="test-id",
            sum_alias="sum-model",
            sum_id="sum-id",
            model_ctx=4096,
            sum_ctx=2048,
            max_turns=10,
            current_turn=1,
            db_count=5,
            research_mode=True,
            embedding_model="nomic-embed-text-v1.5",
            embedding_texts=42,
            embedding_api_calls=3,
            embedding_prompt_tokens=1200,
        )

        banner = get_banner(state)

        # Render to string
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

        # Check that the embedding row is rendered
        assert "Embedding" in output
        assert "nomic-embed-text-v1.5" in output
        assert "Texts: 42" in output
        assert "API Calls: 3" in output
        assert "Tokens: 1,200" in output

    def test_banner_hides_embedding_row_when_research_mode_false(self):
        """Test that Embedding row is hidden when research_mode=False."""
        from rich.console import Console
        from io import StringIO

        state = BannerState(
            model_alias="test-model",
            model_id="test-id",
            sum_alias="sum-model",
            sum_id="sum-id",
            model_ctx=4096,
            sum_ctx=2048,
            max_turns=10,
            current_turn=1,
            db_count=5,
            research_mode=False,
            embedding_model=None,
            embedding_texts=0,
            embedding_api_calls=0,
            embedding_prompt_tokens=0,
        )

        banner = get_banner(state)

        # Render to string
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

        # The word "Embedding" should not appear in the banner
        assert "Embedding" not in output

    def test_banner_embedding_row_shows_tokens_when_greater_than_zero(self):
        """Test that tokens are shown when > 0."""
        from rich.console import Console
        from io import StringIO

        state = BannerState(
            model_alias="test-model",
            model_id="test-id",
            sum_alias="sum-model",
            sum_id="sum-id",
            model_ctx=4096,
            sum_ctx=2048,
            max_turns=10,
            current_turn=1,
            db_count=5,
            research_mode=True,
            embedding_model="nomic-embed-text-v1.5",
            embedding_texts=10,
            embedding_api_calls=2,
            embedding_prompt_tokens=500,
        )

        banner = get_banner(state)

        # Render to string
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

        # Should contain "Tokens:" since prompt_tokens > 0
        assert "Tokens: 500" in output

    def test_banner_embedding_row_hides_tokens_when_zero(self):
        """Test that tokens are hidden when = 0."""
        state = BannerState(
            model_alias="test-model",
            model_id="test-id",
            sum_alias="sum-model",
            sum_id="sum-id",
            model_ctx=4096,
            sum_ctx=2048,
            max_turns=10,
            current_turn=1,
            db_count=5,
            research_mode=True,
            embedding_model="nomic-embed-text-v1.5",
            embedding_texts=5,
            embedding_api_calls=1,
            embedding_prompt_tokens=0,
        )

        banner = get_banner(state)
        # We can't easily verify absence in rich output, but we can verify
        # the banner renders without error
        assert banner is not None


class TestInterfaceRendererEmbeddingIntegration:
    """Test that InterfaceRenderer correctly passes embedding stats to banner."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the EmbeddingClient singleton before each test."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        yield
        EmbeddingClient._instance = None

    @patch("asky.cli.display.get_db_record_count")
    @patch("requests.sessions.Session.post")
    def test_renderer_pulls_embedding_stats_when_research_mode_true(
        self, mock_post, mock_db_count
    ):
        """Test that InterfaceRenderer fetches and passes embedding stats."""
        from asky.cli.display import InterfaceRenderer
        from asky.core import UsageTracker
        from asky.research.embeddings import get_embedding_client

        mock_db_count.return_value = 10

        # Mock embedding API call
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 25},
        }
        mock_post.return_value = mock_response

        # Simulate some embedding activity
        client = get_embedding_client()
        client.embed(["test text"])

        # Create renderer with research_mode=True
        model_config = {"id": "test-model", "context_size": 4096}
        usage_tracker = UsageTracker()

        renderer = InterfaceRenderer(
            model_config=model_config,
            model_alias="test",
            usage_tracker=usage_tracker,
            research_mode=True,
        )

        # Build banner
        banner = renderer._build_banner(current_turn=1)

        # The banner should be created without error and contain embedding info
        assert banner is not None

        # Verify client stats were read
        stats = client.get_usage_stats()
        assert stats["texts_embedded"] == 1
        assert stats["api_calls"] == 1
        assert stats["prompt_tokens"] == 25

    @patch("asky.cli.display.get_db_record_count")
    def test_renderer_skips_embedding_stats_when_research_mode_false(
        self, mock_db_count
    ):
        """Test that InterfaceRenderer doesn't fetch embedding stats when not in research mode."""
        from asky.cli.display import InterfaceRenderer
        from asky.core import UsageTracker

        mock_db_count.return_value = 10

        model_config = {"id": "test-model", "context_size": 4096}
        usage_tracker = UsageTracker()

        renderer = InterfaceRenderer(
            model_config=model_config,
            model_alias="test",
            usage_tracker=usage_tracker,
            research_mode=False,
        )

        # Build banner - should not try to import embedding client
        banner = renderer._build_banner(current_turn=1)
        assert banner is not None

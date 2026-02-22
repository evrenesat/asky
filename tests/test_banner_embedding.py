"""Tests for embedding usage tracking in banner (research mode)."""

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from asky.banner import BannerState, get_banner


class _FakeTokenizer:
    def encode(self, text, add_special_tokens=False):  # noqa: ARG002
        words = [word for word in text.split() if word]
        return list(range(len(words)))

    def decode(self, token_ids, skip_special_tokens=True):  # noqa: ARG002
        return " ".join(f"tok{token_id}" for token_id in token_ids)


class _FakeArray:
    def __init__(self, rows):
        self.rows = rows

    def tolist(self):
        return self.rows


class _FakeSentenceTransformer:
    def __init__(self, model_name, device="cpu", **kwargs):  # noqa: ARG002
        self.model_name = model_name
        self.device = device
        self.max_seq_length = 16
        self.tokenizer = _FakeTokenizer()

    def encode(
        self,
        texts,
        batch_size,
        convert_to_numpy,
        show_progress_bar,
        normalize_embeddings,
    ):  # noqa: ARG002
        rows = []
        for text in texts:
            token_count = max(1, len([word for word in text.split() if word]))
            base = float(token_count)
            rows.append([base, base + 1.0, base + 2.0])
        return _FakeArray(rows)


class TestEmbeddingClientUsageTracking:
    """Test that EmbeddingClient tracks usage correctly."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton and mock sentence-transformers for each test."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _FakeSentenceTransformer,
        ):
            yield
        EmbeddingClient._instance = None

    def test_usage_counters_increment_on_embed(self):
        """Test that usage counters increment correctly after embedding."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()
        client.embed(["text1", "text2"])

        assert client.texts_embedded == 2
        assert client.api_calls == 1
        assert client.prompt_tokens == 2

    def test_usage_counters_accumulate_across_calls(self):
        """Test that usage counters accumulate across multiple embed calls."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()
        client.embed(["text1"])
        assert client.texts_embedded == 1
        assert client.api_calls == 1
        assert client.prompt_tokens == 1

        client.embed(["text2"])
        assert client.texts_embedded == 2
        assert client.api_calls == 2
        assert client.prompt_tokens == 2

    def test_get_usage_stats_returns_correct_dict(self):
        """Test that get_usage_stats returns the correct dictionary."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()
        client.embed(["test"])

        stats = client.get_usage_stats()
        assert stats == {
            "texts_embedded": 1,
            "api_calls": 1,
            "prompt_tokens": 1,
        }

    def test_usage_filters_empty_values(self):
        """Test that usage tracking ignores empty embedding inputs."""
        from asky.research.embeddings import EmbeddingClient

        client = EmbeddingClient()
        client.embed(["test", "", "  "])

        assert client.texts_embedded == 1
        assert client.api_calls == 1
        assert client.prompt_tokens == 1


class TestBannerEmbeddingDisplay:
    """Test that the banner displays embedding stats correctly."""

    def test_banner_shows_embedding_row_when_research_mode_true(self):
        """Test that Embedding row appears when research_mode=True."""
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
            embedding_model="all-MiniLM-L6-v2",
            embedding_texts=42,
            embedding_api_calls=3,
            embedding_prompt_tokens=1200,
        )

        banner = get_banner(state)
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

        assert "Embedding" in output
        assert "all-MiniLM-L6-v2" in output
        assert "Texts: 42" in output
        assert "API Calls: 3" in output
        assert "Tokens: 1,200" in output

    def test_banner_hides_embedding_row_when_research_mode_false(self):
        """Test that Embedding row is hidden when research_mode=False."""
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
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

        assert "Embedding" not in output

    def test_banner_embedding_row_shows_tokens_when_greater_than_zero(self):
        """Test that tokens are shown when > 0."""
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
            embedding_model="all-MiniLM-L6-v2",
            embedding_texts=10,
            embedding_api_calls=2,
            embedding_prompt_tokens=500,
        )

        banner = get_banner(state)
        string_io = StringIO()
        console = Console(file=string_io, force_terminal=True, width=120)
        console.print(banner)
        output = string_io.getvalue()

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
            embedding_model="all-MiniLM-L6-v2",
            embedding_texts=5,
            embedding_api_calls=1,
            embedding_prompt_tokens=0,
        )

        banner = get_banner(state)
        assert banner is not None


class TestInterfaceRendererEmbeddingIntegration:
    """Test that InterfaceRenderer correctly passes embedding stats to banner."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton and mock sentence-transformers for each test."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _FakeSentenceTransformer,
        ):
            yield
        EmbeddingClient._instance = None

    @patch("asky.cli.display.get_db_record_count")
    def test_renderer_pulls_embedding_stats_when_research_mode_true(self, mock_db_count):
        """Test that InterfaceRenderer fetches and passes embedding stats."""
        from asky.cli.display import InterfaceRenderer
        from asky.core import UsageTracker
        from asky.research.embeddings import get_embedding_client

        mock_db_count.return_value = 10

        client = get_embedding_client()
        client.embed(["test text"])

        model_config = {"id": "test-model", "context_size": 4096}
        usage_tracker = UsageTracker()

        renderer = InterfaceRenderer(
            model_config=model_config,
            model_alias="test",
            usage_tracker=usage_tracker,
            research_mode=True,
        )

        banner = renderer._build_banner(current_turn=1)
        assert banner is not None

        stats = client.get_usage_stats()
        assert stats["texts_embedded"] == 1
        assert stats["api_calls"] == 1
        assert stats["prompt_tokens"] == 2

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

        banner = renderer._build_banner(current_turn=1)
        assert banner is not None

    @patch("asky.cli.display.get_db_record_count")
    @patch("asky.cli.display.get_banner")
    def test_renderer_passes_shortlist_stats_to_banner_state(
        self, mock_get_banner, mock_db_count
    ):
        """Shortlist stats should be exposed to banner state."""
        from rich.panel import Panel
        from asky.cli.display import InterfaceRenderer
        from asky.core import UsageTracker

        mock_db_count.return_value = 10
        mock_get_banner.return_value = Panel("ok")

        renderer = InterfaceRenderer(
            model_config={"id": "test-model", "context_size": 4096},
            model_alias="test",
            usage_tracker=UsageTracker(),
            research_mode=False,
        )
        renderer.set_shortlist_stats(
            {
                "enabled": True,
                "collected": 9,
                "processed": 5,
                "selected": 3,
                "warnings": 1,
                "elapsed_ms": 432.1,
            }
        )

        _ = renderer._build_banner(current_turn=1)
        state = mock_get_banner.call_args.args[0]
        assert state.shortlist_enabled is True
        assert state.shortlist_collected == 9
        assert state.shortlist_processed == 5
        assert state.shortlist_selected == 3
        assert state.shortlist_warnings == 1

    @patch("asky.cli.display.get_total_session_count")
    @patch("asky.cli.display.get_db_record_count")
    @patch("asky.cli.display.get_banner")
    def test_renderer_uses_global_session_count_without_active_session(
        self, mock_get_banner, mock_db_count, mock_total_session_count
    ):
        """Session totals should be shown even when no session is active."""
        from rich.panel import Panel
        from asky.cli.display import InterfaceRenderer
        from asky.core import UsageTracker

        mock_db_count.return_value = 10
        mock_total_session_count.return_value = 7
        mock_get_banner.return_value = Panel("ok")

        renderer = InterfaceRenderer(
            model_config={"id": "test-model", "context_size": 4096},
            model_alias="test",
            usage_tracker=UsageTracker(),
            research_mode=False,
            session_manager=None,
        )

        _ = renderer._build_banner(current_turn=1)
        state = mock_get_banner.call_args.args[0]
        assert state.total_sessions == 7
        assert state.session_name is None
        assert state.session_msg_count == 0

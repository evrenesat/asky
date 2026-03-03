"""Tests for the research embeddings module."""

from unittest.mock import patch

import pytest


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
    def __init__(self, model_name, device="cpu", **kwargs):
        self.model_name = model_name
        self.device = device
        self.kwargs = kwargs
        self.max_seq_length = 16
        self.tokenizer = _FakeTokenizer()
        self.encode_calls = []

    def encode(
        self,
        texts,
        batch_size,
        convert_to_numpy,
        show_progress_bar,
        normalize_embeddings,
    ):
        self.encode_calls.append(
            {
                "texts": list(texts),
                "batch_size": batch_size,
                "convert_to_numpy": convert_to_numpy,
                "show_progress_bar": show_progress_bar,
                "normalize_embeddings": normalize_embeddings,
            }
        )
        rows = []
        for text in texts:
            token_count = max(1, len([word for word in text.split() if word]))
            base = float(token_count)
            rows.append([base, base + 1.0, base + 2.0])
        return _FakeArray(rows)


class _PrimaryFailSentenceTransformer:
    def __init__(self, model_name, device="cpu", **kwargs):
        if model_name == "bad/model":
            raise RuntimeError("primary load failed")
        self.model_name = model_name
        self.device = device
        self.kwargs = kwargs
        self.max_seq_length = 16
        self.tokenizer = _FakeTokenizer()

    def encode(
        self,
        texts,
        batch_size,
        convert_to_numpy,
        show_progress_bar,
        normalize_embeddings,
    ):
        rows = []
        for text in texts:
            token_count = max(1, len([word for word in text.split() if word]))
            base = float(token_count)
            rows.append([base, base + 1.0, base + 2.0])
        return _FakeArray(rows)


class _AlwaysFailSentenceTransformer:
    def __init__(self, model_name, device="cpu", **kwargs):  # noqa: ARG002
        raise RuntimeError(f"cannot load {model_name}")


class _LocalCacheOnlySentenceTransformer:
    calls = []

    def __init__(self, model_name, device="cpu", **kwargs):
        local_files_only = kwargs.get("local_files_only")
        self.__class__.calls.append(
            {"model_name": model_name, "local_files_only": local_files_only}
        )
        if local_files_only is not True:
            raise AssertionError("Remote load should not be attempted in this test")
        self.model_name = model_name
        self.device = device
        self.kwargs = kwargs
        self.max_seq_length = 16
        self.tokenizer = _FakeTokenizer()

    def encode(
        self,
        texts,
        batch_size,
        convert_to_numpy,
        show_progress_bar,
        normalize_embeddings,
    ):
        rows = []
        for text in texts:
            token_count = max(1, len([word for word in text.split() if word]))
            base = float(token_count)
            rows.append([base, base + 1.0, base + 2.0])
        return _FakeArray(rows)


class _TruncationAwareTokenizer:
    def __init__(self):
        self.last_kwargs = {}

    def encode(self, text, **kwargs):
        self.last_kwargs = kwargs
        words = [word for word in text.split() if word]
        if kwargs.get("truncation") and kwargs.get("max_length"):
            words = words[: kwargs["max_length"]]
        return list(range(len(words)))

    def decode(self, token_ids, skip_special_tokens=True):  # noqa: ARG002
        return " ".join(f"tok{token_id}" for token_id in token_ids)


class _TruncationAwareSentenceTransformer:
    def __init__(self, model_name, device="cpu", **kwargs):
        self.model_name = model_name
        self.device = device
        self.kwargs = kwargs
        self.max_seq_length = 3
        self.tokenizer = _TruncationAwareTokenizer()

    def encode(
        self,
        texts,
        batch_size,
        convert_to_numpy,
        show_progress_bar,
        normalize_embeddings,
    ):
        rows = []
        for text in texts:
            token_count = max(1, len([word for word in text.split() if word]))
            base = float(token_count)
            rows.append([base, base + 1.0, base + 2.0])
        return _FakeArray(rows)


class TestEmbeddingClient:
    """Tests for EmbeddingClient class."""

    @pytest.fixture
    def client(self):
        """Create an EmbeddingClient instance for testing."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _FakeSentenceTransformer,
        ):
            instance = EmbeddingClient(
                model="test-model",
                batch_size=2,
                device="cpu",
                normalize_embeddings=True,
                local_files_only=True,
            )
            yield instance
        EmbeddingClient._instance = None

    def test_init_sets_parameters(self, client):
        """Test that initialization sets parameters correctly."""
        assert client.model == "test-model"
        assert client.batch_size == 2
        assert client.device == "cpu"
        assert client.normalize_embeddings is True
        assert client.local_files_only is True

    def test_embed_single_text(self, client):
        """Test embedding a single text."""
        result = client.embed_single("test text")
        assert result == [2.0, 3.0, 4.0]
        assert client.texts_embedded == 1
        assert client.api_calls == 1
        assert client.prompt_tokens == 2

    def test_embed_multiple_texts(self, client):
        """Test embedding multiple texts."""
        result = client.embed(["text one", "text two"])
        assert len(result) == 2
        assert result[0] == [2.0, 3.0, 4.0]
        assert result[1] == [2.0, 3.0, 4.0]

    def test_embed_batches_large_inputs(self, client):
        """Test that large inputs are batched."""
        result = client.embed(["a", "b", "c", "d"])
        assert len(result) == 4
        assert client.api_calls == 2

    def test_embed_empty_list_returns_empty(self, client):
        """Test that embedding empty list returns empty list."""
        result = client.embed([])
        assert result == []

    def test_embed_filters_empty_strings(self, client):
        """Test that empty strings are filtered out."""
        result = client.embed(["text", "", "  "])
        assert len(result) == 1
        assert client.texts_embedded == 1

    def test_embed_single_empty_raises(self, client):
        """Test that embedding empty string raises error."""
        with pytest.raises(ValueError):
            client.embed_single("")

        with pytest.raises(ValueError):
            client.embed_single("   ")

    def test_is_available_returns_true(self, client):
        """Test is_available returns True when model loads."""
        assert client.is_available() is True

    def test_is_available_returns_false_on_error(self):
        """Test is_available returns False when backend is missing."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch("asky.research.embeddings.SentenceTransformer", None):
            client = EmbeddingClient(model="test-model")
            assert client.is_available() is False
        EmbeddingClient._instance = None

    def test_get_tokenizer_and_max_seq_length(self, client):
        """Test tokenizer and max sequence length accessors."""
        tokenizer = client.get_tokenizer()
        assert tokenizer is not None
        assert client.max_seq_length == 16

    def test_fallback_model_auto_download_on_primary_failure(self):
        """Primary model failure should fall back to bundled HF model."""
        from asky.research.embeddings import (
            EmbeddingClient,
            FALLBACK_EMBEDDING_MODEL,
        )

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _PrimaryFailSentenceTransformer,
        ):
            client = EmbeddingClient(
                model="bad/model",
                local_files_only=False,
            )
            assert client.is_available() is True
            assert client.model == FALLBACK_EMBEDDING_MODEL
            assert client.has_model_load_failure() is False
        EmbeddingClient._instance = None

    def test_cached_model_load_failure_flag(self):
        """Model load failures should be cached for fast future checks."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _AlwaysFailSentenceTransformer,
        ):
            client = EmbeddingClient(
                model="bad/model",
                local_files_only=False,
            )
            assert client.is_available() is False
            assert client.has_model_load_failure() is True
        EmbeddingClient._instance = None

    def test_prefers_local_cache_before_remote_load(self):
        """When cached locally, model loading should avoid remote attempt."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        _LocalCacheOnlySentenceTransformer.calls = []
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _LocalCacheOnlySentenceTransformer,
        ):
            client = EmbeddingClient(
                model="cached/model",
                local_files_only=False,
            )
            assert client.is_available() is True
            assert _LocalCacheOnlySentenceTransformer.calls == [
                {"model_name": "cached/model", "local_files_only": True}
            ]
        EmbeddingClient._instance = None

    def test_token_counting_uses_truncation_when_model_has_max_length(self):
        """Token counting should truncate to model max length to avoid warnings."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _TruncationAwareSentenceTransformer,
        ):
            client = EmbeddingClient(
                model="trunc/model",
                local_files_only=True,
            )
            _ = client.embed_single("one two three four five six")
            tokenizer = client.get_tokenizer()
            assert tokenizer.last_kwargs.get("truncation") is True
            assert tokenizer.last_kwargs.get("max_length") == 3
            assert client.prompt_tokens == 3
        EmbeddingClient._instance = None

    def test_embed_truncates_overlength_text_before_model_encode(self):
        """Embedding inputs should be truncated to model max sequence length."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _TruncationAwareSentenceTransformer,
        ):
            client = EmbeddingClient(
                model="trunc/model",
                local_files_only=True,
            )
            # 6 tokens in input; truncation-aware model max_seq_length is 3.
            result = client.embed_single("one two three four five six")
            assert result == [3.0, 4.0, 5.0]
        EmbeddingClient._instance = None


class TestEmbeddingSerialization:
    """Tests for embedding serialization utilities."""

    def test_serialize_embedding(self):
        """Test serializing embedding to bytes."""
        from asky.research.embeddings import EmbeddingClient

        embedding = [1.0, 2.0, 3.0]
        serialized = EmbeddingClient.serialize_embedding(embedding)
        assert len(serialized) == 12
        assert isinstance(serialized, bytes)

    def test_deserialize_embedding(self):
        """Test deserializing embedding from bytes."""
        from asky.research.embeddings import EmbeddingClient

        embedding = [1.0, 2.0, 3.0]
        serialized = EmbeddingClient.serialize_embedding(embedding)
        deserialized = EmbeddingClient.deserialize_embedding(serialized)

        assert len(deserialized) == 3
        assert abs(deserialized[0] - 1.0) < 0.0001
        assert abs(deserialized[1] - 2.0) < 0.0001
        assert abs(deserialized[2] - 3.0) < 0.0001

    def test_serialize_deserialize_roundtrip(self):
        """Test that serialize/deserialize is a perfect roundtrip."""
        from asky.research.embeddings import EmbeddingClient

        original = [0.123456, -0.789012, 1.5, -2.5, 0.0]
        serialized = EmbeddingClient.serialize_embedding(original)
        restored = EmbeddingClient.deserialize_embedding(serialized)

        for orig, rest in zip(original, restored):
            assert abs(orig - rest) < 0.0001

    def test_deserialize_empty_returns_empty(self):
        """Test that deserializing empty bytes returns empty list."""
        from asky.research.embeddings import EmbeddingClient

        result = EmbeddingClient.deserialize_embedding(b"")
        assert result == []

        result = EmbeddingClient.deserialize_embedding(None)
        assert result == []


class TestGetEmbeddingClient:
    """Tests for the get_embedding_client helper."""

    def test_get_embedding_client_returns_singleton(self):
        """Test that get_embedding_client returns singleton."""
        from asky.research.embeddings import EmbeddingClient, get_embedding_client

        EmbeddingClient._instance = None
        with patch(
            "asky.research.embeddings.SentenceTransformer",
            _FakeSentenceTransformer,
        ):
            client1 = get_embedding_client()
            client2 = get_embedding_client()
            assert client1 is client2
        EmbeddingClient._instance = None

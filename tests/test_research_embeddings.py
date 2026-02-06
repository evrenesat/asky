"""Tests for the research embeddings module."""

import struct
from unittest.mock import patch, MagicMock

import pytest
import requests


class TestEmbeddingClient:
    """Tests for EmbeddingClient class."""

    @pytest.fixture
    def client(self):
        """Create an EmbeddingClient instance for testing."""
        from asky.research.embeddings import EmbeddingClient

        # Reset singleton
        EmbeddingClient._instance = None

        client = EmbeddingClient(
            api_url="http://localhost:1234/v1/embeddings",
            model="test-model",
            timeout=10,
            batch_size=2,
            retry_attempts=1,
            retry_backoff_seconds=0,
        )
        yield client

    def test_init_sets_parameters(self, client):
        """Test that initialization sets parameters correctly."""
        assert client.api_url == "http://localhost:1234/v1/embeddings"
        assert client.model == "test-model"
        assert client.timeout == 10
        assert client.batch_size == 2

    @patch("requests.sessions.Session.post")
    def test_embed_single_text(self, mock_post, client):
        """Test embedding a single text."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}]
        }
        mock_post.return_value = mock_response

        result = client.embed_single("test text")

        assert result == [0.1, 0.2, 0.3]
        mock_post.assert_called_once()

    @patch("requests.sessions.Session.post")
    def test_embed_multiple_texts(self, mock_post, client):
        """Test embedding multiple texts."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ]
        }
        mock_post.return_value = mock_response

        result = client.embed(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    @patch("requests.sessions.Session.post")
    def test_embed_batches_large_inputs(self, mock_post, client):
        """Test that large inputs are batched."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"embedding": [0.1]},
                {"embedding": [0.2]},
            ]
        }
        mock_post.return_value = mock_response

        # With batch_size=2, this should make 2 API calls
        result = client.embed(["text1", "text2", "text3", "text4"])

        assert mock_post.call_count == 2
        assert len(result) == 4

    def test_embed_empty_list_returns_empty(self, client):
        """Test that embedding empty list returns empty list."""
        result = client.embed([])
        assert result == []

    def test_embed_filters_empty_strings(self, client):
        """Test that empty strings are filtered out."""
        with patch("requests.sessions.Session.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1]}]
            }
            mock_post.return_value = mock_response

            result = client.embed(["text", "", "  "])
            # Only "text" should be embedded
            assert len(result) == 1

    def test_embed_single_empty_raises(self, client):
        """Test that embedding empty string raises error."""
        with pytest.raises(ValueError):
            client.embed_single("")

        with pytest.raises(ValueError):
            client.embed_single("   ")

    @patch("requests.sessions.Session.post")
    def test_embed_handles_alternative_response_format(self, mock_post, client):
        """Test handling of alternative response format."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [[0.1, 0.2], [0.3, 0.4]]
        }
        mock_post.return_value = mock_response

        result = client.embed(["text1", "text2"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch("requests.sessions.Session.post")
    def test_embed_connection_error(self, mock_post, client):
        """Test handling of connection errors."""
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(requests.exceptions.ConnectionError):
            client.embed_single("test")

    @patch("requests.sessions.Session.post")
    def test_embed_timeout_error(self, mock_post, client):
        """Test handling of timeout errors."""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()

        with pytest.raises(requests.exceptions.Timeout):
            client.embed_single("test")

    @patch("requests.sessions.Session.post")
    def test_is_available_returns_true(self, mock_post, client):
        """Test is_available returns True when API works."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1]}]
        }
        mock_post.return_value = mock_response

        assert client.is_available() is True

    @patch("requests.sessions.Session.post")
    def test_is_available_returns_false_on_error(self, mock_post, client):
        """Test is_available returns False when API fails."""
        mock_post.side_effect = Exception("API error")

        assert client.is_available() is False

    @patch("requests.sessions.Session.post")
    def test_embed_retries_transient_errors(self, mock_post):
        """Test transient failures are retried before succeeding."""
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
        client = EmbeddingClient(
            api_url="http://localhost:1234/v1/embeddings",
            model="test-model",
            timeout=10,
            batch_size=2,
            retry_attempts=3,
            retry_backoff_seconds=0,
        )

        timeout_error = requests.exceptions.Timeout()
        success_response = MagicMock()
        success_response.json.return_value = {
            "data": [{"embedding": [0.11, 0.22, 0.33]}]
        }
        success_response.raise_for_status.return_value = None
        mock_post.side_effect = [timeout_error, success_response]

        result = client.embed_single("retry test")

        assert result == [0.11, 0.22, 0.33]
        assert mock_post.call_count == 2


class TestEmbeddingSerialization:
    """Tests for embedding serialization utilities."""

    def test_serialize_embedding(self):
        """Test serializing embedding to bytes."""
        from asky.research.embeddings import EmbeddingClient

        embedding = [1.0, 2.0, 3.0]
        serialized = EmbeddingClient.serialize_embedding(embedding)

        # Should be 12 bytes (3 floats * 4 bytes)
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

        client1 = get_embedding_client()
        client2 = get_embedding_client()

        assert client1 is client2

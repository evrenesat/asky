import pytest
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from asky.cli import openrouter


def test_cache_validation_valid():
    """Test is_cache_valid returns True for recent cache."""
    with patch("asky.cli.openrouter.get_cache_path") as mock_path:
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_path.return_value = mock_file

        data = {"fetched_at": datetime.now().isoformat(), "models": []}

        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            assert openrouter.is_cache_valid() is True


def test_cache_validation_expired():
    """Test is_cache_valid returns False for old cache."""
    with patch("asky.cli.openrouter.get_cache_path") as mock_path:
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_path.return_value = mock_file

        old_date = (datetime.now() - timedelta(days=2)).isoformat()
        data = {"fetched_at": old_date, "models": []}

        with patch("builtins.open", mock_open(read_data=json.dumps(data))):
            assert openrouter.is_cache_valid() is False


def test_cache_validation_missing():
    """Test is_cache_valid returns False when file missing."""
    with patch("asky.cli.openrouter.get_cache_path") as mock_path:
        mock_file = MagicMock()
        mock_file.exists.return_value = False
        mock_path.return_value = mock_file
        assert openrouter.is_cache_valid() is False


@patch("asky.cli.openrouter.requests.get")
def test_fetch_models_uses_cache(mock_get):
    """Test fetch_models uses cache if valid and no force_refresh."""
    with patch("asky.cli.openrouter.is_cache_valid", return_value=True):
        with patch("asky.cli.openrouter.get_cache_path") as mock_path:
            data = {"models": [{"id": "cached"}]}
            with patch("builtins.open", mock_open(read_data=json.dumps(data))):
                models = openrouter.fetch_models()
                assert models == [{"id": "cached"}]
                mock_get.assert_not_called()


@patch("asky.cli.openrouter.requests.get")
def test_fetch_models_refreshes_on_force(mock_get):
    """Test fetch_models calls API when forced."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": [{"id": "fresh"}]}
    mock_get.return_value = mock_response

    with patch("asky.cli.openrouter.get_cache_path") as mock_path:
        # Mock open for writing
        with patch("builtins.open", mock_open()):
            models = openrouter.fetch_models(force_refresh=True)
            assert models == [{"id": "fresh"}]
            mock_get.assert_called_once()


def test_search_models():
    """Test searching models by ID and name."""
    models = [
        {"id": "openai/gpt-4", "name": "GPT-4"},
        {"id": "anthropic/claude-3", "name": "Claude 3 Opus"},
        {"id": "meta/llama-3", "name": "Llama 3"},
    ]

    # Search by ID part
    results = openrouter.search_models("gpt", models)
    assert len(results) == 1
    assert results[0]["id"] == "openai/gpt-4"

    # Search by Name part
    results = openrouter.search_models("Opus", models)
    assert len(results) == 1
    assert results[0]["id"] == "anthropic/claude-3"

    # Case insensitive
    results = openrouter.search_models("LLAMA", models)
    assert len(results) == 1

import pytest
from unittest.mock import MagicMock, patch
from asky.core.api_client import get_llm_msg
from asky.config.loader import _hydrate_models, load_config


def test_hydrate_models_preserves_parameters():
    """Test that _hydrate_models preserves the parameters dictionary."""
    config = {
        "api": {"test_api": {"url": "http://test.com", "api_key": "secret"}},
        "models": {
            "test_model": {
                "id": "test-v1",
                "api": "test_api",
                "context_size": 1000,
                "parameters": {"temperature": 0.7, "max_tokens": 100},
            }
        },
    }

    hydrated = _hydrate_models(config)
    model_data = hydrated["models"]["test_model"]

    # Check regular fields
    assert model_data["base_url"] == "http://test.com"
    assert model_data["api_key"] == "secret"

    # Check parameters
    assert "parameters" in model_data
    assert model_data["parameters"]["temperature"] == 0.7
    assert model_data["parameters"]["max_tokens"] == 100


@patch("asky.core.api_client.requests.post")
def test_get_llm_msg_includes_parameters(mock_post):
    """Test that get_llm_msg includes provided parameters in the payload."""
    # Setup mock response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}]
    }
    mock_post.return_value = mock_response

    # Setup model config mock
    mock_models = {
        "test_model": {
            "id": "test-v1",
            "base_url": "http://test.com",
            "api_key": "secret",
        }
    }

    with patch("asky.config.MODELS", mock_models):
        messages = [{"role": "user", "content": "Hi"}]
        parameters = {"temperature": 0.5, "top_p": 0.9}

        get_llm_msg(model_id="test-v1", messages=messages, parameters=parameters)

        # Verify call arguments
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        assert payload["model"] == "test-v1"
        assert payload["temperature"] == 0.5
        assert payload["top_p"] == 0.9


@patch("asky.core.api_client.requests.post")
def test_get_llm_msg_ignores_none_parameters(mock_post):
    """Test that None values in parameters are excluded from the payload."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}]
    }
    mock_post.return_value = mock_response

    mock_models = {
        "test_model": {"id": "test-v1", "base_url": "http://test", "api_key": "k"}
    }

    with patch("asky.config.MODELS", mock_models):
        get_llm_msg(
            model_id="test-v1",
            messages=[],
            parameters={"temperature": 0.7, "seed": None},
        )

        payload = mock_post.call_args[1]["json"]
        assert payload["temperature"] == 0.7
        assert "seed" not in payload

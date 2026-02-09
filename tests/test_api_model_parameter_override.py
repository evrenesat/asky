from unittest.mock import patch

from asky.api import AskyClient, AskyConfig


def test_model_parameters_override_merges_with_model_defaults():
    models = {
        "test": {
            "id": "provider/test",
            "parameters": {"temperature": 0.7, "top_p": 0.9},
        }
    }

    with patch("asky.api.client.MODELS", models):
        client = AskyClient(
            AskyConfig(
                model_alias="test",
                model_parameters_override={"temperature": 0.2, "max_tokens": 256},
            )
        )

    assert client.model_config["parameters"] == {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 256,
    }
    # Original source config must not be mutated.
    assert models["test"]["parameters"]["temperature"] == 0.7


def test_model_parameters_override_allows_override_only_when_base_missing():
    models = {
        "test": {
            "id": "provider/test",
        }
    }

    with patch("asky.api.client.MODELS", models):
        client = AskyClient(
            AskyConfig(
                model_alias="test",
                model_parameters_override={"temperature": 0.1},
            )
        )

    assert client.model_config["parameters"] == {"temperature": 0.1}

"""Tests for interactive model configuration persistence helpers."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch
import tomllib
import sys

# Crucial: same import as minimal test
from asky.cli.models import (
    edit_model_command,
    save_model_config,
    add_model_command,
    prompt,
)

FAKE_MODELS = {
    "mymodel": {
        "id": "provider/mymodel",
        "api": "openrouter",
        "context_size": 32000,
        "source_shortlist_enabled": None,
        "parameters": {},
    }
}

FAKE_CONFIG = {
    "general": {
        "default_model": "other",
        "summarization_model": "other",
        "interface_model": "other",
        "default_image_model": "other",
    }
}


def _prepare_models_file(tmp_path: Path) -> Path:
    config_dir = tmp_path / ".config" / "asky"
    config_dir.mkdir(parents=True, exist_ok=True)
    models_path = config_dir / "models.toml"
    models_path.write_text("[models]\n")
    return models_path


def test_save_model_config_persists_context_and_shortlist_override(tmp_path):
    models_path = _prepare_models_file(tmp_path)

    with patch("asky.cli.models.Path.home", return_value=tmp_path):
        save_model_config(
            "nano",
            {
                "id": "gpt-5-nano",
                "api": "openai",
                "context_size": 120000,
                "source_shortlist_enabled": False,
                "image_support": True,
                "parameters": {"temperature": 0.2},
            },
        )

    with models_path.open("rb") as f:
        data = tomllib.load(f)

    model = data["models"]["nano"]
    assert model["context_size"] == 120000
    assert model["source_shortlist_enabled"] is False
    assert model["image_support"] is True
    assert model["parameters"]["temperature"] == 0.2


def test_save_model_config_omits_shortlist_override_when_auto(tmp_path):
    models_path = _prepare_models_file(tmp_path)

    with patch("asky.cli.models.Path.home", return_value=tmp_path):
        save_model_config(
            "std",
            {
                "id": "gpt-5",
                "api": "openai",
                "context_size": 256000,
                "source_shortlist_enabled": None,
                "image_support": None,
                "parameters": None,
            },
        )

    with models_path.open("rb") as f:
        data = tomllib.load(f)

    model = data["models"]["std"]
    assert model["context_size"] == 256000
    assert "source_shortlist_enabled" not in model
    assert "image_support" not in model


def test_edit_model_action_m_sets_main_model(tmp_path):
    """Choosing 'm' updates default_model and returns without touching model config."""
    _prepare_models_file(tmp_path)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.prompt.Prompt.ask", return_value="m"),
        patch("asky.cli.models.update_general_config") as mock_update,
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_update.assert_called_once_with("default_model", "mymodel")
    mock_save.assert_not_called()


def test_add_model_command_search_retry_flow(tmp_path):
    """Test that Step 2 retries on search failure and doesn't proceed to Context size."""

    # Mock models returned by OpenRouter
    mock_models = [
        {
            "id": "google/gemini-pro",
            "name": "Gemini Pro",
            "context_length": 128000,
            "supported_parameters": ["temperature"],
        }
    ]

    api_config = {
        "api": {
            "openrouter": {},
        }
    }

    # Flow:
    # 1. Select provider -> 1 (openrouter)
    # 2. Search query -> "gibberish"
    # 3. Action -> "s" (search again)
    # 4. Search query -> "gemini"
    # 5. Select model -> 1
    # 6. Context size -> 128000
    # 7. Nickname -> "gemini-pro"

    prompt_responses = [
        "gibberish",  # First search
        "s",  # Action: search again
        "gemini",  # Second search
        "gemini-pro",  # Nickname
    ]

    int_responses = [
        1,  # Select provider (openrouter)
        1,  # Select model from list
        128000,  # Context size
    ]

    def mock_prompt_ask(label, **kwargs):
        l_lower = label.lower()
        print(f"DEBUG TEST label='{label}'")
        if "pre-llm" in l_lower or "image input" in l_lower:
            return "auto"
        if any(kw in l_lower for kw in ["search", "action", "nickname"]):
            res = prompt_responses.pop(0)
            print(f"DEBUG TEST MATCH res='{res}'")
            return res
        return kwargs.get("default", "")

    def mock_int_prompt_ask(label, **kwargs):
        return int_responses.pop(0)

    with (
        patch("asky.cli.models.load_config", return_value=api_config),
        patch("asky.cli.models.openrouter.fetch_models", return_value=mock_models),
        patch("asky.cli.models.prompt.Prompt.ask", side_effect=mock_prompt_ask),
        patch("asky.cli.models.prompt.IntPrompt.ask", side_effect=mock_int_prompt_ask),
        patch("asky.cli.models.prompt.Confirm.ask", return_value=True),
        patch("asky.cli.models.save_model_config") as mock_save,
        patch("asky.cli.models.update_general_config"),
        patch("asky.cli.models.console.print") as mock_print,
    ):
        add_model_command()

    mock_save.assert_called_once()
    saved_alias, saved_cfg = mock_save.call_args[0]
    assert saved_alias == "gemini-pro"
    assert saved_cfg["id"] == "google/gemini-pro"

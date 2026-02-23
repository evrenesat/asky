"""Tests for interactive model configuration persistence helpers."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch
import tomllib

from asky.cli.models import edit_model_command, save_model_config

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


def _patch_edit_model(action: str, extra_inputs: list | None = None):
    """Return a context manager stack that mocks MODELS, load_config, and Prompt.ask."""
    inputs = [action] + (extra_inputs or [])
    prompt_iter = iter(inputs)

    def fake_prompt_ask(*args, **kwargs):
        return next(prompt_iter)

    return (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", side_effect=fake_prompt_ask),
    )


def test_edit_model_action_m_sets_main_model(tmp_path):
    """Choosing 'm' updates default_model and returns without touching model config."""
    _prepare_models_file(tmp_path)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", return_value="m"),
        patch("asky.cli.models.update_general_config") as mock_update,
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_update.assert_called_once_with("default_model", "mymodel")
    mock_save.assert_not_called()


def test_edit_model_action_s_sets_summarization_model(tmp_path):
    """Choosing 's' updates summarization_model and returns without touching model config."""
    _prepare_models_file(tmp_path)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", return_value="s"),
        patch("asky.cli.models.update_general_config") as mock_update,
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_update.assert_called_once_with("summarization_model", "mymodel")
    mock_save.assert_not_called()


def test_edit_model_action_i_sets_interface_model(tmp_path):
    """Choosing 'i' updates interface_model and returns without touching model config."""
    _prepare_models_file(tmp_path)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", return_value="i"),
        patch("asky.cli.models.update_general_config") as mock_update,
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_update.assert_called_once_with("interface_model", "mymodel")
    mock_save.assert_not_called()


def test_edit_model_action_g_sets_default_image_model(tmp_path):
    """Choosing 'g' updates default_image_model and returns without touching model config."""
    _prepare_models_file(tmp_path)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", return_value="g"),
        patch("asky.cli.models.update_general_config") as mock_update,
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_update.assert_called_once_with("default_image_model", "mymodel")
    mock_save.assert_not_called()


def test_edit_model_action_e_saves_changes(tmp_path):
    """Choosing 'e' enters parameter edit flow; confirming save writes model config."""
    _prepare_models_file(tmp_path)

    # First response: action choice. Then shortlist + image support prompts. Remaining: '' for params.
    fixed_responses = ["e", "auto", "auto"] + [""] * 20

    def fake_prompt(*args, **kwargs):
        return fixed_responses.pop(0)

    with (
        patch("asky.cli.models.MODELS", FAKE_MODELS),
        patch("asky.cli.models.load_config", return_value=FAKE_CONFIG),
        patch("asky.cli.models.Prompt.ask", side_effect=fake_prompt),
        patch("asky.cli.models.IntPrompt.ask", return_value=32000),
        patch("asky.cli.models.Confirm.ask", return_value=True),
        patch("asky.cli.models.save_model_config") as mock_save,
    ):
        edit_model_command("mymodel")

    mock_save.assert_called_once()
    saved_alias, saved_cfg = mock_save.call_args[0]
    assert saved_alias == "mymodel"
    assert saved_cfg["context_size"] == 32000

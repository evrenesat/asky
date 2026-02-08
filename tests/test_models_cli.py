"""Tests for interactive model configuration persistence helpers."""

from pathlib import Path
from unittest.mock import patch
import tomllib

from asky.cli.models import save_model_config


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
                "parameters": {"temperature": 0.2},
            },
        )

    with models_path.open("rb") as f:
        data = tomllib.load(f)

    model = data["models"]["nano"]
    assert model["context_size"] == 120000
    assert model["source_shortlist_enabled"] is False
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
                "parameters": None,
            },
        )

    with models_path.open("rb") as f:
        data = tomllib.load(f)

    model = data["models"]["std"]
    assert model["context_size"] == 256000
    assert "source_shortlist_enabled" not in model

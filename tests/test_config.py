from asky.config import MODELS, SYSTEM_PROMPT


def test_models_config():
    assert isinstance(MODELS, dict)
    assert len(MODELS) > 0
    for model_key, config in MODELS.items():
        assert "id" in config
        assert "context_size" in config


def test_system_prompt_params():
    # Verify strings are importable and non-empty
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0


def test_default_context_size():
    from asky.config import DEFAULT_CONTEXT_SIZE

    assert isinstance(DEFAULT_CONTEXT_SIZE, int)
    assert DEFAULT_CONTEXT_SIZE > 0


def test_xmpp_and_interface_config_params():
    from asky.config import (
        DEFAULT_IMAGE_MODEL,
        INTERFACE_PLANNER_SYSTEM_PROMPT,
        INTERFACE_MODEL,
        XMPP_COMMAND_PREFIX,
        XMPP_IMAGE_ENABLED,
        XMPP_IMAGE_PROMPT,
        XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE,
        XMPP_RESPONSE_CHUNK_CHARS,
        XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL,
        XMPP_VOICE_HF_TOKEN_ENV,
    )

    assert isinstance(INTERFACE_MODEL, str)
    assert isinstance(DEFAULT_IMAGE_MODEL, str)
    assert isinstance(INTERFACE_PLANNER_SYSTEM_PROMPT, str)
    assert INTERFACE_PLANNER_SYSTEM_PROMPT.strip()
    assert isinstance(XMPP_COMMAND_PREFIX, str)
    assert XMPP_COMMAND_PREFIX
    assert isinstance(XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE, bool)
    assert isinstance(XMPP_IMAGE_ENABLED, bool)
    assert isinstance(XMPP_IMAGE_PROMPT, str)
    assert XMPP_IMAGE_PROMPT
    assert isinstance(XMPP_RESPONSE_CHUNK_CHARS, int)
    assert XMPP_RESPONSE_CHUNK_CHARS >= 64
    assert isinstance(XMPP_VOICE_HF_TOKEN_ENV, str)
    assert XMPP_VOICE_HF_TOKEN_ENV
    assert isinstance(XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL, bool)


def test_invalid_config_exits(tmp_path):
    """Ensure invalid TOML raises SystemExit."""
    from unittest.mock import patch
    from asky.config.loader import load_config
    import pytest

    # Create invalid config
    config_dir = tmp_path / "asky"
    config_dir.mkdir()
    config_file = config_dir / "general.toml"
    config_file.write_text("invalid_toml = [")

    with patch("asky.config.loader._get_config_dir", return_value=config_dir):
        with pytest.raises(SystemExit) as excinfo:
            load_config()
        assert excinfo.value.code == 1

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from asky.core.prompts import construct_research_system_prompt


def test_research_prompt_monolithic():
    """Test fallback to monolithic prompt when components are missing."""
    mock_config = {
        "RESEARCH_SYSTEM_PROMPT": "Monolithic prompt {CURRENT_DATE}",
        "RESEARCH_SYSTEM_PREFIX": None,
        "RESEARCH_SYSTEM_SUFFIX": None,
        "RESEARCH_FORCE_SEARCH": None,
    }

    with (
        patch(
            "asky.config.RESEARCH_SYSTEM_PROMPT", mock_config["RESEARCH_SYSTEM_PROMPT"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_PREFIX", mock_config["RESEARCH_SYSTEM_PREFIX"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_SUFFIX", mock_config["RESEARCH_SYSTEM_SUFFIX"]
        ),
        patch(
            "asky.config.RESEARCH_FORCE_SEARCH", mock_config["RESEARCH_FORCE_SEARCH"]
        ),
    ):
        prompt = construct_research_system_prompt()
        assert "Monolithic prompt" in prompt
        assert datetime.now().strftime("%Y") in prompt


def test_research_prompt_modular():
    """Test construction from modular components."""
    mock_config = {
        "RESEARCH_SYSTEM_PROMPT": "Monolithic prompt",
        "RESEARCH_SYSTEM_PREFIX": "Prefix {CURRENT_DATE}",
        "RESEARCH_SYSTEM_SUFFIX": "Suffix",
        "RESEARCH_FORCE_SEARCH": "Force Search",
    }

    with (
        patch(
            "asky.config.RESEARCH_SYSTEM_PROMPT", mock_config["RESEARCH_SYSTEM_PROMPT"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_PREFIX", mock_config["RESEARCH_SYSTEM_PREFIX"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_SUFFIX", mock_config["RESEARCH_SYSTEM_SUFFIX"]
        ),
        patch(
            "asky.config.RESEARCH_FORCE_SEARCH", mock_config["RESEARCH_FORCE_SEARCH"]
        ),
    ):
        prompt = construct_research_system_prompt()
        assert "Prefix" in prompt
        assert "Force Search" in prompt
        assert "Suffix" in prompt
        assert "Monolithic prompt" not in prompt
        assert datetime.now().strftime("%Y") in prompt


def test_research_prompt_partial_modular():
    """Test construction with partial components."""
    mock_config = {
        "RESEARCH_SYSTEM_PROMPT": "Monolithic prompt",
        "RESEARCH_SYSTEM_PREFIX": "Prefix {CURRENT_DATE}",
        "RESEARCH_SYSTEM_SUFFIX": None,
        "RESEARCH_FORCE_SEARCH": None,
    }

    with (
        patch(
            "asky.config.RESEARCH_SYSTEM_PROMPT", mock_config["RESEARCH_SYSTEM_PROMPT"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_PREFIX", mock_config["RESEARCH_SYSTEM_PREFIX"]
        ),
        patch(
            "asky.config.RESEARCH_SYSTEM_SUFFIX", mock_config["RESEARCH_SYSTEM_SUFFIX"]
        ),
        patch(
            "asky.config.RESEARCH_FORCE_SEARCH", mock_config["RESEARCH_FORCE_SEARCH"]
        ),
    ):
        prompt = construct_research_system_prompt()
        assert "Prefix" in prompt
        assert "Force Search" not in prompt
        assert "Suffix" not in prompt
        assert "Monolithic prompt" not in prompt

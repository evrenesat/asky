import pytest
import dataclasses
from unittest.mock import MagicMock, patch
from asky.api.client import AskyClient
from asky.api.types import (
    AskyConfig,
    AskyTurnRequest,
    PreloadResolution,
    ContextResolution,
    SessionResolution,
)


@pytest.fixture
def mock_client(monkeypatch: pytest.MonkeyPatch):
    from asky.config import MODELS

    # Mock MODELS to prevent AskyClient.__init__ from failing
    monkeypatch.setitem(
        MODELS, "test-model", {"context_size": 4096, "id": "test-model-id"}
    )
    config = AskyConfig(model_alias="test-model")
    client = AskyClient(config)

    # Mock external dependencies used in run_turn to avoid side effects/network
    monkeypatch.setattr(
        "asky.api.client.run_preload_pipeline",
        MagicMock(return_value=PreloadResolution()),
    )
    monkeypatch.setattr(
        "asky.api.client.resolve_session_for_turn",
        MagicMock(
            return_value=(
                None,
                SessionResolution(
                    notices=[],
                    halt_reason=None,
                    research_mode=False,
                    max_turns=5,
                    memory_auto_extract=False,
                ),
            )
        ),
    )
    monkeypatch.setattr(
        "asky.api.client.load_context_from_history",
        MagicMock(return_value=ContextResolution()),
    )
    monkeypatch.setattr("asky.api.client.save_interaction", MagicMock())

    # Return empty output so post-run side effects (history/memory extraction) are skipped.
    client.run_messages = MagicMock(return_value="")

    return client


def test_memory_trigger_prefix_removal_case_insensitive(mock_client):
    """Global memory trigger prefixes should be stripped case-insensitively."""
    with patch.object(AskyClient, "build_messages") as mock_build:
        mock_build.return_value = []
        with patch(
            "asky.api.client.USER_MEMORY_GLOBAL_TRIGGERS", ["remember globally:"]
        ):
            request = AskyTurnRequest(query_text="REMEMBER GLOBALLY: Buy milk")
            mock_client.run_turn(request)

            # Verify the query_text passed to build_messages has the trigger removed
            assert mock_build.call_args[1]["query_text"] == "Buy milk"


def test_memory_trigger_prefix_removal_unicode_safe(mock_client):
    """Trigger-prefix stripping should stay correct for casefold length changes."""
    with patch.object(AskyClient, "build_messages") as mock_build:
        mock_build.return_value = []
        # 'ẞ' (U+1E9E) casefolds to 'ss' (length 1 -> 2)
        with patch("asky.api.client.USER_MEMORY_GLOBAL_TRIGGERS", ["ẞ:"]):
            # Case 1: Input starts with original trigger char
            request = AskyTurnRequest(query_text="ẞ: test")
            mock_client.run_turn(request)
            assert mock_build.call_args_list[-1][1]["query_text"] == "test"

            # Case 2: Input starts with case-equivalent 'SS'
            # Both 'ẞ' and 'SS' casefold to 'ss', so they should match.
            request = AskyTurnRequest(query_text="SS: test")
            mock_client.run_turn(request)
            assert mock_build.call_args_list[-1][1]["query_text"] == "test"


def test_research_mode_resolution_boolean_robustness(mock_client):
    """Boolean session overrides should drive `research_mode` directly."""
    with patch("asky.api.client.resolve_session_for_turn") as mock_resolve:
        mock_res = SessionResolution(
            notices=[],
            halt_reason=None,
            research_mode=True,
            max_turns=5,
            memory_auto_extract=False,
        )
        mock_resolve.return_value = (None, mock_res)

        request = AskyTurnRequest(query_text="test")
        mock_client.run_turn(request)

        # Verify research_mode was passed as True to run_messages
        assert mock_client.run_messages.call_args[1]["research_mode"] is True


def test_research_mode_resolution_invalid_type_fallback(mock_client):
    """Non-boolean session values should fall back to the client configuration."""
    # Force config to False to test fallback logic
    mock_client.config = dataclasses.replace(mock_client.config, research_mode=False)

    with patch("asky.api.client.resolve_session_for_turn") as mock_resolve:
        # Simulate a leaky integer value (e.g., 1 from SQLite) that isn't True/False
        mock_res = SessionResolution(
            notices=[],
            halt_reason=None,
            research_mode=1,
            max_turns=5,
            memory_auto_extract=False,
        )
        mock_resolve.return_value = (None, mock_res)

        request = AskyTurnRequest(query_text="test")
        mock_client.run_turn(request)

        # Should fallback to config.research_mode (False) because 1 is not a boolean
        assert mock_client.run_messages.call_args[1]["research_mode"] is False

import pytest
import dataclasses
from unittest.mock import MagicMock, patch
from asky.api.client import AskyClient
from asky.api.types import (
    AskyConfig,
    AskyTurnRequest,
    PreloadResolution,
    ContextResolution,
)


@pytest.fixture
def mock_client():
    from asky.config import MODELS

    with pytest.MonkeyPatch.context() as mp:
        # Mock MODELS to prevent AskyClient.__init__ from failing
        mp.setitem(MODELS, "test-model", {"context_size": 4096, "id": "test-model-id"})
        config = AskyConfig(model_alias="test-model")
        client = AskyClient(config)

        # Mock external dependencies used in run_turn to avoid side effects/network
        client.run_preload_pipeline = MagicMock(return_value=PreloadResolution())
        mp.setattr(
            "asky.api.client.resolve_session_for_turn",
            MagicMock(
                return_value=(
                    None,
                    MagicMock(
                        notices=[], halt_reason=None, research_mode=False, max_turns=5
                    ),
                )
            ),
        )
        mp.setattr(
            "asky.api.client.load_context_from_history",
            MagicMock(return_value=ContextResolution()),
        )
        mp.setattr("asky.api.client.save_interaction", MagicMock())

        # Always patch run_messages to avoid executing the actual conversation engine
        client.run_messages = MagicMock(return_value="OK")

        return client


def test_memory_trigger_prefix_removal_case_insensitive(mock_client):
    """
    Regression test for C-01: Verifies that global memory triggers are correctly
    identified and stripped from the query text regardless of case.
    """
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
    """
    Regression test for C-01: Verifies that trigger removal is robust against
    Unicode characters that change length when casefolded (e.g., 'ẞ' -> 'ss').
    """
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
    """
    Regression test for C-02: Verifies that research_mode is correctly enabled
    when session resolution returns an explicit boolean True.
    """
    with patch("asky.api.client.resolve_session_for_turn") as mock_resolve:
        mock_res = MagicMock(
            notices=[], halt_reason=None, research_mode=True, max_turns=5
        )
        mock_resolve.return_value = (None, mock_res)

        request = AskyTurnRequest(query_text="test")
        mock_client.run_turn(request)

        # Verify research_mode was passed as True to run_messages
        assert mock_client.run_messages.call_args[1]["research_mode"] is True


def test_research_mode_resolution_invalid_type_fallback(mock_client):
    """
    Regression test for C-02: Verifies that if an invalid type (e.g., an integer 0/1
    directly from an un-cast DB field) is encountered, the resolver falls back to
    the safe configuration default instead of using the raw value.
    """
    # Force config to False to test fallback logic
    mock_client.config = dataclasses.replace(mock_client.config, research_mode=False)

    with patch("asky.api.client.resolve_session_for_turn") as mock_resolve:
        # Simulate a leaky integer value (e.g., 1 from SQLite) that isn't True/False
        mock_res = MagicMock(notices=[], halt_reason=None, research_mode=1, max_turns=5)
        mock_resolve.return_value = (None, mock_res)

        request = AskyTurnRequest(query_text="test")
        mock_client.run_turn(request)

        # Should fallback to config.research_mode (False) because 1 is not a boolean
        assert mock_client.run_messages.call_args[1]["research_mode"] is False

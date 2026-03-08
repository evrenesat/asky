
import pytest
from unittest.mock import MagicMock, patch
from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.api.types import SessionResolution, PreloadResolution

@pytest.fixture(autouse=True)
def mock_models():
    models = {"gpt4": {"id": "gpt-4"}, "helper-model": {"id": "helper-1"}}
    with patch("asky.config.MODELS", models), \
         patch("asky.api.client.MODELS", models):
        yield

@pytest.fixture
def mock_policy_engine():
    with patch("asky.api.interface_query_policy.InterfaceQueryPolicyEngine") as mock:
        engine = mock.return_value
        engine.decide.return_value = MagicMock(
            shortlist_enabled=True,
            memory_action={"memory": "test", "scope": "global"},
            prompt_enrichment="enriched"
        )
        yield mock

@patch("asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution()))
@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch("asky.api.client.AskyClient.run_messages", return_value="Final")
@patch("asky.api.client.save_interaction")
@patch("asky.memory.tools.execute_save_memory")
def test_helper_disabled_when_interface_model_empty(
    mock_save_mem, mock_save_int, mock_run, mock_preload, mock_resolve, mock_policy_engine
):
    # Ensure INTERFACE_MODEL is empty
    with patch("asky.config.INTERFACE_MODEL", ""):
        client = AskyClient(AskyConfig(model_alias="gpt4"))
        client.run_turn(AskyTurnRequest(query_text="test"))
        
        mock_policy_engine.assert_not_called()
        mock_save_mem.assert_not_called()

@patch("asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution()))
@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch("asky.api.client.AskyClient.run_messages", return_value="Final")
@patch("asky.api.client.save_interaction")
@patch("asky.memory.tools.execute_save_memory")
def test_helper_disabled_in_lean_mode(
    mock_save_mem, mock_save_int, mock_run, mock_preload, mock_resolve, mock_policy_engine
):
    with patch("asky.config.INTERFACE_MODEL", "helper-model"):
        client = AskyClient(AskyConfig(model_alias="gpt4"))
        # request.lean = True
        client.run_turn(AskyTurnRequest(query_text="test", lean=True))
        
        mock_policy_engine.assert_not_called()
        mock_save_mem.assert_not_called()

@patch("asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution()))
@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch("asky.api.client.AskyClient.run_messages", return_value="Final")
@patch("asky.api.client.save_interaction")
@patch("asky.memory.tools.execute_save_memory")
def test_helper_memory_skipped_when_save_memory_disabled(
    mock_save_mem, mock_save_int, mock_run, mock_preload, mock_resolve, mock_policy_engine
):
    with patch("asky.config.INTERFACE_MODEL", "helper-model"):
        client = AskyClient(AskyConfig(model_alias="gpt4"))
        client.run_turn(AskyTurnRequest(query_text="test", disabled_tools={"save_memory"}))
        
        mock_policy_engine.assert_called_once()
        mock_save_mem.assert_not_called()

@patch("asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution()))
@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch("asky.api.client.AskyClient.run_messages", return_value="Final")
@patch("asky.api.client.save_interaction")
@patch("asky.memory.tools.execute_save_memory")
def test_helper_active_when_configured_and_not_lean(
    mock_save_mem, mock_save_int, mock_run, mock_preload, mock_resolve, mock_policy_engine
):
    with patch("asky.config.INTERFACE_MODEL", "helper-model"):
        client = AskyClient(AskyConfig(model_alias="gpt4"))
        client.run_turn(AskyTurnRequest(query_text="test"))
        
        mock_policy_engine.assert_called_once()
        mock_save_mem.assert_called_once()

@patch("asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution()))
@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch("asky.api.client.AskyClient.run_messages", return_value="Final")
@patch("asky.api.client.save_interaction")
@patch("asky.memory.tools.execute_save_memory")
def test_helper_memory_forces_global_scope(
    mock_save_mem, mock_save_int, mock_run, mock_preload, mock_resolve, mock_policy_engine
):
    with patch("asky.config.INTERFACE_MODEL", "helper-model"):
        # Model returns extra keys and a fake session_id
        mock_policy_engine.return_value.decide.return_value = MagicMock(
            shortlist_enabled=True,
            memory_action={"memory": "test fact", "scope": "global", "session_id": 999, "extra": "stuff"},
            prompt_enrichment=None
        )
        
        client = AskyClient(AskyConfig(model_alias="gpt4"))
        client.run_turn(AskyTurnRequest(query_text="test"))
        
        # Verify sanitized call
        mock_save_mem.assert_called_once()
        args = mock_save_mem.call_args[0][0]
        assert args["memory"] == "test fact"
        assert args["session_id"] is None
        assert "extra" not in args

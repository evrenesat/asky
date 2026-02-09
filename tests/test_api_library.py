from unittest.mock import MagicMock, patch

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.api.types import ContextResolution, PreloadResolution, SessionResolution


def test_asky_client_build_messages_with_context_and_preloaded_sources():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=True,
        )
    )
    messages = client.build_messages(
        query_text="What happened?",
        context_str="Prior context",
        source_shortlist_context="1. https://example.com",
    )

    assert messages[0]["role"] == "system"
    assert "research assistant" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"
    assert "Context from previous queries" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "Preloaded sources gathered before tool calls" in messages[2]["content"]


@patch("asky.api.client.create_default_tool_registry")
@patch("asky.api.client.ConversationEngine")
def test_asky_client_run_messages_uses_default_registry(
    mock_engine_cls, mock_create_default_registry
):
    registry = MagicMock()
    registry.get_system_prompt_guidelines.return_value = [
        "`web_search`: Discover initial sources first."
    ]
    mock_create_default_registry.return_value = registry

    engine = MagicMock()
    engine.run.return_value = "Answer"
    mock_engine_cls.return_value = engine

    client = AskyClient(AskyConfig(model_alias="gf"))
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "Q"}]

    final_answer = client.run_messages(messages)

    assert final_answer == "Answer"
    mock_create_default_registry.assert_called_once()
    mock_engine_cls.assert_called_once()
    engine.run.assert_called_once_with(messages, display_callback=None)
    assert "Enabled Tool Guidelines:" in messages[0]["content"]


@patch("asky.api.client.create_research_tool_registry")
@patch("asky.api.client.ConversationEngine")
def test_asky_client_run_messages_uses_research_registry(
    mock_engine_cls, mock_create_research_registry
):
    registry = MagicMock()
    registry.get_system_prompt_guidelines.return_value = []
    mock_create_research_registry.return_value = registry

    engine = MagicMock()
    engine.run.return_value = "Answer"
    mock_engine_cls.return_value = engine

    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=True,
            disabled_tools={"web_search"},
        )
    )
    messages = [{"role": "system", "content": "System"}, {"role": "user", "content": "Q"}]

    client.run_messages(messages, research_session_id="42")

    mock_create_research_registry.assert_called_once_with(
        usage_tracker=client.usage_tracker,
        disabled_tools={"web_search"},
        session_id="42",
    )


@patch("asky.api.client.generate_summaries", return_value=("query-sum", "answer-sum"))
@patch.object(AskyClient, "run_messages", return_value="Answer")
def test_asky_client_chat_returns_structured_result(
    mock_run_messages, mock_generate_summaries
):
    client = AskyClient(AskyConfig(model_alias="gf"))
    result = client.chat(query_text="Question")

    assert result.final_answer == "Answer"
    assert result.query_summary == "query-sum"
    assert result.answer_summary == "answer-sum"
    assert result.model_alias == "gf"
    mock_run_messages.assert_called_once()
    mock_generate_summaries.assert_called_once_with(
        "Question",
        "Answer",
        usage_tracker=client.summarization_tracker,
    )


@patch("asky.api.client.save_interaction")
@patch("asky.api.client.generate_summaries", return_value=("qsum", "asum"))
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(
        combined_context="Preloaded context",
        shortlist_stats={"enabled": True},
    ),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
@patch(
    "asky.api.client.load_context_from_history",
    return_value=ContextResolution(context_str="Context text", resolved_ids=[1, 2]),
)
def test_asky_client_run_turn_full_flow_non_session(
    mock_load_context,
    mock_resolve_session,
    mock_preload,
    mock_run_messages,
    mock_generate_summaries,
    mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf"))
    result = client.run_turn(
        AskyTurnRequest(
            query_text="Question",
            continue_ids="1,2",
            summarize_context=True,
        )
    )

    assert result.halted is False
    assert result.final_answer == "Final"
    assert result.query_summary == "qsum"
    assert result.answer_summary == "asum"
    assert result.context.resolved_ids == [1, 2]
    assert result.preload.combined_context == "Preloaded context"
    mock_load_context.assert_called_once_with("1,2", True)
    mock_resolve_session.assert_called_once()
    mock_preload.assert_called_once()
    mock_run_messages.assert_called_once()
    mock_save_interaction.assert_called_once_with(
        "Question", "Final", "gf", "qsum", "asum"
    )


@patch.object(AskyClient, "run_messages")
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(
        None,
        SessionResolution(
            event="session_resume_ambiguous",
            halt_reason="session_ambiguous",
            notices=["Multiple sessions found for 'foo'"],
            matched_sessions=[{"id": 1, "name": "a", "created_at": "ts"}],
        ),
    ),
)
def test_asky_client_run_turn_halts_on_ambiguous_session(
    mock_resolve_session,
    mock_run_messages,
):
    client = AskyClient(AskyConfig(model_alias="gf"))
    result = client.run_turn(
        AskyTurnRequest(
            query_text="",
            resume_session_term="foo",
        )
    )

    assert result.halted is True
    assert result.halt_reason == "session_ambiguous"
    assert result.final_answer == ""
    mock_resolve_session.assert_called_once()
    mock_run_messages.assert_not_called()

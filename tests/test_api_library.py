from unittest.mock import MagicMock, patch, ANY

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
        preload=PreloadResolution(
            combined_context="1. https://example.com",
        ),
    )

    assert messages[0]["role"] == "system"
    assert "research assistant" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"
    assert "Context from previous queries" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    assert "Preloaded sources gathered before tool calls" in messages[2]["content"]


def test_asky_client_build_messages_contains_seed_url_context_block():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=False,
        )
    )
    messages = client.build_messages(
        query_text="Summarize this URL",
        preload=PreloadResolution(
            combined_context=(
                "Seed URL Content from Query:\n"
                "1. URL: https://example.com\n"
                "   Delivery status: full_content\n"
                "   Content:\nExample content"
            ),
        ),
    )

    assert "Seed URL Content from Query:" in messages[-1]["content"]
    assert "Delivery status: full_content" in messages[-1]["content"]


def test_asky_client_build_messages_seed_direct_answer_instruction():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=False,
        )
    )
    messages = client.build_messages(
        query_text="Summarize",
        preload=PreloadResolution(
            seed_url_direct_answer_ready=True,
            combined_context=(
                "Seed URL Content from Query:\n"
                "1. URL: https://example.com\n"
                "   Delivery status: full_content\n"
                "   Content:\nExample content"
            ),
        ),
    )
    assert "do NOT call get_url_content/get_url_details for the same URL" in messages[-1][
        "content"
    ]


def test_asky_client_build_messages_keeps_verify_instruction_when_seed_not_ready():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=False,
        )
    )
    messages = client.build_messages(
        query_text="Summarize",
        preload=PreloadResolution(
            seed_url_direct_answer_ready=False,
            combined_context="Shortlist context",
        ),
    )
    assert (
        "Use this preloaded corpus as a starting point, then verify with tools before citing."
        in messages[-1]["content"]
    )


def test_asky_client_build_messages_adds_local_kb_guidance():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=True,
        )
    )

    messages = client.build_messages(
        query_text="Answer this",
        local_kb_hint_enabled=True,
    )

    assert messages[0]["role"] == "system"
    assert "Local Knowledge Base Guidance" in messages[0]["content"]
    assert "query_research_memory" in messages[0]["content"]


@patch("asky.api.client.create_tool_registry")
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
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Q"},
    ]

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
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Q"},
    ]

    client.run_messages(messages, research_session_id="42", preload=PreloadResolution())

    mock_create_research_registry.assert_called_once_with(
        usage_tracker=client.usage_tracker,
        disabled_tools={"web_search"},
        session_id="42",
        corpus_preloaded=False,
        summarization_tracker=client.summarization_tracker,
        tool_trace_callback=None,
    )


@patch.object(AskyClient, "run_messages", return_value="Answer")
def test_asky_client_chat_returns_structured_result(mock_run_messages):
    client = AskyClient(AskyConfig(model_alias="gf"))
    result = client.chat(query_text="Question")

    assert result.final_answer == "Answer"
    assert result.query_summary == ""
    assert result.answer_summary == ""
    assert result.model_alias == "gf"
    mock_run_messages.assert_called_once()


@patch("asky.api.client.save_interaction")
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
    assert result.query_summary == ""
    assert result.answer_summary == ""
    assert result.context.resolved_ids == [1, 2]
    assert result.preload.combined_context == "Preloaded context"
    mock_load_context.assert_called_once_with("1,2", True)
    mock_resolve_session.assert_called_once()
    mock_preload.assert_called_once()
    mock_run_messages.assert_called_once()
    mock_save_interaction.assert_called_once_with("Question", "Final", "gf", "", "")


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


@patch("asky.api.client.save_interaction")
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(
        combined_context="Preloaded context",
        local_payload={"targets": ["/tmp/corpus/doc.md"], "ingested": []},
        shortlist_stats={"enabled": True},
    ),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
@patch("asky.api.client.create_research_tool_registry")
def test_asky_client_run_turn_redacts_local_targets_for_model(
    mock_create_registry,
    mock_resolve_session,
    mock_preload,
    mock_run_messages,
    mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))

    result = client.run_turn(
        AskyTurnRequest(
            query_text="Use /tmp/corpus/doc.md and summarize the policy changes",
        )
    )

    assert result.halted is False
    assert "/tmp/corpus/doc.md" not in result.messages[-1]["content"]
    assert "summarize the policy changes" in result.messages[-1]["content"]
    assert "Local Knowledge Base Guidance" in result.messages[0]["content"]
    mock_resolve_session.assert_called_once()
    mock_preload.assert_called_once()
    mock_run_messages.assert_called_once_with(
        result.messages,
        session_manager=ANY,
        research_session_id=None,
        preload=result.preload,
        display_callback=None,
        verbose_output_callback=None,
        summarization_status_callback=None,
        event_callback=None,
        lean=False,
        disabled_tools=None,
        max_turns=ANY,
    )
    mock_save_interaction.assert_called_once()


@patch("asky.api.client.run_preload_pipeline", return_value=PreloadResolution())
@patch(
    "asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution())
)
@patch("asky.api.client.AskyClient.run_messages")
@patch("asky.api.client.save_interaction")
def test_asky_client_run_turn_propagates_local_corpus_paths(
    mock_save, mock_run, mock_resolve_session, mock_preload
):
    client = AskyClient(AskyConfig(model_alias="gf"))
    request = AskyTurnRequest(query_text="Q", local_corpus_paths=["/a/b"])

    # Mock run_messages to avoid actual LLM call/hang
    mock_run.return_value = "Final"

    client.run_turn(request)

    mock_run.assert_called_once()


@patch("asky.api.client.save_interaction")
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(
        seed_url_context="seed context",
        shortlist_context="shortlist context",
        combined_context="combined context",
        shortlist_payload={
            "seed_url_documents": [
                {
                    "url": "https://example.com/a",
                    "resolved_url": "https://example.com/a",
                    "title": "Doc A",
                    "content": "Alpha",
                    "error": "",
                    "warning": "",
                }
            ],
            "candidates": [
                {
                    "rank": 1,
                    "url": "https://example.com/a",
                    "source_type": "seed",
                    "final_score": 0.9,
                    "snippet": "snippet",
                    "why_selected": ["semantic_similarity=0.9"],
                }
            ],
            "warnings": [],
        },
    ),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
def test_run_turn_emits_preload_provenance_event(
    _mock_resolve_session,
    _mock_preload,
    _mock_run_messages,
    _mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf", verbose=True))
    events = []
    client.run_turn(
        AskyTurnRequest(query_text="Question"),
        verbose_output_callback=events.append,
    )

    preload_events = [
        event
        for event in events
        if isinstance(event, dict) and event.get("kind") == "preload_provenance"
    ]
    assert len(preload_events) == 1
    assert preload_events[0]["combined_context_chars"] == len("combined context")


@patch("asky.api.client.run_preload_pipeline")
@patch(
    "asky.api.client.resolve_session_for_turn", return_value=(None, SessionResolution())
)
@patch("asky.api.client.AskyClient.run_messages")
@patch("asky.api.client.save_interaction")
def test_asky_client_run_turn_enables_hint_with_only_explicit_paths(
    mock_save, mock_run, mock_resolve_session, mock_preload
):
    # Setup preload to return NO discovered targets
    mock_preload.return_value = PreloadResolution(local_payload={"targets": []})

    mock_run.return_value = "Final"

    client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))
    # Provide explicit paths but query has no targets
    request = AskyTurnRequest(
        query_text="Generic query", local_corpus_paths=["/opt/explicit"]
    )

    result = client.run_turn(request)
    assert result.final_answer == "Final"
    mock_run.assert_called_once()

    # Verify hint was injected despite empty local_payload targets
    # (The hint is usually "Local Knowledge Base Guidance" in system prompt or similar)
    # Based on client.py logic: local_kb_hint_enabled -> redact_local_source_targets call
    # We can check if the hint exists in messages.

    # Check for the hint in system prompt or messages
    assert any(
        "Local Knowledge Base Guidance" in m["content"]
        for m in mock_run.call_args.args[0]
        if m["role"] == "system"
    )
    # Verify local_corpus_paths reached the pipeline
    _, kwargs = mock_preload.call_args
    assert kwargs["local_corpus_paths"] == ["/opt/explicit"]


@patch("asky.api.client.save_interaction")
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(
        seed_url_direct_answer_ready=True,
        combined_context="Seed URL Content from Query",
    ),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
def test_run_turn_disables_retrieval_tools_when_seed_direct_mode_ready(
    _mock_resolve_session,
    _mock_preload,
    mock_run_messages,
    _mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf", research_mode=False))
    client.run_turn(AskyTurnRequest(query_text="Summarize https://example.com"))

    kwargs = mock_run_messages.call_args.kwargs
    assert kwargs["disabled_tools"] == {"web_search", "get_url_content", "get_url_details"}


@patch("asky.api.client.save_interaction")
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
    return_value=PreloadResolution(
        seed_url_direct_answer_ready=True,
        combined_context="Seed URL Content from Query",
    ),
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
def test_run_turn_does_not_disable_retrieval_tools_in_research_mode(
    _mock_resolve_session,
    _mock_preload,
    mock_run_messages,
    _mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))
    client.run_turn(AskyTurnRequest(query_text="Summarize https://example.com"))

    kwargs = mock_run_messages.call_args.kwargs
    assert kwargs["disabled_tools"] is None


def test_asky_client_build_messages_adds_retrieval_only_guidance():
    config = AskyConfig(model_alias="gf", research_mode=True)
    client = AskyClient(config)

    messages = client.build_messages(
        query_text="foo",
        preload=PreloadResolution(
            local_payload={"stats": {"indexed_chunks": 1}},
            combined_context="preloaded context",
        ),
    )

    system_msg = next(m["content"] for m in messages if m["role"] == "system")
    assert "A research corpus has been pre-loaded" in system_msg
    assert "Do NOT attempt to browse new URLs" in system_msg


def test_asky_client_build_messages_no_retrieval_guidance_when_not_preloaded():
    config = AskyConfig(model_alias="gf", research_mode=True)
    client = AskyClient(config)

    messages = client.build_messages(
        query_text="foo",
        preload=PreloadResolution(
            combined_context="preloaded context",
        ),
    )

    system_msg = next(m["content"] for m in messages if m["role"] == "system")
    assert "A research corpus has been pre-loaded" not in system_msg


def test_asky_client_build_messages_uses_configured_retrieval_guidance_override():
    client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))

    with patch(
        "asky.config.RESEARCH_RETRIEVAL_ONLY_GUIDANCE_PROMPT",
        "CUSTOM RETRIEVAL GUIDANCE",
    ):
        messages = client.build_messages(
            query_text="foo",
            preload=PreloadResolution(
                local_payload={"stats": {"indexed_chunks": 1}},
                combined_context="preloaded context",
            ),
        )

    system_msg = next(m["content"] for m in messages if m["role"] == "system")
    assert "CUSTOM RETRIEVAL GUIDANCE" in system_msg
    assert "A research corpus has been pre-loaded" not in system_msg


@patch("asky.api.client.save_interaction")
@patch.object(AskyClient, "run_messages", return_value="Final")
@patch(
    "asky.api.client.run_preload_pipeline",
)
@patch(
    "asky.api.client.resolve_session_for_turn",
    return_value=(None, SessionResolution()),
)
def test_asky_client_run_turn_passes_corpus_preloaded_to_run_messages(
    mock_resolve_session,
    mock_preload,
    mock_run_messages,
    mock_save_interaction,
):
    client = AskyClient(AskyConfig(model_alias="gf", research_mode=True))

    # Case 1: Local indexed chunks > 0
    mock_preload.return_value = PreloadResolution(
        local_payload={"stats": {"indexed_chunks": 5}},
        shortlist_payload={"fetched_count": 0},
    )
    client.run_turn(AskyTurnRequest(query_text="foo"))
    _, kwargs = mock_run_messages.call_args
    assert kwargs["preload"].is_corpus_preloaded is True

    # Case 2: Web shortlist fetched > 0
    mock_preload.return_value = PreloadResolution(
        local_payload={"stats": {"indexed_chunks": 0}},
        shortlist_payload={"fetched_count": 3},
    )
    client.run_turn(AskyTurnRequest(query_text="foo"))
    _, kwargs = mock_run_messages.call_args
    assert kwargs["preload"].is_corpus_preloaded is True

    # Case 3: Neither
    mock_preload.return_value = PreloadResolution(
        local_payload={"stats": {"indexed_chunks": 0}},
        shortlist_payload={"fetched_count": 0},
    )
    client.run_turn(AskyTurnRequest(query_text="foo"))
    _, kwargs = mock_run_messages.call_args
    assert kwargs["preload"].is_corpus_preloaded is False


def test_asky_client_uses_system_prompt_override():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            system_prompt_override="Override Prompt",
        )
    )
    messages = client.build_messages(query_text="Hi")
    assert messages[0]["role"] == "system"
    assert "Override Prompt" in messages[0]["content"]
    assert "helpful assistant" not in messages[0]["content"]


def test_asky_client_override_with_research_guidance_and_hints():
    client = AskyClient(
        AskyConfig(
            model_alias="gf",
            research_mode=True,
            system_prompt_override="Override Prompt",
        )
    )
    # Mock preload where is_corpus_preloaded=True
    preload = MagicMock()
    preload.is_corpus_preloaded = True

    messages = client.build_messages(
        query_text="Hi", preload=preload, local_kb_hint_enabled=True
    )
    assert "Override Prompt" in messages[0]["content"]
    # Check that research guidance is STILL appended
    assert "A research corpus has been pre-loaded" in messages[0]["content"]
    assert "Local Knowledge Base Guidance" in messages[0]["content"]

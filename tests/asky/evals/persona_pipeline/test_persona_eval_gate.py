"""Deterministic evaluation gate for persona behavior."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.cli.mention_parser import parse_persona_mention
from asky.plugins.manual_persona_creator.storage import (
    CHUNKS_FILENAME,
    METADATA_FILENAME,
    PERSONA_SCHEMA_VERSION,
    PROMPT_FILENAME,
    write_chunks,
    write_metadata,
)
from asky.plugins.manual_persona_creator.knowledge_catalog import write_catalog
from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaKnowledgeEntry,
    PersonaSourceClass,
    PersonaSourceRecord,
    PersonaTrustClass,
)
from asky.plugins.manual_persona_creator.runtime_index import rebuild_runtime_index
from asky.plugins.persona_manager.knowledge import rebuild_embeddings
from asky.plugins.persona_manager.session_binding import set_session_binding
from asky.evals.persona_pipeline.assertions import evaluate_persona_answer
from asky.plugins.runtime import get_or_create_plugin_runtime


class _FakeEmbeddingClient:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]
    def embed_single(self, text):
        return [1.0, 0.0]


@pytest.fixture(autouse=True)
def mock_models(monkeypatch):
    import asky.api.client
    monkeypatch.setattr(asky.api.client, "MODELS", {"openai/gpt-4o-mini": {"alias": "openai/gpt-4o-mini", "id": "gpt-4o-mini", "parameters": {}}})


@pytest.fixture
def eval_persona_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "asky.plugins.persona_manager.knowledge.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )
    monkeypatch.setattr(
        "asky.plugins.persona_manager.runtime_planner.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.runtime_index.get_embedding_client",
        lambda: _FakeEmbeddingClient(),
    )
    
    # Mock ASKY_HOME for all components
    monkeypatch.setenv("ASKY_HOME", str(tmp_path))
    
    # Force fresh DB for each test by patching DB_PATH everywhere
    db_path = tmp_path / "history.db"
    import asky.config
    import asky.storage.sqlite
    import asky.storage
    
    monkeypatch.setattr(asky.config, "DB_PATH", db_path)
    monkeypatch.setattr(asky.storage.sqlite, "DB_PATH", db_path)
    
    from asky.storage.sqlite import SQLiteHistoryRepository
    new_repo = SQLiteHistoryRepository()
    monkeypatch.setattr(asky.storage, "_repo", new_repo)
    new_repo.init_db()

    # Create plugins.toml with persona_manager enabled
    (tmp_path / "plugins.toml").write_text("[persona_manager]\nenabled = true\n")
    
    persona_data_root = tmp_path / "plugins" / "persona_manager"
    persona_root = persona_data_root / "personas" / "eval_p"
    persona_root.mkdir(parents=True)
    
    metadata = {
        "persona": {
            "name": "eval_p",
            "schema_version": PERSONA_SCHEMA_VERSION,
        }
    }
    write_metadata(persona_root / METADATA_FILENAME, metadata)
    (persona_root / PROMPT_FILENAME).write_text("Test Persona")
    
    sources = [
        PersonaSourceRecord(
            source_id="s1",
            source_class=PersonaSourceClass.AUTHORED_BOOK,
            trust_class=PersonaTrustClass.AUTHORED_PRIMARY,
            label="Book 1",
        ),
        PersonaSourceRecord(
            source_id="s2",
            source_class=PersonaSourceClass.MANUAL_SOURCE,
            trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
            label="Notes 2",
        ),
    ]
    entries = [
        PersonaKnowledgeEntry(
            entry_id="chunk:e1",
            entry_kind=PersonaEntryKind.RAW_CHUNK,
            source_id="s1",
            text="The secret code is 1234.",
            metadata={"chunk_index": 0},
        ),
        PersonaKnowledgeEntry(
            entry_id="chunk:e2",
            entry_kind=PersonaEntryKind.RAW_CHUNK,
            source_id="s2",
            text="The code was changed in 2025.",
            metadata={"chunk_index": 0},
        ),
    ]
    write_catalog(persona_root, sources, entries)
    
    chunks = [
        {"chunk_id": "e1", "text": "The secret code is 1234.", "source": "Book 1"},
        {"chunk_id": "e2", "text": "The code was changed in 2025.", "source": "Notes 2"},
    ]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)
    rebuild_embeddings(persona_dir=persona_root, chunks=chunks)
    rebuild_runtime_index(persona_dir=persona_root)
    
    return tmp_path


def _create_client() -> AskyClient:
    config = AskyConfig(model_alias="openai/gpt-4o-mini")
    # Reset runtime cache for each test
    import asky.plugins.runtime
    asky.plugins.runtime._RUNTIME_CACHE = None
    asky.plugins.runtime._RUNTIME_INITIALIZED = False
    runtime = get_or_create_plugin_runtime()
    return AskyClient(config, plugin_runtime=runtime)


def _run_turn_with_mention(client: AskyClient, query: str, data_dir: Path):
    mention_result = parse_persona_mention(query)
    if mention_result.has_mention:
        persona_name = mention_result.persona_identifier
        from asky.storage import create_session
        session_id = create_session(name="eval-session", model="openai/gpt-4o-mini")
        
        persona_manager_data_dir = data_dir / "plugins" / "persona_manager"
        set_session_binding(persona_manager_data_dir, session_id=session_id, persona_name=persona_name)
        
        return client.run_turn(AskyTurnRequest(
            query_text=mention_result.cleaned_query,
            resume_session_term="eval-session"
        ))
    return client.run_turn(AskyTurnRequest(query_text=query))


def test_eval_gate_direct_evidence_passed(eval_persona_data, monkeypatch):
    """Scenario: Model returns correctly formatted grounded response."""
    model_response = (
        "Answer: The secret code is 1234.\n"
        "Grounding: direct_evidence\n"
        "Evidence: [P1]"
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    client = _create_client()
    result = _run_turn_with_mention(client, "@eval_p What is the secret code?", eval_persona_data)
    
    assertion = evaluate_persona_answer(
        result.final_answer, 
        expected_grounding="direct_evidence", 
        expected_citations=["P1"]
    )
    assert assertion.passed, assertion.detail


def test_eval_gate_supported_pattern_passed(eval_persona_data, monkeypatch):
    """Scenario: Model synthesizes two sources with correct citations."""
    model_response = (
        "Answer: The code 1234 was changed in 2025.\n"
        "Grounding: supported_pattern\n"
        "Evidence: [P1], [P2]"
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    client = _create_client()
    result = _run_turn_with_mention(client, "@eval_p What happened to the code?", eval_persona_data)
    
    assertion = evaluate_persona_answer(
        result.final_answer, 
        expected_grounding="supported_pattern", 
        expected_citations=["P1", "P2"]
    )
    assert assertion.passed, assertion.detail


def test_eval_gate_invalid_draft_collapses_to_insufficient(eval_persona_data, monkeypatch):
    """Scenario: Model omits citations for a direct claim, triggering fallback."""
    model_response = (
        "Answer: The code is 1234.\n"
        "Grounding: direct_evidence\n"
        "Evidence: none" 
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    client = _create_client()
    result = _run_turn_with_mention(client, "@eval_p What is the code?", eval_persona_data)
    
    assert "I don't have enough grounded persona evidence to answer this reliably." in result.final_answer
    assert "Grounding: insufficient_evidence" in result.final_answer
    assert "[P1] Book 1" in result.final_answer


def test_eval_gate_insufficient_evidence_unseen_topic(eval_persona_data, monkeypatch):
    """Scenario: Query about something not in knowledge returns insufficient_evidence."""
    # This model response is INVALID because Evidence: is empty while packets exist.
    # It will trigger the fallback which HAS P1 and P2.
    model_response = (
        "Answer: I have no information about the moon.\n"
        "Grounding: insufficient_evidence\n"
        "Evidence:"
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    client = _create_client()
    result = _run_turn_with_mention(client, "@eval_p What is the moon made of?", eval_persona_data)
    
    assertion = evaluate_persona_answer(
        result.final_answer, 
        expected_grounding="insufficient_evidence", 
        expected_citations=["P1", "P2"] # Fallback includes all retrieved packets
    )
    assert assertion.passed, assertion.detail


def test_eval_gate_bounded_inference_passed(eval_persona_data, monkeypatch):
    """Scenario: Model synthesizes persona info with current context citations."""
    model_response = (
        "Answer: The secret code was 1234 but a recent strike changed things.\n"
        "Grounding: bounded_inference\n"
        "Evidence: [P1]\n"
        "Current Context: - [W1] recent strike"
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    # Mock live sources in thread-local
    def mock_run_turn(*args, **kwargs):
        from asky.plugins.runtime import get_or_create_plugin_runtime
        runtime = get_or_create_plugin_runtime()
        plugin = runtime.get_plugin("persona_manager")
        plugin._thread_local.live_sources = [{"label": "recent strike"}]
        # Original call would happen here, but we are mocking the whole path in _run_turn_with_mention
        return client.run_turn(*args, **kwargs)

    client = _create_client()
    
    # We need to ensure live_sources is populated before validation.
    # In a real run, POST_TOOL_EXECUTE does this.
    # Here we can patch the plugin's thread local directly.
    runtime = client.plugin_runtime
    plugin = runtime.manager.get_plugin("persona_manager")
    plugin._thread_local.live_sources = [{"label": "recent strike"}]
    
    result = _run_turn_with_mention(client, "@eval_p What is the code and status?", eval_persona_data)
    
    assertion = evaluate_persona_answer(
        result.final_answer, 
        expected_grounding="bounded_inference", 
        expected_citations=["P1"],
        expected_w_citations=["W1"]
    )
    assert assertion.passed, assertion.detail


def test_eval_gate_citations_outside_evidence_fail(eval_persona_data, monkeypatch):
    """Scenario: Model places citations only in the answer prose, which triggers fallback."""
    model_response = (
        "Answer: The secret code is 1234 [P1].\n"
        "Grounding: direct_evidence\n"
        "Evidence:"
    )
    
    monkeypatch.setattr(
        "asky.core.engine.get_llm_msg", 
        lambda *args, **kwargs: {"content": model_response, "role": "assistant"}
    )
    
    client = _create_client()
    result = _run_turn_with_mention(client, "@eval_p What is the secret code?", eval_persona_data)
    
    # Check that it collapsed to fallback
    assert "I don't have enough grounded persona evidence to answer this reliably." in result.final_answer
    assert "Grounding: insufficient_evidence" in result.final_answer

"""Tests for hierarchical summarization behavior."""

from asky import summarization


def test_hierarchical_summarization_for_long_content(monkeypatch):
    """Long inputs should trigger map-reduce summarization calls."""
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS", 200)
    monkeypatch.setattr(
        summarization, "SUMMARIZATION_HIERARCHICAL_CHUNK_TARGET_CHARS", 180
    )
    monkeypatch.setattr(
        summarization, "SUMMARIZATION_HIERARCHICAL_CHUNK_OVERLAP_CHARS", 30
    )
    monkeypatch.setattr(summarization, "HIERARCHICAL_MAX_CHUNKS", 6)

    call_counter = {"count": 0}

    def fake_get_llm_msg(*_args, **_kwargs):
        call_counter["count"] += 1
        return {"content": f"summary-{call_counter['count']}"}

    long_text = "\n\n".join(
        [f"Section {idx}. " + ("detail " * 60) for idx in range(12)]
    )

    output = summarization._summarize_content(
        content=long_text,
        prompt_template="Summarize while preserving key facts.",
        max_output_chars=300,
        get_llm_msg_func=fake_get_llm_msg,
    )

    assert output.startswith("summary-")
    assert call_counter["count"] > 2


def test_single_pass_summarization_for_short_content(monkeypatch):
    """Short inputs should stay on a single summarization call."""
    monkeypatch.setattr(
        summarization, "SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS", 10_000
    )

    call_counter = {"count": 0}

    def fake_get_llm_msg(*_args, **_kwargs):
        call_counter["count"] += 1
        return {"content": "short-summary"}

    output = summarization._summarize_content(
        content="short text content",
        prompt_template="Summarize in one sentence.",
        max_output_chars=120,
        get_llm_msg_func=fake_get_llm_msg,
    )

    assert output == "short-summary"
    assert call_counter["count"] == 1


def test_hierarchical_summarization_uses_single_reduce_call(monkeypatch):
    """Hierarchical mode should run map calls plus one final reduce call."""
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS", 10)
    monkeypatch.setattr(
        summarization,
        "_semantic_chunk_text",
        lambda *_args, **_kwargs: ["c1", "c2", "c3", "c4"],
    )

    call_counter = {"count": 0}

    def fake_get_llm_msg(*_args, **_kwargs):
        call_counter["count"] += 1
        return {"content": f"summary-{call_counter['count']}"}

    output = summarization._summarize_content(
        content="long text for hierarchical mode",
        prompt_template="Summarize with key facts.",
        max_output_chars=300,
        get_llm_msg_func=fake_get_llm_msg,
    )

    assert output.startswith("summary-")
    assert call_counter["count"] == 5


def test_zero_chunk_target_uses_summarization_input_limit(monkeypatch):
    """Zero chunk target should auto-resolve to summarization input limit."""
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS", 10)
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_CHUNK_TARGET_CHARS", 0)
    monkeypatch.setattr(summarization, "SUMMARIZATION_INPUT_LIMIT", 4321)

    observed = {"target_chars": None}

    def fake_chunker(_text, target_chars, overlap_chars, max_chunks):
        _ = overlap_chars
        _ = max_chunks
        observed["target_chars"] = target_chars
        return ["chunk-1", "chunk-2"]

    monkeypatch.setattr(summarization, "_semantic_chunk_text", fake_chunker)

    call_counter = {"count": 0}

    def fake_get_llm_msg(*_args, **_kwargs):
        call_counter["count"] += 1
        return {"content": f"summary-{call_counter['count']}"}

    output = summarization._summarize_content(
        content="long enough content for map reduce",
        prompt_template="Summarize with key facts.",
        max_output_chars=300,
        get_llm_msg_func=fake_get_llm_msg,
    )

    assert observed["target_chars"] == 4321
    assert output.startswith("summary-")


def test_positive_chunk_target_is_used_as_is(monkeypatch):
    """Explicit non-zero chunk target should bypass auto resolution."""
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS", 10)
    monkeypatch.setattr(
        summarization, "SUMMARIZATION_HIERARCHICAL_CHUNK_TARGET_CHARS", 321
    )
    monkeypatch.setattr(summarization, "SUMMARIZATION_INPUT_LIMIT", 9999)

    observed = {"target_chars": None}

    def fake_chunker(_text, target_chars, overlap_chars, max_chunks):
        _ = overlap_chars
        _ = max_chunks
        observed["target_chars"] = target_chars
        return ["chunk-1", "chunk-2"]

    monkeypatch.setattr(summarization, "_semantic_chunk_text", fake_chunker)

    def fake_get_llm_msg(*_args, **_kwargs):
        return {"content": "summary"}

    summarization._summarize_content(
        content="long enough content for map reduce",
        prompt_template="Summarize with key facts.",
        max_output_chars=300,
        get_llm_msg_func=fake_get_llm_msg,
    )

    assert observed["target_chars"] == 321


def test_negative_chunk_target_falls_back_to_input_limit(monkeypatch):
    """Negative chunk target should explicitly fall back to input limit."""
    monkeypatch.setattr(summarization, "SUMMARIZATION_HIERARCHICAL_CHUNK_TARGET_CHARS", -5)
    monkeypatch.setattr(summarization, "SUMMARIZATION_INPUT_LIMIT", 2500)

    resolved = summarization._resolve_hierarchical_chunk_target_chars()

    assert resolved == 2500

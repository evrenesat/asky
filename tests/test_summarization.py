"""Tests for hierarchical summarization behavior."""

from asky import summarization


def test_hierarchical_summarization_for_long_content(monkeypatch):
    """Long inputs should trigger map-reduce summarization calls."""
    monkeypatch.setattr(summarization, "HIERARCHICAL_TRIGGER_CHARS", 200)
    monkeypatch.setattr(summarization, "HIERARCHICAL_CHUNK_TARGET_CHARS", 180)
    monkeypatch.setattr(summarization, "HIERARCHICAL_CHUNK_OVERLAP_CHARS", 30)
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
    monkeypatch.setattr(summarization, "HIERARCHICAL_TRIGGER_CHARS", 10_000)

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

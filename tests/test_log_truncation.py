import pytest
from asky.core.api_client import _middle_truncate_words, format_log_content
from unittest.mock import MagicMock


def test_middle_truncate_words():
    # Exactly 40 words (no truncation for side_words=20)
    text_40 = " ".join(["word"] * 40)
    assert _middle_truncate_words(text_40, 20) == text_40

    # 41 words (truncation)
    text_41 = " ".join([str(i) for i in range(41)])
    truncated = _middle_truncate_words(text_41, 20)
    words = truncated.split()
    assert "[TRUNCATED]" in truncated
    assert words[0] == "0"
    assert words[19] == "19"
    assert words[-20] == "21"
    assert words[-1] == "40"
    assert len(words) == 43  # 20 + 3 ([TRUNCATED]) + 20


def test_format_log_content_truncation(monkeypatch):
    monkeypatch.setattr("asky.config.TRUNCATE_MESSAGES_IN_LOGS", True)

    # Large system message
    large_system = {"role": "system", "content": " ".join(["system"] * 100)}
    formatted = format_log_content(large_system)
    assert "... [TRUNCATED] ..." in formatted
    assert len(formatted.split()) == 43

    # Large assistant message
    large_assistant = {"role": "assistant", "content": " ".join(["assistant"] * 100)}
    formatted_assistant = format_log_content(large_assistant)
    assert "... [TRUNCATED] ..." in formatted_assistant

    # Large user message (should NOT use middle truncation by default logic if not system/assistant)
    # Actually, the existing logic for non-system/assistant is content[:200] + "..."
    large_user = {"role": "user", "content": "a " * 300}
    formatted_user = format_log_content(large_user)
    assert "[TRUNCATED]" not in formatted_user
    assert formatted_user.endswith("...")
    assert len(formatted_user) == 203


def test_format_log_content_no_truncation(monkeypatch):
    monkeypatch.setattr("asky.config.TRUNCATE_MESSAGES_IN_LOGS", False)

    large_system = {"role": "system", "content": " ".join(["system"] * 100)}
    formatted = format_log_content(large_system)
    assert "[TRUNCATED]" not in formatted
    assert len(formatted.split()) == 100

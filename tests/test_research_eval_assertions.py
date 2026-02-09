from asky.evals.research_pipeline.assertions import evaluate_answer
from asky.evals.research_pipeline.dataset import DatasetExpected


def test_contains_assertion_passes():
    expected = DatasetExpected(type="contains", text="hello")
    result = evaluate_answer("hello world", expected)
    assert result.passed is True


def test_contains_assertion_fails_when_missing_substring():
    expected = DatasetExpected(type="contains", text="missing")
    result = evaluate_answer("hello world", expected)
    assert result.passed is False
    assert "expected substring not found" in result.detail


def test_regex_assertion_supports_inline_flags():
    expected = DatasetExpected(type="regex", pattern=r"(?i)hello")
    result = evaluate_answer("HeLLo world", expected)
    assert result.passed is True


def test_regex_assertion_handles_invalid_pattern():
    expected = DatasetExpected(type="regex", pattern=r"([")
    result = evaluate_answer("hello", expected)
    assert result.passed is False
    assert "failed to compile" in result.detail

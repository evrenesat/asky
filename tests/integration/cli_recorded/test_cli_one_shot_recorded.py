import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_sentences,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_one_shot_simple_query():
    """Simple direct question, invariant sentence checks."""
    result = run_cli_inprocess(["-L", "What is the capital of France? Answer in one word."])

    assert result.exit_code == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    assert_output_contains_sentences(result.stdout, ["Paris"])


def test_one_shot_exact_normalized_output():
    """Small-output case with exact normalized output comparison."""
    result = run_cli_inprocess(["-L", "Say exactly 'PONG' and nothing else."])

    assert result.exit_code == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    normalized = normalize_cli_output(result.stdout)
    assert "PONG" in normalized.upper()


def test_one_shot_model_alias_override(monkeypatch):
    """Per-test model override case proving alias override works."""
    monkeypatch.setenv("ASKY_CLI_MODEL_ALIAS", "sonnet")

    result = run_cli_inprocess(["-L", "Hello, are you Claude? Answer 'yes'."])

    assert result.exit_code == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    assert_output_contains_sentences(result.stdout, ["yes"])

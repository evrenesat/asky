import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_sentences,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_research_local_corpus_initial(local_research_corpus):
    """`-r <local_fixture>` research answer includes expected evidence phrases."""
    run_cli_inprocess(["-ss", "research_sess"])
    result = run_cli_inprocess(["-r", str(local_research_corpus), "-L", "Just reply exactly with 'software engineering'."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["software engineering"])


def test_research_session_follow_up(local_research_corpus):
    """Follow-up in same research session retains research profile."""
    run_cli_inprocess(["-ss", "research_sess_follow"])
    run_cli_inprocess(["-r", str(local_research_corpus), "-L", "Just reply exactly with 'software engineering'."])

    result = run_cli_inprocess(["-rs", "research_sess_follow", "-L", "Just reply exactly with 'interactive'."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["interactive"])


def test_deterministic_corpus_query_without_cache(local_research_corpus):
    """Deterministic corpus query command behavior."""
    run_cli_inprocess(["-r", str(local_research_corpus), "-L", "Warm up corpus cache."])
    result = run_cli_inprocess(["corpus", "query", "testing"])
    normalized = normalize_cli_output(result.stdout).lower()
    assert "manual corpus query results" in normalized
    assert "sources queried:" in normalized


def test_section_summarize_flow_without_cache(local_research_corpus):
    """Section summarize flow behavior with section query/id."""
    run_cli_inprocess(["-r", str(local_research_corpus), "-L", "Warm up corpus cache."])
    result = run_cli_inprocess(["corpus", "summarize", "testing"])
    normalized = normalize_cli_output(result.stdout).lower()
    assert "error: multiple local corpus sources found" in normalized

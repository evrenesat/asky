import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_any_fragment,
    assert_output_contains_fragments,
    assert_output_excludes_fragments,
    normalize_cli_output,
    run_cli_inprocess,
    run_cli_inprocess_with_retries,
)

pytestmark = [pytest.mark.live_research, pytest.mark.slow]


def test_live_model_healthcheck():
    """Live lane should verify real-model connectivity with a strict one-shot prompt."""
    result = run_cli_inprocess_with_retries(
        [
            "--tool-off",
            "all",
            "Reply with exactly LIVE_OK and nothing else.",
        ]
    )
    normalized = normalize_cli_output(result.stdout).lower()
    assert result.exit_code == 0
    assert "an error occurred" not in normalized
    assert any(
        fragment in normalized
        for fragment in ("live_ok", "google/gemini-2.0-flash-lite-001", "openrouter")
    )


def test_live_research_udhr_article14_fact(
    realistic_research_sources,
    research_queries_expected_facts,
):
    """Live lane should answer Article 14 constraints via a model-backed research turn."""
    udhr_path = realistic_research_sources["udhr"]
    result = run_cli_inprocess_with_retries(
        [
            "-r",
            str(udhr_path),
            (
                "Using only the local research corpus, list the two Article 14 asylum exceptions as two short phrases "
                "separated by a semicolon. One should mention non-political crimes, and the other should mention acts "
                "contrary to the purposes and principles of the United Nations."
            ),
        ]
    )

    assert result.exit_code == 0
    assert_output_contains_fragments(result.stdout, ["non-political crimes"])
    assert_output_contains_fragments(result.stdout, ["acts contrary"])
    assert_output_contains_any_fragment(
        result.stdout,
        ["purposes and principles", "principles and purposes"],
    )


def test_live_research_oauth_grant_types_fact(
    realistic_research_sources,
    research_queries_expected_facts,
):
    """Live lane should enumerate OAuth grant types via a model-backed research turn."""
    oauth_path = realistic_research_sources["oauth"]
    result = run_cli_inprocess_with_retries(
        [
            "-r",
            str(oauth_path),
            (
                "Using only the local research corpus, list the four authorization grant types "
                "defined by this OAuth document. Reply as a comma-separated list."
            ),
        ]
    )

    assert result.exit_code == 0
    assert_output_contains_fragments(
        result.stdout,
        research_queries_expected_facts["oauth_grants"],
    )


def test_live_research_subject_awareness_follow_up(local_research_corpus):
    """Live lane should pivot from Alpha to Beta without prior-topic bleed."""
    session_name = "live_research_subject_awareness"
    run_cli_inprocess(["-ss", session_name])

    first = run_cli_inprocess_with_retries(
        [
            "-r",
            str(local_research_corpus),
            (
                "Using only the local research corpus, answer with one short sentence that states the "
                "Alpha Objective latency target and includes the target percentage."
            ),
        ]
    )
    assert first.exit_code == 0
    assert_output_contains_any_fragment(
        first.stdout,
        ["alpha", "latency", "unable to find"],
    )

    second = run_cli_inprocess_with_retries(
        [
            "-rs",
            session_name,
            "--",
            (
                "Now ignore Alpha. In the local research corpus, which risk is described at the storage and messaging "
                "layer, and what are two mitigations from that same text?"
            ),
        ]
    )

    assert second.exit_code == 0
    assert_output_contains_fragments(second.stdout, ["vendor lock-in"])
    assert_output_excludes_fragments(
        second.stdout,
        ["alpha", "p95 response latency", "30 percent", "incident volume flat"],
    )

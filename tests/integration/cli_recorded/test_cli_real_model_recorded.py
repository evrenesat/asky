import os
from pathlib import Path

import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_any_fragment,
    assert_output_contains_fragments,
    assert_output_contains_sentences,
    assert_output_excludes_fragments,
    run_cli_inprocess,
    run_cli_inprocess_with_retries,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.real_recorded_cli, pytest.mark.vcr]
if os.environ.get("ASKY_CLI_REAL_PROVIDER") != "1":
    pytestmark.append(
        pytest.mark.skip(
            reason="Set ASKY_CLI_REAL_PROVIDER=1 for real_recorded_cli replay/record runs."
        )
    )
REAL_PROVIDER_URL = "https://openrouter.ai/api/v1/chat/completions"
REAL_PROVIDER_DEFAULT_MODEL_ID = "google/gemini-2.0-flash-lite-001"


def _force_real_provider_config() -> None:
    asky_home = Path(os.environ["ASKY_HOME"])
    model_id = os.environ.get("ASKY_CLI_REAL_MODEL_ID", REAL_PROVIDER_DEFAULT_MODEL_ID)
    (asky_home / "models.toml").write_text(
        '[models.gf]\n'
        f'id = "{model_id}"\n'
        'api = "openrouter"\n'
        "context_size = 32000\n",
        encoding="utf-8",
    )
    (asky_home / "api.toml").write_text(
        "[api.openrouter]\n"
        f'url = "{REAL_PROVIDER_URL}"\n'
        'api_key_env = "OPENROUTER_API_KEY"\n',
        encoding="utf-8",
    )


def test_real_one_shot_instruction_following():
    """Real-provider replay: strict short instruction following should be preserved."""
    _force_real_provider_config()
    result = run_cli_inprocess_with_retries(
        [
            "--tool-off",
            "all",
            "Reply with exactly the token PONG_REAL and nothing else.",
        ]
    )

    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["PONG_REAL"])


def test_real_session_follow_up_continuity():
    """Real-provider replay: session follow-up should recall prior turn fact."""
    _force_real_provider_config()
    session_name = "real_recorded_followup"
    run_cli_inprocess(["-ss", session_name])

    initial = run_cli_inprocess_with_retries(
        [
            "--tool-off",
            "all",
            "My project codename is COBALT-73. Reply with READY.",
        ]
    )
    assert initial.exit_code == 0

    result = run_cli_inprocess_with_retries(
        [
            "--tool-off",
            "all",
            "-rs",
            session_name,
            "--",
            "What is my project codename? Reply with token only.",
        ]
    )
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["COBALT-73"])


def test_real_research_udhr_article14_fact(
    realistic_research_sources,
    research_queries_expected_facts,
):
    """Recorded real lane should answer a local-corpus research question via the model."""
    _force_real_provider_config()
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


def test_real_research_oauth_grant_types_fact(
    realistic_research_sources,
    research_queries_expected_facts,
):
    """Recorded real lane should enumerate OAuth grant types from the local corpus."""
    _force_real_provider_config()
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


def test_real_research_subject_awareness_follow_up(local_research_corpus):
    """Recorded real lane should pivot from Alpha to Beta without topic bleed."""
    _force_real_provider_config()
    session_name = "real_research_subject_awareness"
    run_cli_inprocess(["-ss", session_name])

    first = run_cli_inprocess_with_retries(
        [
            "-r",
            str(local_research_corpus),
            (
                "Using only the local research corpus, answer with one short sentence that includes "
                "the exact phrase 'p95 response latency' and the target percentage from the Alpha Objective section."
            ),
        ]
    )
    assert first.exit_code == 0
    assert_output_contains_fragments(first.stdout, ["p95 response latency"])
    assert_output_contains_any_fragment(
        first.stdout,
        ["at least 30", "30 percent", "30%"],
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
    assert_output_contains_fragments(second.stdout, ["vendor lock-in", "internal adapter"])
    assert_output_contains_any_fragment(second.stdout, ["two providers", "dual-provider"])
    assert_output_excludes_fragments(
        second.stdout,
        ["alpha", "p95 response latency", "30 percent", "incident volume flat"],
    )

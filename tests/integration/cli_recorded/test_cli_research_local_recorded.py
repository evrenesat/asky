import pytest

from tests.integration.cli_recorded.helpers import (
    get_session_profile_by_name,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_research_session_profile_persisted_with_local_corpus(local_research_corpus):
    """Research run should persist session-level research profile and corpus pointers."""
    session_name = "research_profile_persist"
    run_cli_inprocess(["-ss", session_name])

    result = run_cli_inprocess(
        [
            "-r",
            str(local_research_corpus),
            "Summarize the Alpha Objective section in one sentence.",
        ]
    )
    assert result.exit_code == 0

    profile = get_session_profile_by_name(session_name)
    assert profile is not None
    assert profile["research_mode"] is True
    assert profile["research_source_mode"] == "local_only"
    assert str(local_research_corpus) in profile["research_local_corpus_paths"]


def test_research_follow_up_keeps_session_profile(local_research_corpus):
    """Follow-up without -r should still keep persisted local-only research profile."""
    session_name = "research_profile_follow_up"
    run_cli_inprocess(["-ss", session_name])
    warmup = run_cli_inprocess(
        [
            "-r",
            str(local_research_corpus),
            "Answer with one word: initialized.",
        ]
    )
    assert warmup.exit_code == 0

    follow_up = run_cli_inprocess(
        [
            "-rs",
            session_name,
            "--",
            "Now answer about the Beta risk in one short sentence.",
        ]
    )
    assert follow_up.exit_code == 0

    profile = get_session_profile_by_name(session_name)
    assert profile is not None
    assert profile["research_mode"] is True
    assert profile["research_source_mode"] == "local_only"
    assert str(local_research_corpus) in profile["research_local_corpus_paths"]


def test_deterministic_corpus_query_outputs_expected_structure(local_research_corpus):
    """Manual corpus query should return deterministic command output shape."""
    warmup = run_cli_inprocess(
        [
            "-r",
            str(local_research_corpus),
            "Warm up corpus cache.",
        ]
    )
    assert warmup.exit_code == 0

    result = run_cli_inprocess(["corpus", "query", "vendor lock-in"])
    normalized = normalize_cli_output(result.stdout).lower()
    assert result.exit_code == 0
    assert "manual corpus query results" in normalized
    assert "sources queried:" in normalized
    assert "corpus://cache/" in normalized


def test_section_summarize_reports_metadata_with_explicit_source(local_research_corpus):
    """Explicit section source/query should return deterministic summary metadata lines."""
    alpha_path = local_research_corpus / "alpha_overview.md"
    warmup = run_cli_inprocess(
        [
            "-r",
            str(alpha_path),
            "Warm up corpus cache.",
        ]
    )
    assert warmup.exit_code == 0

    result = run_cli_inprocess(
        [
            "--summarize-section",
            "--section-source",
            "alpha_overview.md",
        ]
    )
    normalized = normalize_cli_output(result.stdout).lower()
    assert result.exit_code == 0
    assert "section source:" in normalized
    assert "sections returned:" in normalized
    assert "all detected headings:" in normalized


def test_section_summarize_errors_for_unknown_source_selector(local_research_corpus):
    """Summarize command should fail clearly for an unknown section source selector."""
    alpha_path = local_research_corpus / "alpha_overview.md"
    warmup = run_cli_inprocess(
        [
            "-r",
            str(alpha_path),
            "Warm up corpus cache.",
        ]
    )
    assert warmup.exit_code == 0

    result = run_cli_inprocess(
        [
            "--summarize-section",
            "--section-source",
            "does-not-exist",
        ]
    )
    normalized = normalize_cli_output(result.stdout).lower()
    assert "error: no local source matched --section-source 'does-not-exist'" in normalized


def test_corpus_query_exhaustive(local_research_corpus):
    """Test --query-corpus with all limit flags."""
    run_cli_inprocess(["-r", str(local_research_corpus), "Warm up."])
    
    # --query-corpus
    result = run_cli_inprocess([
        "--query-corpus", "alpha",
        "--query-corpus-max-sources", "1",
        "--query-corpus-max-chunks", "1"
    ])
    assert result.exit_code == 0
    assert "sources queried: 1" in normalize_cli_output(result.stdout).lower()

    # grouped `corpus query`
    result2 = run_cli_inprocess(["corpus", "query", "beta"])
    assert result2.exit_code == 0
    assert "manual corpus query" in normalize_cli_output(result2.stdout).lower()


def test_corpus_summarize_exhaustive(local_research_corpus):
    """Test --summarize-section with all flags."""
    alpha_path = local_research_corpus / "alpha_overview.md"
    run_cli_inprocess(["-r", str(alpha_path), "Warm up."])

    # --summarize-section with detail and max-chunks
    result = run_cli_inprocess([
        "--summarize-section",
        "--section-source", "alpha_overview.md",
        "--section-detail", "compact",
        "--section-max-chunks", "2"
    ])
    assert result.exit_code == 0
    assert "section source:" in normalize_cli_output(result.stdout).lower()

    # --section-id and --section-include-toc
    # First get ID
    result_list = run_cli_inprocess(["--summarize-section", "--section-source", "alpha_overview.md", "--section-include-toc"])
    # ID is usually 0 or similar for the first section
    result_id = run_cli_inprocess([
        "--summarize-section",
        "--section-source", "alpha_overview.md",
        "--section-id", "0"
    ])
    assert result_id.exit_code == 0

    # grouped `corpus summarize`
    result_grouped = run_cli_inprocess(["corpus", "summarize", "--section-source", "alpha_overview.md"])
    assert result_grouped.exit_code == 0


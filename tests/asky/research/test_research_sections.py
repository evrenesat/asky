"""Tests for deterministic local-corpus section parsing and matching."""

from asky.research.sections import (
    _looks_like_heading,
    build_section_index,
    get_listable_sections,
    match_section_strict,
    slice_section_content,
)


SAMPLE_CONTENT = """
CONTENTS
PREFACE 1
WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW 55
THE METRIC TRAP 86

PREFACE

This book examines efficiency trade-offs and recurring friction.

WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW

Learning still requires human adaptation and sustained effort.
Hardware gains have not removed cognitive bottlenecks.
Examples from education and work show persistent coordination costs.

THE METRIC TRAP

Measurement can distort behavior when targets become proxy goals.
""".strip()


def test_build_section_index_detects_headings_and_stable_ids():
    index = build_section_index(SAMPLE_CONTENT)

    sections = get_listable_sections(index, include_toc=False)
    assert len(sections) >= 2
    assert sections[0]["id"].endswith("-001")
    titles = [section["title"] for section in sections]
    assert "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW" in titles


def test_build_section_index_falls_back_to_full_document_when_no_heading():
    index = build_section_index("single paragraph without heading markers")

    assert len(index["sections"]) == 1
    assert index["sections"][0]["title"] == "Full Document"
    assert len(get_listable_sections(index, include_toc=False)) == 1


def test_match_section_strict_exact_match_succeeds():
    index = build_section_index(SAMPLE_CONTENT)

    match_payload = match_section_strict(
        "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW",
        index,
    )

    assert match_payload["matched"] is True
    assert "WHY LEARNING" in match_payload["section"]["title"]


def test_match_section_strict_low_confidence_returns_suggestions():
    index = build_section_index(SAMPLE_CONTENT)

    match_payload = match_section_strict("learning after moore law", index)

    assert match_payload["matched"] is False
    assert match_payload["suggestions"]


def test_slice_section_content_applies_chunk_limit_truncation():
    long_content = (
        "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW\n\n"
        + "\n\n".join(["Paragraph " + ("detail " * 500) for _ in range(5)])
        + "\n\n"
        + "THE METRIC TRAP\n\nshort section"
    )
    index = build_section_index(long_content)
    match_payload = match_section_strict(
        "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW",
        index,
    )

    section_id = match_payload["section"]["id"]
    sliced = slice_section_content(long_content, index, section_id, max_chunks=1)

    assert sliced["content"]
    assert sliced["truncated"] is True
    assert sliced["available_chunks"] > 1


def test_build_section_index_collapses_duplicate_toc_and_body_headings():
    content = (
        "CONTENTS\n"
        "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW 55\n\n"
        "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW\n\n"
        + ("Real section body. " * 1200)
    )
    index = build_section_index(content)

    all_sections = get_listable_sections(index, include_toc=True)
    body_sections = get_listable_sections(index, include_toc=False)
    assert len(all_sections) >= len(body_sections)
    assert len(body_sections) == 1
    assert body_sections[0]["char_count"] > 1000


def test_slice_section_content_auto_promotes_alias_to_canonical():
    section_index = {
        "sections": [
            {
                "id": "why-learning-014",
                "title": "WHY LEARNING",
                "start_offset": 0,
                "end_offset": 62,
                "char_count": 62,
            },
            {
                "id": "why-learning-038",
                "title": "WHY LEARNING",
                "start_offset": 62,
                "end_offset": 1200,
                "char_count": 1138,
            },
        ],
        "canonical_sections": [
            {
                "id": "why-learning-038",
                "title": "WHY LEARNING",
                "start_offset": 62,
                "end_offset": 1200,
                "char_count": 1138,
            }
        ],
        "alias_map": {
            "why-learning-014": "why-learning-038",
            "why-learning-038": "why-learning-038",
        },
    }
    content = ("x" * 62) + ("Body " * 250)

    sliced = slice_section_content(content, section_index, "why-learning-014")

    assert sliced["auto_promoted"] is True
    assert sliced["resolved_section_id"] == "why-learning-038"
    assert len(sliced["content"]) > 200


_BLANK_KW = {"prev_blank": True, "next_blank": True, "toc_normalized_titles": set()}


def test_looks_like_heading_rejects_semicolon_lines():
    assert _looks_like_heading("(SC): SEDAR; 2016.", **_BLANK_KW) == 0.0
    assert _looks_like_heading("Author et al.; 2020", **_BLANK_KW) == 0.0


def test_looks_like_heading_rejects_stat_notation():
    assert _looks_like_heading("AR(1)", **_BLANK_KW) == 0.0
    assert _looks_like_heading("AR(2)", **_BLANK_KW) == 0.0
    assert _looks_like_heading("ARMA(1,1)", **_BLANK_KW) == 0.0
    assert _looks_like_heading("F(2,30)", **_BLANK_KW) == 0.0


def test_looks_like_heading_rejects_non_ascii_single_token_not_in_toc():
    assert _looks_like_heading("ΔAICc", **_BLANK_KW) == 0.0
    assert _looks_like_heading("R²", **_BLANK_KW) == 0.0


def test_looks_like_heading_allows_non_ascii_token_in_toc():
    kw = {"prev_blank": True, "next_blank": True, "toc_normalized_titles": {"δaicc"}}
    score = _looks_like_heading("ΔAICc", **kw)
    assert score > 0.0


def test_looks_like_heading_allows_multi_word_non_ascii():
    kw = {"prev_blank": True, "next_blank": True, "toc_normalized_titles": set()}
    score = _looks_like_heading("CO₂ Emissions", **kw)
    assert score > 0.0


def test_build_section_index_rejects_statistical_notation_from_biology_paper():
    content = (
        "INTRODUCTION\n\n"
        "This paper investigates population dynamics using autoregressive models.\n\n"
        "METHODS\n\n"
        "We applied AR(1) and AR(2) models to the data. The ΔAICc metric was used "
        "for model selection. See (SC): SEDAR; 2016.\n\n"
        "RESULTS\n\n"
        "Table 1. Model comparison.\n\n"
        "ΔAICc\n\n"
        "AR(1)\n\n"
        "AR(2)\n\n"
        "(SC): SEDAR; 2016.\n\n"
        "DISCUSSION\n\n"
        "Our findings indicate significant population trends.\n"
    )
    index = build_section_index(content)
    sections = get_listable_sections(index, include_toc=False)
    titles = {s["title"] for s in sections}

    assert "AR(1)" not in titles
    assert "AR(2)" not in titles
    assert "ΔAICc" not in titles
    assert "(SC): SEDAR; 2016." not in titles

    assert "INTRODUCTION" in titles
    assert "METHODS" in titles
    assert "RESULTS" in titles
    assert "DISCUSSION" in titles

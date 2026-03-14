"""Tests for persona current context attribution."""

from __future__ import annotations

import pytest

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaSourceClass,
    PersonaTrustClass,
)
from asky.plugins.persona_manager.runtime_grounding import (
    PersonaEvidencePacket,
    validate_grounded_response,
)


@pytest.fixture
def sample_packets() -> list[PersonaEvidencePacket]:
    return [
        PersonaEvidencePacket(
            packet_id="P1",
            source_label="Book A",
            source_class=PersonaSourceClass.AUTHORED_BOOK,
            trust_class=PersonaTrustClass.AUTHORED_PRIMARY,
            text="Evidence from Book A.",
            entry_id="e1",
            source_id="s1",
            entry_kind="viewpoint"
        ),
    ]


@pytest.fixture
def live_sources():
    return [
        {"tool": "web_search", "label": "recent strike", "arguments": {"query": "recent strike"}},
    ]


def test_validate_valid_bounded_inference(sample_packets, live_sources):
    response = (
        "Answer: Based on Book A and the recent strike...\n"
        "Grounding: bounded_inference\n"
        "Evidence: [P1]\n"
        "Current Context: - [W1] recent strike"
    )
    assert validate_grounded_response(response, sample_packets, live_sources) is None


def test_validate_missing_current_context_fails(sample_packets, live_sources):
    response = (
        "Answer: Based on Book A and the recent strike...\n"
        "Grounding: bounded_inference\n"
        "Evidence: [P1]"
    )
    fallback = validate_grounded_response(response, sample_packets, live_sources)
    assert fallback is not None
    assert "Current Context:" in fallback
    assert "- [W1] recent strike" in fallback


def test_validate_web_only_no_persona_packets_fails(sample_packets, live_sources):
    # If live_sources used but NO persona packets cited, must collapse
    response = (
        "Answer: The strike is happening.\n"
        "Grounding: bounded_inference\n"
        "Evidence: none\n"
        "Current Context: - [W1] recent strike"
    )
    fallback = validate_grounded_response(response, sample_packets, live_sources)
    assert fallback is not None
    assert "insufficient_evidence" in fallback


def test_validate_invalid_w_id(sample_packets, live_sources):
    response = (
        "Answer: Strike stuff.\n"
        "Grounding: bounded_inference\n"
        "Evidence: [P1]\n"
        "Current Context: - [W2] unknown"
    )
    fallback = validate_grounded_response(response, sample_packets, live_sources)
    assert fallback is not None


def test_validate_no_live_sources_used_passes(sample_packets):
    response = (
        "Answer: Just persona stuff.\n"
        "Grounding: direct_evidence\n"
        "Evidence: [P1]"
    )
    assert validate_grounded_response(response, sample_packets, None) is None


def test_validate_direct_evidence_plus_live_sources_fails(sample_packets, live_sources):
    response = (
        "Answer: Based on Book A and the recent strike...\n"
        "Grounding: direct_evidence\n" # INVALID when live_sources present
        "Evidence: [P1]\n"
        "Current Context: - [W1] recent strike"
    )
    fallback = validate_grounded_response(response, sample_packets, live_sources)
    assert fallback is not None


def test_validate_supported_pattern_plus_live_sources_fails(sample_packets, live_sources):
    p2 = PersonaEvidencePacket(
            packet_id="P2",
            source_label="Book B",
            source_class=PersonaSourceClass.AUTHORED_BOOK,
            trust_class=PersonaTrustClass.AUTHORED_PRIMARY,
            text="Evidence from Book B.",
            entry_id="e2",
            source_id="s2",
            entry_kind="viewpoint"
        )
    packets = sample_packets + [p2]
    response = (
        "Answer: Based on both books and the recent strike...\n"
        "Grounding: supported_pattern\n" # INVALID when live_sources present
        "Evidence: [P1], [P2]\n"
        "Current Context: - [W1] recent strike"
    )
    fallback = validate_grounded_response(response, packets, live_sources)
    assert fallback is not None

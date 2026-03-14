"""Tests for persona grounding and validation."""

from __future__ import annotations

import pytest

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaGroundingClass,
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
        ),
        PersonaEvidencePacket(
            packet_id="P2",
            source_label="Manual B",
            source_class=PersonaSourceClass.MANUAL_SOURCE,
            trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
            text="Evidence from Manual B.",
            entry_id="e2",
            source_id="s2",
        ),
    ]


def test_validate_valid_direct_evidence(sample_packets):
    response = (
        "Answer: Based on Book A, this is true.\n"
        "Grounding: direct_evidence\n"
        "Evidence: [P1]"
    )
    assert validate_grounded_response(response, sample_packets) is None


def test_validate_valid_supported_pattern(sample_packets):
    response = (
        "Answer: Both sources agree.\n"
        "Grounding: supported_pattern\n"
        "Evidence: [P1], [P2]"
    )
    assert validate_grounded_response(response, sample_packets) is None


def test_validate_invalid_no_grounding_line(sample_packets):
    response = "Answer: Just an answer without grounding line."
    fallback = validate_grounded_response(response, sample_packets)
    assert fallback is not None
    assert "insufficient_evidence" in fallback
    assert "- [P1] Book A" in fallback


def test_validate_invalid_no_citations(sample_packets):
    response = (
        "Answer: This is true.\n"
        "Grounding: direct_evidence\n"
        "Evidence: (missing [P#])"
    )
    fallback = validate_grounded_response(response, sample_packets)
    assert fallback is not None
    assert "insufficient_evidence" in fallback


def test_validate_invalid_packet_id(sample_packets):
    response = (
        "Answer: True.\n"
        "Grounding: direct_evidence\n"
        "Evidence: [P3]"  # P3 does not exist
    )
    fallback = validate_grounded_response(response, sample_packets)
    assert fallback is not None


def test_validate_insufficient_evidence_requires_packet_labels(sample_packets):
    # This should now FAIL because Evidence: is empty while packets exist
    response = (
        "Answer: I don't know.\n"
        "Grounding: insufficient_evidence\n"
        "Evidence:"
    )
    fallback = validate_grounded_response(response, sample_packets)
    assert fallback is not None


def test_validate_insufficient_evidence_with_labels_passes(sample_packets):
    # This is how insufficient_evidence should be used now
    response = (
        "Answer: I don't know.\n"
        "Grounding: insufficient_evidence\n"
        "Evidence: [P1], [P2]"
    )
    assert validate_grounded_response(response, sample_packets) is None


def test_validate_citations_outside_evidence_section_fail(sample_packets):
    response = (
        "Answer: True [P1].\n"
        "Grounding: direct_evidence\n"
        "Evidence: "
    )
    fallback = validate_grounded_response(response, sample_packets)
    assert fallback is not None


def test_validate_no_packets_available():
    response = "No packets, no problem."
    assert validate_grounded_response(response, []) is None

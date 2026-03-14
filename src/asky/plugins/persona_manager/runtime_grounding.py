"""Runtime grounding and evidence formatting for personas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaGroundingClass,
    PersonaSourceClass,
    PersonaTrustClass,
)


@dataclass(frozen=True)
class PersonaEvidencePacket:
    """A single packet of retrieved persona evidence."""

    packet_id: str  # P1, P2, P3...
    source_label: str
    source_class: PersonaSourceClass
    trust_class: PersonaTrustClass
    text: str
    entry_id: str
    source_id: str

    def format(self) -> str:
        """Format packet for LLM context."""
        return (
            f"Persona Evidence Packet: {self.packet_id}\n"
            f"Source: {self.source_label}\n"
            f"Class: {self.source_class}\n"
            f"Trust: {self.trust_class}\n"
            f"Evidence: {self.text}\n"
        )


def format_grounding_prompt_extension(persona_name: str) -> str:
    """Return the grounding contract instructions for the system prompt."""
    return (
        f"\nYou are currently acting as the persona: {persona_name}.\n"
        "Your answers must be grounded in the provided Persona Evidence Packets.\n"
        "You must follow this exact answer format:\n"
        "Answer: <your grounded answer here>\n"
        "Grounding: <direct_evidence|supported_pattern|bounded_inference|insufficient_evidence>\n"
        "Evidence: <cite [P#] packet ids here>\n"
        "\nRules:\n"
        "1. If you use direct information from a packet, cite it as [P#].\n"
        "2. If multiple packets support your answer, cite all relevant [P#].\n"
        "3. If no packets are relevant, use 'Grounding: insufficient_evidence' and explain what is missing.\n"
    )


def validate_grounded_response(
    response_text: str,
    available_packets: List[PersonaEvidencePacket],
) -> Optional[str]:
    """
    Validate LLM response against grounding contract.
    Returns a fallback response if validation fails and packets were available.
    Returns None if validation passes or no packets were available to cite.
    """
    if not available_packets:
        return None

    text = response_text.strip()
    
    # Check for Grounding: line
    grounding_match = re.search(r"^Grounding:\s*(\w+)", text, re.MULTILINE)
    if not grounding_match:
        return _build_fallback(available_packets)
    
    grounding_val = grounding_match.group(1).lower()
    valid_grounding = {g.value for g in PersonaGroundingClass}
    if grounding_val not in valid_grounding:
        return _build_fallback(available_packets)

    # Check for Evidence: section
    evidence_match = re.search(r"^Evidence:\s*(.*)", text, re.MULTILINE | re.DOTALL)
    if not evidence_match:
        return _build_fallback(available_packets)
    
    evidence_section = evidence_match.group(1).strip()
    
    # Extract citations strictly from the Evidence section
    citations = set(re.findall(r"\[P(\d+)\]", evidence_section))
    if not citations:
        return _build_fallback(available_packets)
    
    # Validate that cited packet IDs actually exist
    valid_ids = {p.packet_id for p in available_packets}
    for c in citations:
        if f"P{c}" not in valid_ids:
            return _build_fallback(available_packets)

    return None


def _build_fallback(packets: List[PersonaEvidencePacket]) -> str:
    """Build the exact fallback response mandated by the plan."""
    lines = [
        "I don't have enough grounded persona evidence to answer this reliably.",
        "",
        "Grounding: insufficient_evidence",
        "Evidence:",
    ]
    for p in packets:
        lines.append(f"- [{p.packet_id}] {p.source_label}")
    return "\n".join(lines)

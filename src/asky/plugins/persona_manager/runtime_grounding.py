"""Runtime grounding and evidence formatting for personas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaGroundingClass,
)
from asky.plugins.persona_manager.runtime_types import PersonaEvidencePacket


def format_grounding_prompt_extension(persona_name: str) -> str:
    """Return the grounding contract instructions for the system prompt."""
    return (
        f"\nYou are currently acting as the persona: {persona_name}.\n"
        "Your answers must be grounded in the provided Persona Evidence Packets.\n"
        "You must follow this exact answer format:\n"
        "Answer: <your grounded answer here>\n"
        "Grounding: <direct_evidence|supported_pattern|bounded_inference|insufficient_evidence>\n"
        "Evidence: <cite [P#] packet ids here>\n"
        "Current Context: <list - [W#] source_label lines here ONLY if live context was used>\n"
        "\nRules:\n"
        "1. If you use direct information from a packet, cite it as [P#].\n"
        "2. If multiple packets support your answer, cite all relevant [P#].\n"
        "3. If you use fresh current-event context from tools, cite it as [W#] in a separate 'Current Context:' section.\n"
        "4. 'Grounding: bounded_inference' MUST be used if both persona packets and fresh current-event context support the answer.\n"
        "5. If no persona packets support the answer, use 'Grounding: insufficient_evidence' even if fresh current-event context is available.\n"
    )


def validate_grounded_response(
    response_text: str,
    available_packets: List[PersonaEvidencePacket],
    live_sources: List[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Validate LLM response against grounding contract.
    Returns a fallback response if validation fails for a persona-loaded turn.
    Returns None if validation passes.
    """
    # 1. Zero-packet persona turns must always fallback to insufficient_evidence
    if not available_packets:
        return _build_fallback([], live_sources)

    text = response_text.strip()
    
    # 2. Extract Grounding: class
    grounding_match = re.search(r"^Grounding:\s*(\w+)", text, re.MULTILINE)
    if not grounding_match:
        return _build_fallback(available_packets, live_sources)
    
    grounding_val = grounding_match.group(1).lower()
    valid_grounding = {g.value for g in PersonaGroundingClass}
    if grounding_val not in valid_grounding:
        return _build_fallback(available_packets, live_sources)

    # 3. Grounding vs Live Sources Compatibility
    # bounded_inference MUST be used iff both persona packets and live sources are present.
    # direct_evidence and supported_pattern are ONLY valid if NO live sources were used.
    if live_sources:
        if grounding_val != PersonaGroundingClass.BOUNDED_INFERENCE.value:
            return _build_fallback(available_packets, live_sources)
    else:
        if grounding_val == PersonaGroundingClass.BOUNDED_INFERENCE.value:
            return _build_fallback(available_packets, live_sources)

    # 4. Extract Evidence: section and citations
    evidence_match = re.search(r"^Evidence:\s*(.*)", text, re.MULTILINE | re.DOTALL)
    if not evidence_match:
        return _build_fallback(available_packets, live_sources)
    
    evidence_content = evidence_match.group(1).strip()
    # Truncate if another section follows
    next_section = re.search(r"\n\w+:", evidence_content)
    if next_section:
        evidence_content = evidence_content[:next_section.start()].strip()
    
    citations = set(re.findall(r"\[P(\d+)\]", evidence_content))
    if not citations:
        # If available_packets is NOT empty, we expect the LLM to have found support.
        # If it returns no citations, it's a validation failure even if it claimed insufficient_evidence.
        return _build_fallback(available_packets, live_sources)
    
    # Validate specific grounding class rules
    if grounding_val == PersonaGroundingClass.SUPPORTED_PATTERN.value and len(citations) < 2:
        return _build_fallback(available_packets, live_sources)
    
    # Validate that cited packet IDs actually exist
    valid_ids = {p.packet_id for p in available_packets}
    for c in citations:
        if f"P{c}" not in valid_ids:
            return _build_fallback(available_packets, live_sources)

    # 5. Live sources attribution (Current Context:)
    if live_sources:
        current_context_match = re.search(r"^Current Context:\s*(.*)", text, re.MULTILINE | re.DOTALL)
        if not current_context_match:
            return _build_fallback(available_packets, live_sources)
        
        context_section = current_context_match.group(1).strip()
        found_w_ids = set(re.findall(r"\[W(\d+)\]", context_section))
        
        if not found_w_ids:
            return _build_fallback(available_packets, live_sources)
            
        valid_w_ids = {str(i + 1) for i in range(len(live_sources))}
        for w_id in found_w_ids:
            if w_id not in valid_w_ids:
                return _build_fallback(available_packets, live_sources)

    return None


def _build_fallback(
    packets: List[PersonaEvidencePacket],
    live_sources: List[Dict[str, Any]] = None,
) -> str:
    """Build the exact fallback response mandated by the plan."""
    lines = [
        "I don't have enough grounded persona evidence to answer this reliably.",
        "",
        "Grounding: insufficient_evidence",
        "Evidence:",
    ]
    if not packets:
        lines[-1] = "Evidence: none"
    else:
        for p in packets:
            lines.append(f"- [{p.packet_id}] {p.source_label}")
    
    if live_sources:
        lines.append("Current Context:")
        for i, src in enumerate(live_sources):
            lines.append(f"- [W{i+1}] {src.get('label', 'web_source')}")
            
    return "\n".join(lines)

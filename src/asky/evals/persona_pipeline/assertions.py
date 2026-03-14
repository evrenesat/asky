"""Assertion helpers for persona pipeline evaluations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PersonaAssertionResult:
    passed: bool
    detail: str


def evaluate_persona_answer(
    answer: str,
    expected_grounding: str,
    expected_citations: List[str],
    expected_contains: Optional[List[str]] = None,
    expected_w_citations: Optional[List[str]] = None,
) -> PersonaAssertionResult:
    """Score a persona answer against grounding/citation expectations."""
    if not answer:
        return PersonaAssertionResult(False, "Answer is empty.")

    # 1. Grounding check
    grounding_match = re.search(r"^Grounding:\s*(\w+)", answer, re.MULTILINE)
    if not grounding_match:
        return PersonaAssertionResult(False, "Missing 'Grounding:' line.")
    
    actual_grounding = grounding_match.group(1).lower()
    if actual_grounding != expected_grounding.lower():
        return PersonaAssertionResult(
            False, 
            f"Grounding mismatch: expected '{expected_grounding}', got '{actual_grounding}'."
        )

    # 2. Evidence section check
    evidence_match = re.search(r"^Evidence:\s*(.*)", answer, re.MULTILINE | re.DOTALL)
    if not evidence_match:
        return PersonaAssertionResult(False, "Missing 'Evidence:' section.")
    
    evidence_text = evidence_match.group(1).strip()
    # Truncate if another section follows (e.g. Current Context:)
    next_section = re.search(r"\n\w+:", evidence_text)
    if next_section:
        evidence_text = evidence_text[:next_section.start()].strip()

    # 3. Citations check within Evidence section
    citations = {f"P{c}" for c in re.findall(r"\[P(\d+)\]", evidence_text)}
    expected_citations_set = set(expected_citations)
    
    # Special case: insufficient_evidence might have empty expected_citations in some tests,
    # but the fallback currently includes ALL packets.
    # Actually, let's just compare sets.
    
    missing = expected_citations_set - citations
    extra = citations - expected_citations_set
    
    if missing:
        return PersonaAssertionResult(False, f"Missing required citations in Evidence: section: {sorted(missing)}.")
    if extra:
        return PersonaAssertionResult(False, f"Extra citations found in Evidence: section: {sorted(extra)}.")
    
    # 4. Current Context check
    if expected_w_citations is not None:
        current_context_match = re.search(r"^Current Context:\s*(.*)", answer, re.MULTILINE | re.DOTALL)
        if not current_context_match and expected_w_citations:
            return PersonaAssertionResult(False, "Missing 'Current Context:' section despite expected [W#] citations.")
        
        actual_w_citations = set()
        if current_context_match:
            context_section = current_context_match.group(1).strip()
            actual_w_citations = {f"W{w}" for w in re.findall(r"\[W(\d+)\]", context_section)}
            
        expected_w_set = set(expected_w_citations)
        missing_w = expected_w_set - actual_w_citations
        extra_w = actual_w_citations - expected_w_set
        
        if missing_w:
            return PersonaAssertionResult(False, f"Missing required Current Context citations: {sorted(missing_w)}.")
        if extra_w:
            return PersonaAssertionResult(False, f"Extra Current Context citations found: {sorted(extra_w)}.")
    else:
        # If not expected, ensure section doesn't exist
        if "^Current Context:" in answer:
             return PersonaAssertionResult(False, "Found 'Current Context:' section but none was expected.")

    # 5. Content check
    if expected_contains:
        for text in expected_contains:
            if text.lower() not in answer.lower():
                return PersonaAssertionResult(False, f"Answer missing expected text: '{text}'.")

    return PersonaAssertionResult(True, "All persona assertions passed.")

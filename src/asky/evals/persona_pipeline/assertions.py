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
    
    evidence_section = evidence_match.group(1).strip()

    # 3. Citations check within Evidence section
    citations = {f"P{c}" for c in re.findall(r"\[P(\d+)\]", evidence_section)}
    expected_citations_set = set(expected_citations)
    
    missing = expected_citations_set - citations
    extra = citations - expected_citations_set
    
    if missing:
        return PersonaAssertionResult(False, f"Missing required citations in Evidence: section: {sorted(missing)}.")
    if extra:
        return PersonaAssertionResult(False, f"Extra citations found in Evidence: section: {sorted(extra)}.")
    
    # 4. Content check
    if expected_contains:
        for text in expected_contains:
            if text.lower() not in answer.lower():
                return PersonaAssertionResult(False, f"Answer missing expected text: '{text}'.")

    return PersonaAssertionResult(True, "All persona assertions passed.")

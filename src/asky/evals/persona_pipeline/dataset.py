"""Dataset loading and validation for persona pipeline evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PersonaDatasetCase:
    """One evaluation test case for persona behavior."""

    id: str
    persona_name: str
    query: str
    expected_grounding: str  # e.g. direct_evidence, insufficient_evidence
    expected_citations: List[str]  # e.g. ["P1", "P2"]
    expected_contains: List[str] = None


@dataclass(frozen=True)
class PersonaDatasetSpec:
    """Complete persona dataset definition."""

    id: str
    tests: List[PersonaDatasetCase]


def load_persona_dataset(path: Path) -> PersonaDatasetSpec:
    """Load persona dataset from JSON."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    tests = []
    for t in data.get("tests", []):
        tests.append(
            PersonaDatasetCase(
                id=t["id"],
                persona_name=t["persona_name"],
                query=t["query"],
                expected_grounding=t["expected_grounding"],
                expected_citations=t.get("expected_citations", []),
                expected_contains=t.get("expected_contains", []),
            )
        )
    return PersonaDatasetSpec(id=data.get("id", "persona_eval"), tests=tests)

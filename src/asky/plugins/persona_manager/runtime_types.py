"""Typed runtime models for persona retrieval and planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaSourceClass,
    PersonaTrustClass,
)


@dataclass(frozen=True)
class PersonaEvidencePacket:
    """A single packet of retrieved persona evidence with full runtime metadata."""

    packet_id: str  # P1, P2, P3...
    entry_id: str
    entry_kind: PersonaEntryKind
    source_id: str
    source_label: str
    source_class: PersonaSourceClass
    trust_class: PersonaTrustClass
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    supporting_excerpts: List[str] = field(default_factory=list)

    def format(self) -> str:
        """Format packet for LLM context."""
        lines = [
            f"Persona Evidence Packet: {self.packet_id}",
            f"Source: {self.source_label}",
            f"Class: {self.source_class}",
            f"Trust: {self.trust_class}",
        ]

        if "book_title" in self.metadata:
            lines.append(f"Book: {self.metadata['book_title']}")
        if "publication_year" in self.metadata:
            lines.append(f"Published: {self.metadata['publication_year']}")
        if "topic" in self.metadata:
            lines.append(f"Topic: {self.metadata['topic']}")
        if "stance_label" in self.metadata:
            lines.append(f"Stance: {self.metadata['stance_label']}")

        lines.append(f"Evidence: {self.text}")

        if self.supporting_excerpts:
            lines.append("Supporting Evidence:")
            for excerpt in self.supporting_excerpts:
                lines.append(f"- {excerpt}")

        return "\n".join(lines) + "\n"


@dataclass
class PersonaPlanState:
    """Turn-level persona plan state."""

    persona_name: str
    query_text: str
    packets: List[PersonaEvidencePacket] = field(default_factory=list)
    live_sources_used: List[Dict[str, Any]] = field(default_factory=list)

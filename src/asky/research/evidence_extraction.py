"""Post-retrieval evidence extraction for research pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from asky.core.api_client import get_llm_msg

logger = logging.getLogger(__name__)

# Maximum chunks to process through extraction.
MAX_EVIDENCE_CHUNKS = 10

# Maximum tokens per extraction LLM call input.
EXTRACTION_MAX_INPUT_TOKENS = 1500


@dataclass
class EvidenceFact:
    """A single extracted fact with provenance."""

    fact: str
    relevance: str  # "high", "medium", "low"
    source_url: Optional[str] = None
    source_title: Optional[str] = None
    chunk_text: Optional[str] = None  # Original chunk for reference


def extract_evidence_from_chunks(
    chunks: List[Dict[str, Any]],
    query: str,
    llm_client: Any,
    model: str,
    max_chunks: int = MAX_EVIDENCE_CHUNKS,
) -> List[EvidenceFact]:
    """Extract query-relevant facts from retrieved chunks.

    For each chunk, makes a single focused LLM call with a structured
    extraction prompt. Caps total calls to max_chunks.

    Returns structured evidence facts.
    """
    if not chunks or not query:
        return []

    evidence_facts: List[EvidenceFact] = []

    # Cap total chunks to process
    target_chunks = chunks[:max_chunks]

    for chunk in target_chunks:
        chunk_text = chunk.get("text", "")
        source_url = chunk.get("url")
        source_title = chunk.get("title")

        if not chunk_text:
            continue

        prompt = (
            "Given this text excerpt and research question, extract specific facts "
            "that are relevant to answering the question. For each fact, rate relevance as "
            "high|medium|low.\n\n"
            f"Question: {query}\n\n"
            "Text:\n"
            f"{chunk_text}\n\n"
            'Output ONLY a JSON array of objects: [{"fact": "...", "relevance": "high|medium|low"}]'
        )

        try:
            # We use a smaller max_tokens for extraction as well.
            response = get_llm_msg(
                model_id=model,
                messages=[{"role": "user", "content": prompt}],
                use_tools=False,
                model_alias=model,
            )

            content = response.get("content", "").strip()
            # Basic JSON extraction
            if "[" in content and "]" in content:
                content = content[content.find("[") : content.rfind("]") + 1]

            facts_data = json.loads(content)
            if isinstance(facts_data, list):
                for item in facts_data:
                    if isinstance(item, dict) and "fact" in item:
                        evidence_facts.append(
                            EvidenceFact(
                                fact=item["fact"],
                                relevance=item.get("relevance", "medium"),
                                source_url=source_url,
                                source_title=source_title,
                                chunk_text=chunk_text,
                            )
                        )
        except Exception as exc:
            logger.debug("Evidence extraction failed for chunk: %s", exc)

    # Sort: high > medium > low
    relevance_map = {"high": 0, "medium": 1, "low": 2}
    evidence_facts.sort(key=lambda x: relevance_map.get(x.relevance, 1))

    return evidence_facts


def format_evidence_context(evidence: List[EvidenceFact]) -> Optional[str]:
    """Format extracted facts as a structured context block."""
    if not evidence:
        return None

    lines = ["Structured Evidence Extracted from Sources:"]
    for i, ef in enumerate(evidence, 1):
        source_info = (
            f" (Source: {ef.source_title or ef.source_url})"
            if ef.source_title or ef.source_url
            else ""
        )
        lines.append(f"{i}. [{ef.relevance.upper()}] {ef.fact}{source_info}")

    return "\n".join(lines)

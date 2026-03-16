"""Persona documentation topics loader."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DOCS_DIR = Path(__file__).parent / "docs"


@dataclass(frozen=True)
class DocTopic:
    """A persona documentation topic."""

    id: str
    title: str
    summary: str
    body: str
    fields: dict[str, str] = field(default_factory=dict)


def load_topic(topic_id: str) -> DocTopic:
    """Load a specific documentation topic by ID."""
    filename = f"{topic_id.replace('-', '_')}.md"
    file_path = DOCS_DIR / filename

    if not file_path.exists():
        valid_ids = sorted([f.stem.replace("_", "-") for f in DOCS_DIR.glob("*.md")])
        raise ValueError(
            f"Unknown topic id: {topic_id}. Valid topics: {', '.join(valid_ids)}"
        )

    content = file_path.read_text(encoding="utf-8")

    # Simple front matter parser for +++ blocks
    if content.startswith("+++"):
        parts = content.split("+++", 2)
        if len(parts) >= 3:
            front_matter_str = parts[1].strip()
            body = parts[2].strip()
            try:
                metadata = tomllib.loads(front_matter_str)
            except Exception as e:
                raise ValueError(f"Failed to parse TOML front matter in {filename}: {e}")

            return DocTopic(
                id=topic_id,
                title=metadata.get("title", topic_id),
                summary=metadata.get("summary", ""),
                body=body,
                fields=metadata.get("fields", {}),
            )

    return DocTopic(id=topic_id, title=topic_id, summary="", body=content.strip())


def list_topics() -> list[DocTopic]:
    """List all available documentation topics."""
    topics = []
    for f in sorted(DOCS_DIR.glob("*.md")):
        topic_id = f.stem.replace("_", "-")
        try:
            topics.append(load_topic(topic_id))
        except ValueError:
            continue
    return topics

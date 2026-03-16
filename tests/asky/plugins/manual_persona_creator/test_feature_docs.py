"""Tests for persona documentation feature."""

from __future__ import annotations

from pathlib import Path
from asky.plugins.manual_persona_creator.feature_docs import load_topic, list_topics

def test_load_topic_with_frontmatter():
    topic = load_topic("create-persona")
    assert topic.id == "create-persona"
    assert "Creating a Persona" in topic.title
    assert len(topic.body) > 100
    assert "persona_name" in topic.fields
    assert topic.fields["persona_name"] == "Unique ID for the persona. Lowercase alphanumeric and dashes only."

def test_list_topics():
    topics = list_topics()
    assert len(topics) >= 3
    ids = {t.id for t in topics}
    assert "create-persona" in ids
    assert "authored-book" in ids
    assert "manual-source" in ids

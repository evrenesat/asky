"""Tests for structured persona retrieval and packet planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from asky.plugins.manual_persona_creator.knowledge_catalog import (
    rebuild_catalog_from_legacy,
)
from asky.plugins.manual_persona_creator.runtime_index import rebuild_runtime_index
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    BOOK_METADATA_FILENAME,
    CHUNKS_FILENAME,
    VIEWPOINTS_FILENAME,
    write_chunks,
)
from asky.plugins.persona_manager.runtime_planner import plan_persona_packets


class _FakeEmbeddingClient:
    def embed(self, texts):
        # Deterministic vectors based on text content for testing
        return [[float(len(t)), 0.0] for t in texts]

    def embed_single(self, text):
        return [float(len(text)), 0.0]


@pytest.fixture
def mock_embeddings(monkeypatch):
    import asky.plugins.persona_manager.runtime_planner
    import asky.plugins.manual_persona_creator.runtime_index

    fake_client = _FakeEmbeddingClient()
    monkeypatch.setattr(
        asky.plugins.persona_manager.runtime_planner,
        "get_embedding_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        asky.plugins.manual_persona_creator.runtime_index,
        "get_embedding_client",
        lambda: fake_client,
    )


def test_plan_persona_packets_prioritizes_viewpoints(tmp_path: Path, mock_embeddings):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    # 1. Add a manual chunk (lower priority)
    # text length 10
    chunks = [{"chunk_id": "m1", "text": "1234567890", "source": "manual.txt"}]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    # 2. Add an authored book with a viewpoint (higher priority)
    # text length 10
    book_dir = persona_root / AUTHORED_BOOKS_DIR_NAME / "book1"
    book_dir.mkdir(parents=True)
    from asky.plugins.manual_persona_creator.storage import write_book_metadata
    write_book_metadata(book_dir / BOOK_METADATA_FILENAME, {"title": "Book 1"})

    viewpoints = [
        {
            "viewpoint_id": "vp1",
            "viewpoint_text": "ABCDEFGHIJ",  # length 10
            "topic": "Topic 1",
            "evidence": [{"text": "Evidence 1", "page_ref": "1"}] # Evidence 1 is also length 10
        }
    ]
    (book_dir / VIEWPOINTS_FILENAME).write_text(json.dumps(viewpoints))

    # Rebuild everything
    rebuild_catalog_from_legacy(persona_root)
    rebuild_runtime_index(persona_root)

    # Query length 10 (perfect match for both)
    packets = plan_persona_packets(
        persona_dir=persona_root,
        query_text="1234567890",
        top_k=2,
    )

    assert len(packets) == 2
    # Viewpoint should be first (priority 0)
    # Then chunk (priority 1)
    # Evidence excerpt is attached support only and should not be a standalone packet.
    assert packets[0].entry_id == "viewpoint:vp1"
    assert packets[1].entry_id == "chunk:m1"
    
    # Viewpoint should have supporting evidence excerpt
    assert len(packets[0].supporting_excerpts) == 1
    assert packets[0].supporting_excerpts[0] == "Evidence 1"


def test_plan_persona_packets_unseen_topic_returns_zero(tmp_path: Path, mock_embeddings, monkeypatch):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()
    chunks = [{"chunk_id": "m1", "text": "known topic", "source": "m1.txt"}]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)
    rebuild_catalog_from_legacy(persona_root)
    rebuild_runtime_index(persona_root)

    # Force low similarity by mocking cosine_similarity
    import asky.plugins.persona_manager.runtime_planner
    monkeypatch.setattr(
        asky.plugins.persona_manager.runtime_planner,
        "cosine_similarity",
        lambda a, b: 0.1
    )

    packets = plan_persona_packets(
        persona_dir=persona_root,
        query_text="unseen topic",
        top_k=5,
    )
    assert len(packets) == 0


def test_plan_persona_packets_excerpt_only_similarity_ignored(tmp_path: Path, mock_embeddings, monkeypatch):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()
    
    # Add a book with a viewpoint and an excerpt
    book_dir = persona_root / AUTHORED_BOOKS_DIR_NAME / "book1"
    book_dir.mkdir(parents=True)
    from asky.plugins.manual_persona_creator.storage import write_book_metadata
    write_book_metadata(book_dir / BOOK_METADATA_FILENAME, {"title": "Book 1"})

    viewpoints = [
        {
            "viewpoint_id": "vp1",
            "viewpoint_text": "irrelevant viewpoint text", # length 25
            "topic": "Topic 1",
            "evidence": [{"text": "relevant excerpt", "page_ref": "1"}] # length 16
        }
    ]
    (book_dir / VIEWPOINTS_FILENAME).write_text(json.dumps(viewpoints))
    rebuild_catalog_from_legacy(persona_root)
    rebuild_runtime_index(persona_root)

    # Mock similarity so only items with exact length match query length
    def restricted_sim(a, b):
        if abs(a[0] - b[0]) < 0.1: return 1.0
        return 0.1

    monkeypatch.setattr(
        "asky.plugins.persona_manager.runtime_planner.cosine_similarity",
        restricted_sim
    )
    
    # Query for "relevant excerpt" (len 16)
    # Excerpt has len 16. Viewpoint has len 25.
    # Only excerpt matches with high similarity. 
    # But it should be IGNORED because it's not primary.
    packets = plan_persona_packets(
        persona_dir=persona_root,
        query_text="relevant excerpt",
        top_k=5,
    )
    assert len(packets) == 0


def test_plan_persona_packets_fallback_to_manual(tmp_path: Path, mock_embeddings):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    # Only manual chunks
    chunks = [
        {"chunk_id": "m1", "text": "manual one", "source": "m1.txt"},
        {"chunk_id": "m2", "text": "manual two", "source": "m2.txt"},
    ]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    rebuild_catalog_from_legacy(persona_root)
    rebuild_runtime_index(persona_root)

    packets = plan_persona_packets(
        persona_dir=persona_root,
        query_text="manual",
        top_k=1,
    )

    assert len(packets) == 1
    assert packets[0].source_label == "m1.txt" or packets[0].source_label == "m2.txt"


def test_plan_persona_packets_respects_top_k(tmp_path: Path, mock_embeddings):
    persona_root = tmp_path / "test_persona"
    persona_root.mkdir()

    chunks = [
        {"chunk_id": "m1", "text": "aaaa", "source": "s1.txt"},
        {"chunk_id": "m2", "text": "bbbb", "source": "s2.txt"},
        {"chunk_id": "m3", "text": "cccc", "source": "s3.txt"},
    ]
    write_chunks(persona_root / CHUNKS_FILENAME, chunks)

    rebuild_catalog_from_legacy(persona_root)
    rebuild_runtime_index(persona_root)

    packets = plan_persona_packets(
        persona_dir=persona_root,
        query_text="aaaa",
        top_k=2,
    )

    assert len(packets) == 2

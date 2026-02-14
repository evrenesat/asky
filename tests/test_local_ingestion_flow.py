"""Tests for pre-LLM local ingestion flow."""

from unittest.mock import MagicMock, patch


def test_preload_local_research_sources_skips_when_no_targets():
    from asky.cli.local_ingestion_flow import preload_local_research_sources

    with patch(
        "asky.cli.local_ingestion_flow.extract_local_source_targets",
        return_value=[],
    ):
        payload = preload_local_research_sources("no local paths here")

    assert payload["enabled"] is False
    assert payload["ingested"] == []
    assert payload["stats"]["targets"] == 0


def test_preload_local_research_sources_ingests_discovered_documents():
    from asky.cli.local_ingestion_flow import preload_local_research_sources

    cache = MagicMock()
    cache.cache_url.side_effect = [10, 11]
    vector_store = MagicMock()
    vector_store.has_chunk_embeddings.return_value = False
    vector_store.embedding_client.model = "test-embedding-model"
    vector_store.store_chunk_embeddings.side_effect = [1, 2]

    with (
        patch(
            "asky.cli.local_ingestion_flow.extract_local_source_targets",
            return_value=["/tmp/corpus"],
        ),
        patch("asky.cli.local_ingestion_flow.ResearchCache", return_value=cache),
        patch(
            "asky.cli.local_ingestion_flow.get_vector_store", return_value=vector_store
        ),
        patch("asky.cli.local_ingestion_flow.chunk_text", return_value=[(0, "chunk")]),
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve") as mock_resolve,
        patch("asky.cli.local_ingestion_flow.fetch_source_via_adapter") as mock_fetch,
    ):
        mock_resolve.return_value.as_posix.return_value = "/tmp/corpus"
        mock_fetch.side_effect = [
            {
                "title": "Corpus",
                "content": "Directory index",
                "links": [{"text": "Doc 1", "href": "local:///tmp/corpus/doc1.txt"}],
                "error": None,
            },
            {
                "title": "Doc 1",
                "content": "Document body",
                "links": [],
                "error": None,
            },
        ]
        payload = preload_local_research_sources("use /tmp/corpus")

    assert payload["enabled"] is True
    assert payload["stats"]["processed_documents"] == 2
    assert payload["stats"]["indexed_chunks"] == 3
    assert len(payload["ingested"]) == 2


def test_format_local_ingestion_context_outputs_compact_summary():
    from asky.cli.local_ingestion_flow import format_local_ingestion_context

    context = format_local_ingestion_context(
        {
            "ingested": [
                {
                    "target": "local:///tmp/doc.txt",
                    "title": "doc.txt",
                    "source_type": "discovered",
                    "content_chars": 100,
                    "indexed_chunks": 2,
                }
            ],
            "warnings": [],
        }
    )

    assert context is not None
    assert "Local knowledge base preloaded before tool calls" in context
    assert "Documents indexed: 1" in context
    assert "Chunk embeddings added: 2" in context


def test_preload_local_research_sources_uses_explicit_targets():
    from asky.cli.local_ingestion_flow import preload_local_research_sources

    with (
        patch(
            "asky.cli.local_ingestion_flow.extract_local_source_targets"
        ) as mock_extract,
        patch("asky.cli.local_ingestion_flow.ResearchCache"),
        patch("asky.cli.local_ingestion_flow.get_vector_store"),
        patch("asky.cli.local_ingestion_flow.fetch_source_via_adapter") as mock_fetch,
    ):
        mock_fetch.return_value = None  # Just to stop early
        payload = preload_local_research_sources(
            "ignore paths in prompt", explicit_targets=["/explicit/path"]
        )

    assert payload["targets"] == ["/explicit/path"]
    mock_extract.assert_not_called()

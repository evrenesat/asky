from pathlib import Path

import pytest

from asky.evals.research_pipeline.dataset import DatasetDocument
from asky.evals.research_pipeline.source_providers import get_source_provider


def _docs():
    return [
        DatasetDocument(id="d1", title="Doc 1", url="https://example.com/d1"),
        DatasetDocument(id="d2", title="Doc 2", url="https://example.com/d2"),
    ]


def test_local_snapshot_provider_builds_query_with_paths(tmp_path):
    provider = get_source_provider("local_snapshot")
    docs = _docs()
    snapshot_paths = {
        "d1": tmp_path / "d1.pdf",
        "d2": tmp_path / "d2.pdf",
    }

    payload = provider.build_query(
        base_query="What does RFC say?",
        docs=docs,
        snapshot_paths=snapshot_paths,
    )

    assert payload.provider_name == "local_snapshot"
    assert str(snapshot_paths["d1"]) in payload.query_text
    assert payload.source_identifiers == [str(snapshot_paths["d1"]), str(snapshot_paths["d2"])]


def test_live_web_provider_builds_query_with_urls():
    provider = get_source_provider("live_web")
    docs = _docs()

    payload = provider.build_query(base_query="What does RFC say?", docs=docs)

    assert payload.provider_name == "live_web"
    assert "https://example.com/d1" in payload.query_text
    assert payload.source_identifiers == ["https://example.com/d1", "https://example.com/d2"]


def test_mock_provider_is_placeholder():
    provider = get_source_provider("mock_web")
    with pytest.raises(NotImplementedError):
        provider.build_query(base_query="q", docs=_docs())


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown source provider"):
        get_source_provider("unknown")

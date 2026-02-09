"""Tests for research source adapter integration."""

import json
from unittest.mock import MagicMock, patch


def test_get_source_adapter_matches_configured_prefix():
    """Adapter should match targets by configured prefix."""
    from asky.research.adapters import get_source_adapter

    adapter_cfg = {
        "local": {
            "enabled": True,
            "prefix": "local://",
            "tool": "local_research_source",
        }
    }

    with patch("asky.research.adapters.RESEARCH_SOURCE_ADAPTERS", adapter_cfg):
        adapter = get_source_adapter("local://papers")

    assert adapter is not None
    assert adapter.name == "local"
    assert adapter.prefix == "local://"
    assert adapter.discover_tool == "local_research_source"
    assert adapter.read_tool == "local_research_source"


def test_fetch_source_via_adapter_normalizes_payload():
    """Adapter payload should normalize to title/content/links."""
    from asky.research.adapters import fetch_source_via_adapter

    adapter_cfg = {
        "local": {
            "enabled": True,
            "prefix": "local://",
            "tool": "local_research_source",
        }
    }
    stdout_payload = {
        "title": "Paper Directory",
        "content": "Index content",
        "items": [
            {"title": "Doc One", "url": "local://doc-1"},
            {"name": "Doc Two", "href": "local://doc-2"},
        ],
    }

    with patch("asky.research.adapters.RESEARCH_SOURCE_ADAPTERS", adapter_cfg):
        with patch("asky.research.adapters._execute_custom_tool") as mock_exec:
            mock_exec.return_value = {
                "stdout": json.dumps(stdout_payload),
                "stderr": "",
                "exit_code": 0,
            }
            result = fetch_source_via_adapter(
                "local://papers", query="ai safety", max_links=10
            )

    assert result["error"] is None
    assert result["title"] == "Paper Directory"
    assert result["content"] == "Index content"
    assert result["links"] == [
        {"text": "Doc One", "href": "local://doc-1"},
        {"text": "Doc Two", "href": "local://doc-2"},
    ]
    mock_exec.assert_called_once_with(
        "local_research_source",
        {
            "target": "local://papers",
            "max_links": 10,
            "operation": "discover",
            "query": "ai safety",
        },
    )


def test_fetch_source_via_adapter_handles_invalid_json():
    """Invalid adapter stdout should return normalized error."""
    from asky.research.adapters import fetch_source_via_adapter

    adapter_cfg = {
        "local": {
            "enabled": True,
            "prefix": "local://",
            "tool": "local_research_source",
        }
    }

    with patch("asky.research.adapters.RESEARCH_SOURCE_ADAPTERS", adapter_cfg):
        with patch("asky.research.adapters._execute_custom_tool") as mock_exec:
            mock_exec.return_value = {
                "stdout": "not-json",
                "stderr": "",
                "exit_code": 0,
            }
            result = fetch_source_via_adapter("local://papers")

    assert "error" in result
    assert result["error"].startswith("Adapter tool returned invalid JSON:")


def test_fetch_source_via_adapter_uses_read_tool_for_read_operation():
    """Read operation should dispatch to read_tool when configured."""
    from asky.research.adapters import fetch_source_via_adapter

    adapter_cfg = {
        "local": {
            "enabled": True,
            "prefix": "local://",
            "discover_tool": "local_list",
            "read_tool": "local_read",
        }
    }

    with patch("asky.research.adapters.RESEARCH_SOURCE_ADAPTERS", adapter_cfg):
        with patch("asky.research.adapters._execute_custom_tool") as mock_exec:
            mock_exec.return_value = {
                "stdout": json.dumps({"title": "Doc", "content": "Body", "links": []}),
                "stderr": "",
                "exit_code": 0,
            }
            result = fetch_source_via_adapter("local://doc-1", operation="read")

    assert result["error"] is None
    mock_exec.assert_called_once_with(
        "local_read",
        {"target": "local://doc-1", "max_links": 50, "operation": "read"},
    )


def test_get_full_content_hydrates_from_adapter_when_missing_cache():
    """get_full_content should fetch/cache adapter targets lazily."""
    from asky.research.tools import execute_get_full_content

    with patch("asky.research.tools._get_cache") as mock_get_cache:
        cache = MagicMock()
        cache.get_cached.side_effect = [
            None,
            {"id": 1, "title": "Doc", "content": "Document text", "links": []},
        ]
        mock_get_cache.return_value = cache

        with patch("asky.research.tools.has_source_adapter", return_value=True):
            with patch("asky.research.tools._fetch_and_parse") as mock_fetch:
                mock_fetch.return_value = {
                    "title": "Doc",
                    "content": "Document text",
                    "links": [],
                    "error": None,
                }
                result = execute_get_full_content({"urls": ["local://doc-1"]})

    assert result["local://doc-1"]["content"] == "Document text"
    cache.cache_url.assert_called_once()


def test_get_relevant_content_hydrates_from_adapter_when_missing_cache():
    """get_relevant_content should hydrate adapter sources before RAG search."""
    from asky.research.tools import execute_get_relevant_content

    with patch("asky.research.tools._get_cache") as mock_get_cache:
        cache = MagicMock()
        cache.get_cached.side_effect = [
            None,
            {"id": 7, "title": "Doc", "content": "Document text", "links": []},
        ]
        mock_get_cache.return_value = cache

        with patch("asky.research.tools.has_source_adapter", return_value=True):
            with patch("asky.research.tools._fetch_and_parse") as mock_fetch:
                mock_fetch.return_value = {
                    "title": "Doc",
                    "content": "Document text",
                    "links": [],
                    "error": None,
                }
                with patch("asky.research.tools.get_vector_store") as mock_vs:
                    store = MagicMock()
                    store.has_chunk_embeddings.return_value = True
                    store.search_chunks.return_value = [("Matched section", 0.93)]
                    mock_vs.return_value = store

                    result = execute_get_relevant_content(
                        {"urls": ["local://doc-1"], "query": "matched"}
                    )

    assert "chunks" in result["local://doc-1"]
    assert result["local://doc-1"]["chunks"][0]["relevance"] == 0.93


def test_builtin_local_adapter_reads_text_file(tmp_path):
    """Builtin local adapter should read plain text files without custom tool config."""
    from asky.research.adapters import fetch_source_via_adapter

    source_file = tmp_path / "notes.txt"
    source_file.write_text("local research text", encoding="utf-8")

    result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] is None
    assert result["title"] == "notes.txt"
    assert "local research text" in result["content"]


def test_builtin_local_adapter_discovers_directory_files(tmp_path):
    """Builtin local adapter should expose supported files as local:// links."""
    from asky.research.adapters import fetch_source_via_adapter

    source_dir = tmp_path / "corpus"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("A", encoding="utf-8")
    (source_dir / "b.md").write_text("B", encoding="utf-8")
    (source_dir / "ignored.bin").write_bytes(b"\x00\x01")

    result = fetch_source_via_adapter(
        f"local://{source_dir.as_posix()}",
        operation="discover",
        max_links=10,
    )

    assert result is not None
    assert result["error"] is None
    hrefs = {item["href"] for item in result["links"]}
    assert len(result["links"]) == 2
    assert any(href.endswith("/a.txt") for href in hrefs)
    assert any(href.endswith("/b.md") for href in hrefs)


def test_builtin_local_adapter_pdf_requires_pymupdf(tmp_path):
    """PDF/EPUB local reads should fail with explicit dependency guidance when missing."""
    from asky.research.adapters import fetch_source_via_adapter

    source_file = tmp_path / "paper.pdf"
    source_file.write_bytes(b"%PDF-1.4\n")

    with patch("asky.research.adapters._load_pymupdf_module", return_value=None):
        result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] == "PyMuPDF is required to read PDF/EPUB local sources."

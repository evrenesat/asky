import pytest
from unittest.mock import MagicMock, patch
from asky.tools import (
    execute_web_search,
    fetch_single_url,
    execute_get_url_content,
    execute_get_url_details,
    _sanitize_url,
)


def test_sanitize_url():
    assert _sanitize_url("http://ex.com/a\\(b\\)") == "http://ex.com/a(b)"
    assert _sanitize_url(None) == ""
    assert _sanitize_url("norm") == "norm"


@pytest.fixture
def mock_requests_get():
    with patch("requests.get") as mock:
        yield mock


@patch("asky.tools.SEARCH_PROVIDER", "searxng")
def test_execute_web_search_success(mock_requests_get):
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "Test Title",
                "url": "http://test.com",
                "content": "Test content",
                "engine": "google",
            }
        ]
    }
    mock_response.status_code = 200
    mock_response.text = ""
    mock_requests_get.return_value = mock_response

    result = execute_web_search({"q": "test query"})
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Test Title"


@patch("asky.tools.SEARCH_PROVIDER", "searxng")
def test_execute_web_search_failure(mock_requests_get):
    mock_requests_get.side_effect = Exception("Search failed")
    result = execute_web_search({"q": "fail"})
    assert "error" in result
    assert "Search failed" in result["error"]


def test_fetch_single_url_success(mock_requests_get):
    with patch("asky.tools.fetch_url_document") as mock_fetch:
        mock_fetch.return_value = {
            "error": None,
            "content": "Page content",
        }
        result = fetch_single_url("http://example.com")

    assert "http://example.com" in result
    assert result["http://example.com"] == "Page content"


def test_execute_get_url_content_batch(mock_requests_get):
    with patch("asky.tools.fetch_url_document") as mock_fetch:
        mock_fetch.side_effect = [
            {"error": None, "content": "content-a"},
            {"error": None, "content": "content-b"},
        ]
        args = {"urls": ["http://a.com", "http://b.com"]}
        result = execute_get_url_content(args)

    assert "http://a.com" in result
    assert "http://b.com" in result
    assert len(result) == 2


def test_execute_get_url_content_rejects_local_targets(mock_requests_get):
    result = execute_get_url_content(
        {"urls": ["local:///tmp/file.txt", "/tmp/file.txt"]}
    )

    assert "local:///tmp/file.txt" in result
    assert (
        "Local filesystem targets are not supported" in result["local:///tmp/file.txt"]
    )
    assert "/tmp/file.txt" in result
    assert "Local filesystem targets are not supported" in result["/tmp/file.txt"]


def test_execute_get_url_content_rejects_non_http_targets(mock_requests_get):
    result = execute_get_url_content({"urls": ["ftp://example.com/resource"]})

    assert "ftp://example.com/resource" in result
    assert "Only HTTP(S) URLs are supported" in result["ftp://example.com/resource"]


def test_execute_get_url_details(mock_requests_get):
    with patch("asky.tools.fetch_url_document") as mock_fetch:
        mock_fetch.return_value = {
            "error": None,
            "content": "Text Link",
            "links": [{"text": "Link", "href": "http://link.com"}],
            "title": "Main Page",
            "date": None,
            "final_url": "http://main.com",
        }
        result = execute_get_url_details({"url": "http://main.com"})

    assert "content" in result
    assert "links" in result
    assert result["content"] == "Text Link"
    assert result["links"][0]["href"] == "http://link.com"


def test_execute_get_url_details_rejects_local_target(mock_requests_get):
    result = execute_get_url_details({"url": "local:///tmp/file.txt"})
    assert "error" in result
    assert "Local filesystem targets are not supported" in result["error"]


def test_execute_get_url_details_rejects_non_http_target(mock_requests_get):
    result = execute_get_url_details({"url": "ftp://example.com/resource"})
    assert "error" in result
    assert "Only HTTP(S) URLs are supported" in result["error"]


@patch("asky.tools.SEARCH_PROVIDER", "searxng")
def test_dispatch_tool_registry_search(mock_requests_get):
    from asky.core import create_tool_registry

    # Mock web search dispatch
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.status_code = 200
    mock_response.text = ""
    mock_requests_get.return_value = mock_response

    registry = create_tool_registry()
    call = {"function": {"name": "web_search", "arguments": '{"q": "test"}'}}

    result = registry.dispatch(call, summarize=False)
    assert "results" in result


@patch("asky.tools.SEARCH_PROVIDER", "serper")
@patch("os.environ.get")
@patch("requests.post")
def test_execute_serper_search_success(mock_post, mock_env_get):
    mock_env_get.return_value = "fake-key"
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "organic": [
            {
                "title": "Serper Result",
                "link": "http://serper.com",
                "snippet": "Serper content",
            }
        ]
    }
    mock_post.return_value = mock_response

    from asky.tools import _execute_serper_search

    result = _execute_serper_search("query", count=1)

    assert "results" in result
    assert result["results"][0]["title"] == "Serper Result"
    assert result["results"][0]["engine"] == "serper"


@patch("asky.tools.SEARCH_PROVIDER", "serper")
@patch("asky.tools._execute_serper_search")
def test_execute_web_search_dispatch_serper(mock_serper):
    from asky.tools import execute_web_search

    execute_web_search({"q": "test"})
    mock_serper.assert_called_once()


@patch("asky.tools.SEARCH_PROVIDER", "searxng")
@patch("asky.tools._execute_searxng_search")
def test_execute_web_search_dispatch_searxng(mock_searxng):
    from asky.tools import execute_web_search

    execute_web_search({"q": "test"})
    mock_searxng.assert_called_once()


def test_registry_guidelines_are_not_sent_in_api_schema():
    from asky.core.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        "sample_tool",
        {
            "name": "sample_tool",
            "description": "Sample tool",
            "system_prompt_guideline": "Use only for focused checks.",
            "parameters": {"type": "object", "properties": {}},
        },
        lambda _args: {"ok": True},
    )

    schemas = registry.get_schemas()
    assert schemas[0]["function"]["name"] == "sample_tool"
    assert "system_prompt_guideline" not in schemas[0]["function"]
    assert registry.get_system_prompt_guidelines() == [
        "`sample_tool`: Use only for focused checks."
    ]


def test_default_registry_respects_disabled_tools_and_custom_guidelines():
    from asky.core.tool_registry_factory import create_tool_registry

    custom_tools = {
        "custom_echo": {
            "command": "echo",
            "enabled": True,
            "description": "Echo input",
            "system_prompt_guideline": "Use for shell echo checks.",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
            },
        }
    }

    registry = create_tool_registry(
        execute_web_search_fn=lambda _args: {},
        execute_get_url_content_fn=lambda _args: {},
        execute_get_url_details_fn=lambda _args: {},
        execute_custom_tool_fn=lambda _name, _args: {},
        custom_tools=custom_tools,
        disabled_tools={"web_search"},
    )

    tool_names = registry.get_tool_names()
    assert "web_search" not in tool_names
    assert "custom_echo" in tool_names
    assert any(
        guideline.startswith("`custom_echo`:")
        for guideline in registry.get_system_prompt_guidelines()
    )


def test_research_registry_injects_session_id_for_memory_tools():
    from asky.core.tool_registry_factory import create_research_tool_registry

    save_calls = []
    query_calls = []

    def save_executor(args):
        save_calls.append(args)
        return {"ok": True}

    def query_executor(args):
        query_calls.append(args)
        return {"ok": True}

    bindings = {
        "schemas": [
            {
                "name": "save_finding",
                "description": "Save finding",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "query_research_memory",
                "description": "Query finding memory",
                "parameters": {"type": "object", "properties": {}},
            },
        ],
        "extract_links": lambda _args: {},
        "get_link_summaries": lambda _args: {},
        "get_relevant_content": lambda _args: {},
        "get_full_content": lambda _args: {},
        "save_finding": save_executor,
        "query_research_memory": query_executor,
    }

    registry = create_research_tool_registry(
        load_research_tool_bindings_fn=lambda: bindings,
        disabled_tools={"web_search"},
        session_id="session-123",
    )

    registry.dispatch(
        {
            "function": {
                "name": "save_finding",
                "arguments": '{"finding":"foo"}',
            }
        },
        summarize=False,
    )
    registry.dispatch(
        {
            "function": {
                "name": "query_research_memory",
                "arguments": '{"query":"foo","session_id":"explicit"}',
            }
        },
        summarize=False,
    )

    assert save_calls[-1]["session_id"] == "session-123"
    assert query_calls[-1]["session_id"] == "explicit"


def test_tool_name_sets_cover_all_schemas():
    from asky.research.tools import (
        ACQUISITION_TOOL_NAMES,
        RESEARCH_TOOL_SCHEMAS,
        RETRIEVAL_TOOL_NAMES,
    )

    all_schema_names = {s["name"] for s in RESEARCH_TOOL_SCHEMAS}
    covered_names = ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES
    assert covered_names == all_schema_names


def test_research_registry_corpus_preloaded_excludes_acquisition_tools():
    from asky.core.tool_registry_factory import create_research_tool_registry
    from asky.research.tools import ACQUISITION_TOOL_NAMES, RETRIEVAL_TOOL_NAMES

    # Dummy bindings for all tools
    bindings = {
        "schemas": [
            {"name": name, "parameters": {"type": "object", "properties": {}}}
            for name in (ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES)
        ],
    }
    for name in ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES:
        bindings[name] = lambda _args: {}

    registry = create_research_tool_registry(
        load_research_tool_bindings_fn=lambda: bindings,
        disabled_tools={"web_search"},
        corpus_preloaded=True,
    )

    schemas = registry.get_schemas()
    schema_names = {s["function"]["name"] for s in schemas}

    # Acquisition tools should be missing
    for name in ACQUISITION_TOOL_NAMES:
        assert name not in schema_names

    # Retrieval tools should be present
    for name in RETRIEVAL_TOOL_NAMES:
        assert name in schema_names


def test_research_registry_corpus_not_preloaded_keeps_all_tools():
    from asky.core.tool_registry_factory import create_research_tool_registry
    from asky.research.tools import ACQUISITION_TOOL_NAMES, RETRIEVAL_TOOL_NAMES

    # Dummy bindings
    bindings = {
        "schemas": [
            {"name": name, "parameters": {"type": "object", "properties": {}}}
            for name in (ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES)
        ],
    }
    for name in ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES:
        bindings[name] = lambda _args: {}

    registry = create_research_tool_registry(
        load_research_tool_bindings_fn=lambda: bindings,
        disabled_tools={"web_search"},
        corpus_preloaded=False,
    )

    schemas = registry.get_schemas()
    schema_names = {s["function"]["name"] for s in schemas}

    # All tools should be present (except web_search which we disabled manually)
    for name in ACQUISITION_TOOL_NAMES | RETRIEVAL_TOOL_NAMES:
        assert name in schema_names

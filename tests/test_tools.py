import pytest
from unittest.mock import MagicMock, patch
from asearch.tools import (
    execute_web_search,
    fetch_single_url,
    execute_get_url_content,
    execute_get_url_details,
    execute_get_date_time,
    dispatch_tool_call,
    reset_read_urls,
    summarize_text,
)


@pytest.fixture
def mock_requests_get():
    with patch("requests.get") as mock:
        yield mock


@pytest.fixture
def reset_urls():
    reset_read_urls()
    yield
    reset_read_urls()


@patch("asearch.tools.SEARCH_PROVIDER", "searxng")
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
    mock_requests_get.return_value = mock_response

    result = execute_web_search({"q": "test query"})
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Test Title"


@patch("asearch.tools.SEARCH_PROVIDER", "searxng")
def test_execute_web_search_failure(mock_requests_get):
    mock_requests_get.side_effect = Exception("Search failed")
    result = execute_web_search({"q": "fail"})
    assert "error" in result
    assert "Search failed" in result["error"]


def test_fetch_single_url_success(mock_requests_get, reset_urls):
    mock_response = MagicMock()
    mock_response.text = "<p>Page content</p>"
    mock_requests_get.return_value = mock_response

    result = fetch_single_url("http://example.com", max_chars=100)
    assert "http://example.com" in result
    assert result["http://example.com"] == "Page content"


def test_fetch_single_url_already_read(mock_requests_get, reset_urls):
    mock_response = MagicMock()
    mock_response.text = "content"
    mock_requests_get.return_value = mock_response

    # First fetch
    fetch_single_url("http://example.com", max_chars=100)
    # Second fetch
    result = fetch_single_url("http://example.com", max_chars=100)
    assert "Error: Already read this URL" in result["http://example.com"]


def test_execute_get_url_content_batch(mock_requests_get, reset_urls):
    mock_response = MagicMock()
    mock_response.text = "content"
    mock_requests_get.return_value = mock_response

    args = {"urls": ["http://a.com", "http://b.com"]}
    result = execute_get_url_content(args, max_chars=100, summarize=False)

    assert "http://a.com" in result
    assert "http://b.com" in result
    assert len(result) == 2


def test_execute_get_url_details(mock_requests_get, reset_urls):
    mock_response = MagicMock()
    mock_response.text = (
        '<html><body>Text <a href="http://link.com">Link</a></body></html>'
    )
    mock_requests_get.return_value = mock_response

    result = execute_get_url_details({"url": "http://main.com"}, max_chars=100)
    assert "content" in result
    assert "links" in result
    assert result["content"] == "Text Link"
    assert result["links"][0]["href"] == "http://link.com"


@patch("asearch.tools.SEARCH_PROVIDER", "searxng")
def test_dispatch_tool_call(mock_requests_get, reset_urls):
    # Mock web search dispatch
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_requests_get.return_value = mock_response

    call = {"function": {"name": "web_search", "arguments": '{"q": "test"}'}}
    result = dispatch_tool_call(call, max_chars=1000, summarize=False)
    assert "results" in result


def test_execute_get_date_time():
    result = execute_get_date_time()
    assert "date_time" in result
    assert "T" in result["date_time"]  # Basic ISO format check


@patch("asearch.llm.get_llm_msg")
def test_summarize_text(mock_get_msg):
    # Mock LLM response
    mock_get_msg.return_value = {"content": "Buffered Summary"}

    summary = summarize_text("Long text content")

    assert summary == "Buffered Summary"

    # Verify strict mocking of inner import
    # Note: summarize_text imports get_llm_msg inside the function.
    # unittest.mock.patch usually handles this if we patch 'asearch.llm.get_llm_msg'
    # BEFORE summarize_text imports it?
    # summarize_text does `from asearch.llm import get_llm_msg` INSIDE.
    # So we need to patch `asearch.llm.get_llm_msg` globally, which `patch` should do.

    args, kwargs = mock_get_msg.call_args
    # First arg is model_id, checks config
    assert len(args) >= 2


def test_summarize_text_empty():
    assert summarize_text("") == ""


@patch("asearch.tools.SEARCH_PROVIDER", "serper")
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

    from asearch.tools import _execute_serper_search

    result = _execute_serper_search("query", count=1)

    assert "results" in result
    assert result["results"][0]["title"] == "Serper Result"
    assert result["results"][0]["engine"] == "serper"


@patch("asearch.tools.SEARCH_PROVIDER", "serper")
@patch("asearch.tools._execute_serper_search")
def test_execute_web_search_dispatch_serper(mock_serper):
    from asearch.tools import execute_web_search

    execute_web_search({"q": "test"})
    mock_serper.assert_called_once()


@patch("asearch.tools.SEARCH_PROVIDER", "searxng")
@patch("asearch.tools._execute_searxng_search")
def test_execute_web_search_dispatch_searxng(mock_searxng):
    from asearch.tools import execute_web_search

    execute_web_search({"q": "test"})
    mock_searxng.assert_called_once()

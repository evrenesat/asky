import pytest
from unittest.mock import MagicMock, patch
from asky.tools import (
    execute_web_search,
    fetch_single_url,
    execute_get_url_content,
    execute_get_url_details,
    execute_get_date_time,
    _sanitize_url,
)
from asky.core import dispatch_tool_call


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
    mock_response = MagicMock()
    mock_response.text = "<p>Page content</p>"
    mock_requests_get.return_value = mock_response

    result = fetch_single_url("http://example.com")
    assert "http://example.com" in result
    assert result["http://example.com"] == "Page content"


def test_execute_get_url_content_batch(mock_requests_get):
    mock_response = MagicMock()
    mock_response.text = "content"
    mock_requests_get.return_value = mock_response

    args = {"urls": ["http://a.com", "http://b.com"]}
    result = execute_get_url_content(args)

    assert "http://a.com" in result
    assert "http://b.com" in result
    assert len(result) == 2


def test_execute_get_url_details(mock_requests_get):
    mock_response = MagicMock()
    mock_response.text = (
        '<html><body>Text <a href="http://link.com">Link</a></body></html>'
    )
    mock_requests_get.return_value = mock_response

    result = execute_get_url_details({"url": "http://main.com"})
    assert "content" in result
    assert "links" in result
    assert result["content"] == "Text Link"
    assert result["links"][0]["href"] == "http://link.com"


@patch("asky.tools.SEARCH_PROVIDER", "searxng")
def test_dispatch_tool_call(mock_requests_get):
    # Mock web search dispatch
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.status_code = 200
    mock_response.text = ""
    mock_requests_get.return_value = mock_response

    call = {"function": {"name": "web_search", "arguments": '{"q": "test"}'}}
    result = dispatch_tool_call(call, summarize=False)
    assert "results" in result


def test_execute_get_date_time():
    result = execute_get_date_time()
    assert "date_time" in result
    assert "T" in result["date_time"]  # Basic ISO format check


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

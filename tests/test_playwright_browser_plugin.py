"""Tests for Playwright Browser Plugin."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from asky.plugins.hook_types import FETCH_URL_OVERRIDE, FetchURLContext
from asky.plugins.playwright_browser.plugin import PlaywrightBrowserPlugin


class MockContext:
    def __init__(self, data_dir, config):
        self.data_dir = data_dir
        self.config = config
        self.plugin_name = "playwright_browser"
        self.hook_registry = MagicMock()


@pytest.fixture
def plugin_context(tmp_path):
    config = {
        "intercept": ["get_url_content", "get_url_details", "research", "shortlist", "default"],
        "browser": "chromium",
        "persist_session": True,
    }
    return MockContext(tmp_path, config)


def test_plugin_activation(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    plugin_context.hook_registry.register.assert_called_once_with(
        FETCH_URL_OVERRIDE, 
        plugin._on_fetch_url_override,
        plugin_name=plugin_context.plugin_name
    )


def test_intercept_filtering_match(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    ctx = FetchURLContext(
        url="https://example.com",
        output_format="markdown",
        include_links=False,
        max_links=None,
        trace_callback=None,
        trace_context={"tool_name": "get_url_content"},
    )
    
    with patch.object(plugin._browser_manager, "fetch_page") as mock_fetch:
        mock_fetch.return_value = ("<html><body>Test</body></html>", "https://example.com")
        plugin._on_fetch_url_override(ctx)
        
        assert ctx.result is not None
        assert "playwright" in ctx.result["source"]
        assert ctx.result["content"] == "Test"


def test_intercept_filtering_no_match(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    ctx = FetchURLContext(
        url="https://example.com",
        output_format="markdown",
        include_links=False,
        max_links=None,
        trace_callback=None,
        trace_context={"tool_name": "research"},
    )
    
    plugin._on_fetch_url_override(ctx)
    assert ctx.result is None


def test_fallback_on_playwright_error(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    ctx = FetchURLContext(
        url="https://example.com",
        output_format="markdown",
        include_links=False,
        max_links=None,
        trace_callback=None,
        trace_context={"tool_name": "get_url_content"},
    )
    
    with patch.object(plugin._browser_manager, "fetch_page", side_effect=Exception("Browser crash")):
        plugin._on_fetch_url_override(ctx)
        assert ctx.result is None


def test_result_dict_shape(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    ctx = FetchURLContext(
        url="https://example.com",
        output_format="markdown",
        include_links=True,
        max_links=10,
        trace_callback=None,
        trace_context={"tool_name": "get_url_content"},
    )
    
    html = '<html><head><title>Test Title</title></head><body><a href="/link">Link</a></body></html>'
    with patch.object(plugin._browser_manager, "fetch_page") as mock_fetch:
        mock_fetch.return_value = (html, "https://example.com/final")
        plugin._on_fetch_url_override(ctx)
        
        res = ctx.result
        assert res["error"] is None
        assert res["requested_url"] == "https://example.com"
        assert res["final_url"] == "https://example.com/final"
        assert res["title"] == "Test Title"
        assert "playwright" in res["source"]
        assert len(res["links"]) == 1
        assert res["links"][0]["href"] == "https://example.com/link"


@patch("asky.plugins.playwright_browser.browser.time.sleep")
@patch("asky.plugins.playwright_browser.browser.time.perf_counter")
def test_same_site_delay_logic(mock_perf, mock_sleep, tmp_path):
    from asky.plugins.playwright_browser.browser import PlaywrightBrowserManager
    
    manager = PlaywrightBrowserManager(
        data_dir=tmp_path,
        same_site_min_delay_ms=2000,
        same_site_max_delay_ms=2000,
    )
    
    # Mock playwright start
    manager._playwright = MagicMock()
    manager._browser = MagicMock()
    manager._context = MagicMock()
    
    # First call - no delay
    mock_perf.return_value = 100.0
    manager._apply_delay("https://example.com/1")
    mock_sleep.assert_not_called()
    
    # Second call to same domain, 0.5s later -> should sleep 1.5s
    mock_perf.return_value = 100.5
    manager._apply_delay("https://example.com/2")
    mock_sleep.assert_called_once_with(1.5)
    
    # Third call to different domain -> no sleep
    mock_sleep.reset_mock()
    manager._apply_delay("https://other.com")
    mock_sleep.assert_not_called()


def test_intercept_filtering_default_fallback(plugin_context):
    plugin = PlaywrightBrowserPlugin()
    plugin.activate(plugin_context)
    
    ctx = FetchURLContext(
        url="https://example.com",
        output_format="markdown",
        include_links=False,
        max_links=None,
        trace_callback=None,
        trace_context=None, # Missing tool_name and source
    )
    
    with patch.object(plugin._browser_manager, "fetch_page") as mock_fetch:
        mock_fetch.return_value = ("<html><body>Default</body></html>", "https://example.com")
        plugin._on_fetch_url_override(ctx)
        
        assert ctx.result is not None
        assert ctx.result["content"] == "Default"


def test_try_fetch_url_plugin_override_no_runtime():
    """Verify _try_fetch_url_plugin_override returns None when runtime is missing."""
    from asky.retrieval import _try_fetch_url_plugin_override
    
    with patch("asky.plugins.runtime.get_or_create_plugin_runtime", return_value=None):
        result = _try_fetch_url_plugin_override(
            url="https://example.com",
            output_format="markdown",
            include_links=False,
            max_links=None,
            trace_callback=None,
            trace_context=None,
        )
        assert result is None

import pytest
from asky.cli.chat import _parse_disabled_tools
from asky.core.tool_registry_factory import get_all_available_tool_names
from asky.cli.completion import complete_tool_names
from unittest.mock import MagicMock


def test_get_all_available_tool_names():
    tools = get_all_available_tool_names()
    assert isinstance(tools, list)
    # Basic tools should always be there
    assert "web_search" in tools
    assert "get_url_content" in tools
    assert "get_url_details" in tools
    # Research tools should be there
    assert "extract_links" in tools
    # Sorted
    assert tools == sorted(tools)


def test_parse_disabled_tools_all():
    all_tools = get_all_available_tool_names()

    # Test 'all'
    disabled = _parse_disabled_tools(["all"])
    assert disabled == set(all_tools)

    # Test 'all' with redundancy
    disabled = _parse_disabled_tools(["web_search", "all"])
    assert disabled == set(all_tools)


def test_parse_disabled_tools_specific():
    disabled = _parse_disabled_tools(["web_search", "get_url_content"])
    assert disabled == {"web_search", "get_url_content"}


def test_complete_tool_names():
    # Test with empty prefix
    completions = complete_tool_names("", MagicMock())
    assert "all" in completions
    assert "web_search" in completions

    # Test with prefix
    completions = complete_tool_names("web", MagicMock())
    assert "web_search" in completions
    assert "all" not in completions

    # Test with prefix 'a'
    completions = complete_tool_names("a", MagicMock())
    assert "all" in completions

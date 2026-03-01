import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from asky.research.adapters import fetch_source_via_adapter, LocalSourcePayload

def test_fetch_source_via_plugin_handler(tmp_path):
    """Confirm fetch_source_via_adapter uses plugin-provided handlers."""
    # Create a dummy file with a custom extension
    custom_file = tmp_path / "test.custom"
    custom_file.write_text("original content")
    
    # Mock plugin handler
    mock_handler = MagicMock()
    mock_handler.extensions = [".custom"]
    mock_handler.read.return_value = LocalSourcePayload(
        content="transcribed content",
        title="test.custom"
    )
    
    # Mock research roots to include tmp_path
    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path)]):
        # Mock plugin handlers hook
        with patch("asky.research.adapters._get_plugin_handlers", return_value=[mock_handler]):
            result = fetch_source_via_adapter(str(custom_file), operation="read")
            
            assert result is not None
            assert result["content"] == "transcribed content"
            assert result["title"] == "test.custom"
            mock_handler.read.assert_called_once_with(str(custom_file.resolve()))

def test_discover_custom_extension_via_plugin(tmp_path):
    """Confirm directory discovery includes plugin-provided extensions."""
    custom_file = tmp_path / "test.custom"
    custom_file.write_text("content")
    
    # Mock plugin handler
    mock_handler = MagicMock()
    mock_handler.extensions = [".custom"]
    
    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path)]):
        with patch("asky.research.adapters._get_plugin_handlers", return_value=[mock_handler]):
            result = fetch_source_via_adapter(str(tmp_path), operation="discover")
            
            assert result is not None
            assert any(link["text"] == "test.custom" for link in result["links"])

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from asky.plugins.voice_transcriber.plugin import VoiceTranscriberPlugin
from asky.plugins.image_transcriber.plugin import ImageTranscriberPlugin
from asky.plugins import PluginContext

def test_voice_transcribe_tool_rejects_non_https():
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {}
    plugin = VoiceTranscriberPlugin(ctx)
    
    result = plugin.transcribe_audio_url_tool(url="http://example.com/audio.mp3")
    assert "error" in result
    assert "HTTPS" in result["error"]

def test_voice_transcribe_tool_success(tmp_path):
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {"model": "m"}
    plugin = VoiceTranscriberPlugin(ctx)
    
    # Mock download and strategy
    with patch.object(plugin.service, "download_audio", return_value=tmp_path / "audio.mp3"):
        with patch.object(plugin.service.strategy, "transcribe", return_value="hello world"):
            result = plugin.transcribe_audio_url_tool(url="https://example.com/audio.mp3")
            
            assert result["status"] == "success"
            assert result["transcript"] == "hello world"

def test_image_transcribe_tool_rejects_non_https():
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {"model_alias": "m"}
    plugin = ImageTranscriberPlugin(ctx)
    
    result = plugin.transcribe_image_url_tool(url="http://example.com/image.png")
    assert "error" in result
    assert "HTTPS" in result["error"]

def test_image_transcribe_tool_success(tmp_path):
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {"model_alias": "m"}
    plugin = ImageTranscriberPlugin(ctx)
    
    # Mock download and service
    with patch.object(plugin.service, "download_image", return_value=(tmp_path / "image.png", "image/png")):
        with patch.object(plugin.service, "transcribe_file", return_value="a cat"):
            result = plugin.transcribe_image_url_tool(url="https://example.com/image.png")
            
            assert result["status"] == "success"
            assert result["description"] == "a cat"

def test_tool_registration_via_hook():
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {"model": "m", "model_alias": "m"}
    
    v_plugin = VoiceTranscriberPlugin(ctx)
    i_plugin = ImageTranscriberPlugin(ctx)
    
    registry = MagicMock()
    hook_ctx = MagicMock()
    hook_ctx.registry = registry
    hook_ctx.disabled_tools = set()
    
    v_plugin.on_tool_registry_build(hook_ctx)
    i_plugin.on_tool_registry_build(hook_ctx)
    
    # Check if register was called with correct names
    calls = [call[1]["name"] for call in registry.register.call_args_list]
    assert "transcribe_audio_url" in calls
    assert "transcribe_image_url" in calls

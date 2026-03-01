import pytest
from unittest.mock import MagicMock
from asky.plugins import PLUGIN_CAPABILITY_REGISTER, PluginCapabilityRegisterContext, PluginContext
from asky.plugins.voice_transcriber.plugin import VoiceTranscriberPlugin
from asky.plugins.image_transcriber.plugin import ImageTranscriberPlugin

def test_voice_transcriber_registers_capability():
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {}
    plugin = VoiceTranscriberPlugin(ctx)
    
    cap_ctx = PluginCapabilityRegisterContext()
    plugin.on_plugin_capability_register(cap_ctx)
    
    assert "voice_transcriber" in cap_ctx.capabilities
    assert cap_ctx.capabilities["voice_transcriber"] == plugin.service

def test_image_transcriber_registers_capability():
    ctx = MagicMock(spec=PluginContext)
    ctx.hook_registry = MagicMock()
    ctx.plugin_name = "test_plugin"
    ctx.config = {"model_alias": "m"}
    plugin = ImageTranscriberPlugin(ctx)
    
    cap_ctx = PluginCapabilityRegisterContext()
    plugin.on_plugin_capability_register(cap_ctx)
    
    assert "image_transcriber" in cap_ctx.capabilities
    assert cap_ctx.capabilities["image_transcriber"] == plugin.service

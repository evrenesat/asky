import pytest
from unittest.mock import MagicMock
from pathlib import Path
from asky.plugins.runtime import create_plugin_runtime
from asky.plugins.hook_types import (
    PLUGIN_CAPABILITY_REGISTER,
    LOCAL_SOURCE_HANDLER_REGISTER,
    TOOL_REGISTRY_BUILD,
    PluginCapabilityRegisterContext,
    LocalSourceHandlerRegisterContext,
    ToolRegistryBuildContext,
)
from asky.plugins.voice_transcriber.plugin import VoiceTranscriberPlugin
from asky.plugins.image_transcriber.plugin import ImageTranscriberPlugin

def test_voice_transcriber_full_hook_registration():
    """Verify VoiceTranscriberPlugin registers all intended hooks."""
    mock_runtime = MagicMock()
    mock_hooks = MagicMock()
    mock_runtime.hooks = mock_hooks
    
    ctx = MagicMock()
    ctx.hook_registry = mock_hooks
    ctx.config = {"voice_transcriber": {"model": "test-model", "workers": 2}}
    ctx.plugin_name = "voice_transcriber"
    
    plugin = VoiceTranscriberPlugin()
    plugin.activate(ctx)
    
    # Check that activate registered multiple hooks
    # We expect: TRAY_MENU_REGISTER, PLUGIN_CAPABILITY_REGISTER, 
    # LOCAL_SOURCE_HANDLER_REGISTER, TOOL_REGISTRY_BUILD
    registered_hooks = [call[0][0] for call in mock_hooks.register.call_args_list]
    assert "PLUGIN_CAPABILITY_REGISTER" in registered_hooks
    assert "LOCAL_SOURCE_HANDLER_REGISTER" in registered_hooks
    assert "TOOL_REGISTRY_BUILD" in registered_hooks
    assert "TRAY_MENU_REGISTER" in registered_hooks

    # Verify capability registration works
    cap_ctx = PluginCapabilityRegisterContext()
    plugin.on_plugin_capability_register(cap_ctx)
    assert "voice_transcriber" in cap_ctx.capabilities
    assert cap_ctx.capabilities["voice_transcriber"].model == "test-model"
    assert cap_ctx.capabilities["voice_transcriber"].preferred_workers == 2

def test_image_transcriber_full_hook_registration():
    """Verify ImageTranscriberPlugin registers all intended hooks."""
    mock_hooks = MagicMock()
    
    ctx = MagicMock()
    ctx.hook_registry = mock_hooks
    ctx.config = {"image_transcriber": {"model_alias": "test-vision", "workers": 3}}
    ctx.plugin_name = "image_transcriber"
    
    plugin = ImageTranscriberPlugin()
    plugin.activate(ctx)
    
    registered_hooks = [call[0][0] for call in mock_hooks.register.call_args_list]
    assert "PLUGIN_CAPABILITY_REGISTER" in registered_hooks
    assert "LOCAL_SOURCE_HANDLER_REGISTER" in registered_hooks
    assert "TOOL_REGISTRY_BUILD" in registered_hooks
    assert "TRAY_MENU_REGISTER" in registered_hooks

    # Verify capability registration
    cap_ctx = PluginCapabilityRegisterContext()
    plugin.on_plugin_capability_register(cap_ctx)
    assert "image_transcriber" in cap_ctx.capabilities
    assert cap_ctx.capabilities["image_transcriber"].model_alias == "test-vision"
    assert cap_ctx.capabilities["image_transcriber"].preferred_workers == 3

def test_tool_registration_method_call():
    """Verify plugins call .register() instead of non-existent .register_tool()."""
    ctx = MagicMock()
    ctx.config = {"voice_transcriber": {}, "image_transcriber": {}}
    
    v_plugin = VoiceTranscriberPlugin()
    v_plugin.activate(ctx)
    
    i_plugin = ImageTranscriberPlugin()
    i_plugin.activate(ctx)
    
    mock_registry = MagicMock()
    # ToolRegistry.register is the correct method
    
    hook_ctx = MagicMock()
    hook_ctx.registry = mock_registry
    hook_ctx.disabled_tools = set()
    
    v_plugin.on_tool_registry_build(hook_ctx)
    i_plugin.on_tool_registry_build(hook_ctx)
    
    # Verify .register() was called, and .register_tool() was NOT
    assert mock_registry.register.called
    assert not hasattr(mock_registry, "register_tool") or not mock_registry.register_tool.called

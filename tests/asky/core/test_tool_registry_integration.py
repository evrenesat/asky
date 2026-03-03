"""Integration tests for tool registry after persona tool removal."""

from __future__ import annotations

import logging
from pathlib import Path

from asky.core.registry import ToolRegistry
from asky.plugins.base import PluginContext
from asky.plugins.hook_types import ToolRegistryBuildContext
from asky.plugins.hooks import HookRegistry
from asky.plugins.manual_persona_creator.plugin import ManualPersonaCreatorPlugin
from asky.plugins.persona_manager.plugin import PersonaManagerPlugin


def _plugin_context(plugin_name: str, tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    """Create a plugin context for testing."""
    return PluginContext(
        plugin_name=plugin_name,
        config_dir=tmp_path,
        data_dir=tmp_path / "plugin_data",
        config={},
        hook_registry=hooks,
        logger=logging.getLogger(f"test.{plugin_name}"),
    )


def test_persona_manager_does_not_register_tools(tmp_path: Path):
    """Test that persona_manager plugin does not register any tools."""
    hooks = HookRegistry()
    plugin = PersonaManagerPlugin()
    context = _plugin_context("persona_manager", tmp_path, hooks)
    plugin.activate(context)

    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    tool_names = registry.get_tool_names()
    
    # Verify that persona management tools are NOT registered
    assert "persona_import_package" not in tool_names
    assert "persona_load" not in tool_names
    assert "persona_unload" not in tool_names
    assert "persona_current" not in tool_names
    assert "persona_list" not in tool_names


def test_manual_persona_creator_does_not_register_tools(tmp_path: Path):
    """Test that manual_persona_creator plugin does not register any tools."""
    hooks = HookRegistry()
    plugin = ManualPersonaCreatorPlugin()
    context = _plugin_context("manual_persona_creator", tmp_path, hooks)
    plugin.activate(context)

    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    tool_names = registry.get_tool_names()
    
    # Verify that persona creation tools are NOT registered
    assert "manual_persona_create" not in tool_names
    assert "manual_persona_add_sources" not in tool_names
    assert "manual_persona_list" not in tool_names
    assert "manual_persona_export" not in tool_names


def test_other_plugins_can_still_register_tools(tmp_path: Path):
    """Test that other plugins can still register tools correctly."""
    hooks = HookRegistry()
    
    # Register a mock plugin that adds a tool
    def _register_mock_tool(payload: ToolRegistryBuildContext) -> None:
        payload.registry.register(
            "mock_tool",
            {
                "name": "mock_tool",
                "description": "A mock tool for testing",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "input": {"type": "string", "description": "Test input"}
                    },
                    "required": ["input"],
                },
            },
            lambda args: {"result": f"mock: {args.get('input', '')}"},
        )
    
    hooks.register(
        "TOOL_REGISTRY_BUILD",
        _register_mock_tool,
        plugin_name="mock_plugin",
        priority=100,
    )
    
    # Also activate persona plugins to ensure they don't interfere
    persona_manager = PersonaManagerPlugin()
    persona_manager.activate(_plugin_context("persona_manager", tmp_path, hooks))
    
    manual_creator = ManualPersonaCreatorPlugin()
    manual_creator.activate(_plugin_context("manual_persona_creator", tmp_path, hooks))
    
    # Build the registry
    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    tool_names = registry.get_tool_names()
    
    # Verify that the mock tool is registered
    assert "mock_tool" in tool_names
    
    # Verify that persona tools are still NOT registered
    assert "persona_import_package" not in tool_names
    assert "persona_load" not in tool_names
    assert "manual_persona_create" not in tool_names
    assert "manual_persona_export" not in tool_names


def test_tool_registry_schemas_exclude_persona_tools(tmp_path: Path):
    """Test that tool registry schemas do not include persona tools."""
    hooks = HookRegistry()
    
    # Activate both persona plugins
    persona_manager = PersonaManagerPlugin()
    persona_manager.activate(_plugin_context("persona_manager", tmp_path, hooks))
    
    manual_creator = ManualPersonaCreatorPlugin()
    manual_creator.activate(_plugin_context("manual_persona_creator", tmp_path, hooks))
    
    # Build the registry
    registry = ToolRegistry()
    hooks.invoke(
        "TOOL_REGISTRY_BUILD",
        ToolRegistryBuildContext(mode="standard", registry=registry, disabled_tools=set()),
    )

    # Get all tool schemas
    schemas = registry.get_schemas()
    schema_names = [schema["function"]["name"] for schema in schemas]
    
    # Verify that persona tools are not in the schemas
    persona_tool_names = [
        "persona_import_package",
        "persona_load",
        "persona_unload",
        "persona_current",
        "persona_list",
        "manual_persona_create",
        "manual_persona_add_sources",
        "manual_persona_list",
        "manual_persona_export",
    ]
    
    for tool_name in persona_tool_names:
        assert tool_name not in schema_names, f"Tool {tool_name} should not be in registry schemas"

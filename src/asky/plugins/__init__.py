"""Asky plugin runtime package."""

from asky.plugins.base import AskyPlugin, PluginContext, PluginStatus
from asky.plugins.hook_types import (
    DAEMON_SERVER_REGISTER,
    LOCAL_SOURCE_HANDLER_REGISTER,
    LocalSourceHandlerRegisterContext,
    LocalSourceHandlerSpec,
    PLUGIN_CAPABILITY_REGISTER,
    PluginCapabilityRegisterContext,
    POST_LLM_RESPONSE,
    POST_PRELOAD,
    POST_TOOL_EXECUTE,
    PRE_LLM_CALL,
    PRE_PRELOAD,
    PRE_TOOL_EXECUTE,
    SESSION_RESOLVED,
    SYSTEM_PROMPT_EXTEND,
    TOOL_REGISTRY_BUILD,
    ToolRegistryBuildContext,
    TRAY_MENU_REGISTER,
    TrayMenuRegisterContext,
    TURN_COMPLETED,
)
from asky.plugins.hooks import HookRegistry
from asky.plugins.manager import PluginManager
from asky.plugins.manifest import PluginManifest
from asky.plugins.runtime import (
    PluginRuntime,
    create_plugin_runtime,
    get_or_create_plugin_runtime,
)

__all__ = [
    "AskyPlugin",
    "PluginContext",
    "PluginManifest",
    "PluginManager",
    "PluginRuntime",
    "PluginStatus",
    "HookRegistry",
    "create_plugin_runtime",
    "get_or_create_plugin_runtime",
    "TOOL_REGISTRY_BUILD",
    "ToolRegistryBuildContext",
    "TRAY_MENU_REGISTER",
    "TrayMenuRegisterContext",
    "SESSION_RESOLVED",
    "PRE_PRELOAD",
    "POST_PRELOAD",
    "SYSTEM_PROMPT_EXTEND",
    "PRE_LLM_CALL",
    "POST_LLM_RESPONSE",
    "PRE_TOOL_EXECUTE",
    "POST_TOOL_EXECUTE",
    "TURN_COMPLETED",
    "DAEMON_SERVER_REGISTER",
    "PLUGIN_CAPABILITY_REGISTER",
    "PluginCapabilityRegisterContext",
    "LOCAL_SOURCE_HANDLER_REGISTER",
    "LocalSourceHandlerRegisterContext",
    "LocalSourceHandlerSpec",
]

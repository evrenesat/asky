"""PushDataPlugin: registers push_data LLM tools and handles POST_TURN_RENDER."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import (
    POST_TURN_RENDER,
    TOOL_REGISTRY_BUILD,
    PostTurnRenderContext,
    ToolRegistryBuildContext,
)

logger = logging.getLogger(__name__)


class PushDataPlugin(AskyPlugin):
    """Built-in plugin that provides push_data LLM tools and CLI post-turn push."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self._on_tool_registry_build,
            plugin_name=context.plugin_name,
        )
        context.hook_registry.register(
            POST_TURN_RENDER,
            self._on_post_turn_render,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._context = None

    def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
        from asky.push_data import execute_push_data, get_enabled_endpoints

        for endpoint_name, endpoint_config in get_enabled_endpoints().items():
            fields_config = endpoint_config.get("fields", {})
            properties: Dict[str, Any] = {}
            required = []

            for key, value in fields_config.items():
                if (
                    isinstance(value, str)
                    and value.startswith("${")
                    and value.endswith("}")
                ):
                    param_name = value[2:-1]
                    if param_name not in {"query", "answer", "timestamp", "model"}:
                        properties[param_name] = {
                            "type": "string",
                            "description": f"Value for {param_name}",
                        }
                        required.append(param_name)

            tool_name = f"push_data_{endpoint_name}"
            if tool_name in payload.disabled_tools:
                continue

            description = endpoint_config.get("description", f"Push data to {endpoint_name}")

            def make_push_executor(ep_name: str):
                def push_executor(args: Dict[str, Any]) -> Dict[str, Any]:
                    return execute_push_data(ep_name, dynamic_args=args)

                return push_executor

            payload.registry.register(
                tool_name,
                {
                    "name": tool_name,
                    "description": description,
                    "system_prompt_guideline": endpoint_config.get(
                        "system_prompt_guideline",
                        "Use only after the final answer is complete and data is ready to publish.",
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
                make_push_executor(endpoint_name),
            )

    def _on_post_turn_render(self, ctx: PostTurnRenderContext) -> None:
        cli_args = ctx.cli_args
        if cli_args is None:
            return
        endpoint = getattr(cli_args, "push_data_endpoint", None)
        if not ctx.final_answer or not endpoint:
            return

        from asky.push_data import execute_push_data

        dynamic_args = dict(cli_args.push_params) if getattr(cli_args, "push_params", None) else {}
        query_text = ctx.request.query_text if ctx.request is not None else ""
        result = execute_push_data(
            endpoint,
            dynamic_args=dynamic_args,
            query=query_text,
            answer=ctx.final_answer,
            model=getattr(cli_args, "model", None),
        )
        is_lean = bool(getattr(cli_args, "lean", False))
        if result["success"]:
            if not is_lean:
                logger.info(
                    "Push data successful: %s - %s",
                    result["endpoint"],
                    result["status_code"],
                )
        else:
            logger.error(
                "Push data failed: %s - %s",
                result["endpoint"],
                result.get("error"),
            )

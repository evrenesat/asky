"""Tool registry for managing LLM-callable functions."""

import json
import logging
import inspect
from typing import Any, Dict, List, Optional, Callable


logger = logging.getLogger(__name__)


class ToolRegistry:
    """Manages tool schemas and dispatches tool calls."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}  # name -> schema
        self._executors: Dict[str, Callable] = {}  # name -> executor function
        self._tool_prompt_guidelines: Dict[str, str] = {}  # name -> guideline text

    def register(
        self,
        name: str,
        schema: Dict[str, Any],
        executor: Callable[..., Dict[str, Any]],
    ) -> None:
        """Register a tool with its schema and executor."""
        self._tools[name] = schema
        self._executors[name] = executor
        guideline = schema.get("system_prompt_guideline")
        if isinstance(guideline, str) and guideline.strip():
            self._tool_prompt_guidelines[name] = guideline.strip()
        elif name in self._tool_prompt_guidelines:
            del self._tool_prompt_guidelines[name]

    @staticmethod
    def _to_api_function_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Build an API-safe function schema from internal tool metadata."""
        return {
            "name": schema.get("name", ""),
            "description": schema.get("description", ""),
            "parameters": schema.get(
                "parameters", {"type": "object", "properties": {}}
            ),
        }

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return list of tool definitions for LLM payload."""
        return [
            {"type": "function", "function": self._to_api_function_schema(t)}
            for t in self._tools.values()
        ]

    def get_tool_names(self) -> List[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def get_system_prompt_guidelines(self) -> List[str]:
        """Return enabled tool usage guidelines in registration order."""
        guidelines: List[str] = []
        for tool_name in self._tools.keys():
            guideline = self._tool_prompt_guidelines.get(tool_name)
            if guideline:
                guidelines.append(f"`{tool_name}`: {guideline}")
        return guidelines

    def dispatch(
        self,
        call: Dict[str, Any],
        summarize: bool = False,
        crawler_state: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Dispatch a tool call to its registered executor."""
        func_call = call.get("function", {})
        name = func_call.get("name")
        args_str = func_call.get("arguments", "{}")

        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments for tool: {name}"}

        executor = self._executors.get(name)
        if not executor:
            return {"error": f"Unknown tool: {name}"}

        # Check executor signature to see if it accepts summarize or crawler_state
        try:
            sig = inspect.signature(executor)
            params = sig.parameters
            call_kwargs = {}
            if "summarize" in params:
                call_kwargs["summarize"] = summarize

            if call_kwargs:
                # Merge with tool-provided args if they don't overlap
                # Tool provided args take precedence if they arrive from the LLM
                return executor(args, **call_kwargs)
            return executor(args)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            return {"error": f"Tool execution failed: {str(e)}"}

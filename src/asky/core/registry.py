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

    def register(
        self,
        name: str,
        schema: Dict[str, Any],
        executor: Callable[..., Dict[str, Any]],
    ) -> None:
        """Register a tool with its schema and executor."""
        self._tools[name] = schema
        self._executors[name] = executor

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return list of tool definitions for LLM payload."""
        return [{"type": "function", "function": t} for t in self._tools.values()]

    def get_tool_names(self) -> List[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def dispatch(
        self,
        call: Dict[str, Any],
        summarize: bool = False,
        usage_tracker: Optional[Any] = None,
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

        # Check executor signature to see if it accepts summarize or usage_tracker
        try:
            sig = inspect.signature(executor)
            params = sig.parameters
            call_kwargs = {}
            if "summarize" in params:
                call_kwargs["summarize"] = summarize
            if "usage_tracker" in params:
                call_kwargs["usage_tracker"] = usage_tracker

            if call_kwargs:
                # Merge with tool-provided args if they don't overlap
                # Tool provided args take precedence if they arrive from the LLM
                return executor(args, **call_kwargs)
            return executor(args)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            return {"error": f"Tool execution failed: {str(e)}"}

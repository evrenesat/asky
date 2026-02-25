"""Interface-model planner for natural-language remote routing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from asky.config import MODELS
from asky.core.api_client import get_llm_msg

ACTION_COMMAND = "command"
ACTION_QUERY = "query"
VALID_ACTIONS = {ACTION_COMMAND, ACTION_QUERY}
JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class InterfaceAction:
    """Validated planner output consumed by daemon router."""

    action_type: str
    command_text: str = ""
    query_text: str = ""
    reason: str = ""


class InterfacePlanner:
    """Generate strict structured actions from natural-language messages."""

    def __init__(
        self,
        model_alias: Optional[str],
        *,
        system_prompt: str,
        command_reference: str = "",
        include_command_reference: bool = True,
    ):
        self.model_alias = str(model_alias or "").strip()
        if self.model_alias and self.model_alias not in MODELS:
            raise ValueError(f"Unknown interface model alias: {self.model_alias}")
        self.system_prompt = str(system_prompt or "").strip()
        self.command_reference = str(command_reference or "").strip()
        self.include_command_reference = bool(include_command_reference)

    @property
    def enabled(self) -> bool:
        return bool(self.model_alias)

    def plan(self, message_text: str) -> InterfaceAction:
        """Plan one remote action from natural-language user input."""
        normalized = str(message_text or "").strip()
        if not normalized:
            return InterfaceAction(action_type=ACTION_QUERY, query_text="")
        if not self.enabled:
            return InterfaceAction(action_type=ACTION_QUERY, query_text=normalized)

        model_config = MODELS[self.model_alias]
        model_id = model_config["id"]

        prompt = self._build_system_prompt()
        response = get_llm_msg(
            model_id,
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": normalized},
            ],
            use_tools=False,
            model_alias=self.model_alias,
        )
        content = str(response.get("content", "") or "").strip()
        payload = self._parse_action_payload(content)
        if payload is None:
            return InterfaceAction(
                action_type=ACTION_QUERY,
                query_text=normalized,
                reason="planner_parse_fallback",
            )

        action_type = str(payload.get("action_type", "") or "").strip().lower()
        command_text = str(payload.get("command_text", "") or "").strip()
        query_text = str(payload.get("query_text", "") or "").strip()
        if action_type not in VALID_ACTIONS:
            return InterfaceAction(
                action_type=ACTION_QUERY,
                query_text=normalized,
                reason="planner_invalid_action_type",
            )
        if action_type == ACTION_COMMAND and not command_text:
            return InterfaceAction(
                action_type=ACTION_QUERY,
                query_text=normalized,
                reason="planner_empty_command",
            )
        if action_type == ACTION_QUERY and not query_text:
            query_text = normalized
        return InterfaceAction(
            action_type=action_type,
            command_text=command_text,
            query_text=query_text,
        )

    def _parse_action_payload(self, content: str) -> Optional[dict]:
        text = str(content or "").strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        match = JSON_BLOCK_PATTERN.search(text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _build_system_prompt(self) -> str:
        prompt = self.system_prompt
        if (
            self.include_command_reference
            and self.command_reference
            and self.command_reference not in prompt
        ):
            prompt = (
                f"{prompt}\n\n"
                "Allowed remote command reference:\n"
                f"{self.command_reference}"
            ).strip()
        return prompt

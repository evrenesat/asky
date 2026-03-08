"""Shared adaptive interface policy for plain-query turns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from asky.config import MODELS
from asky.core.api_client import get_llm_msg

JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class InterfaceQueryPolicyDecision:
    """Structured result from the plain-query interface helper."""

    shortlist_enabled: bool = True
    web_tools_mode: str = "full"  # full|search_only|off
    prompt_enrichment: Optional[str] = None
    memory_action: Optional[Dict[str, Any]] = None
    reason: str = "default_policy"
    source: str = "fallback"
    diagnostics: Optional[Dict[str, Any]] = None


class InterfaceQueryPolicyEngine:
    """Adaptive policy engine for standard plain-query turns."""

    def __init__(
        self,
        model_alias: Optional[str] = None,
        system_prompt: Optional[str] = None,
        double_verbose: bool = False,
    ):
        self.model_alias = str(model_alias or "").strip()
        self.system_prompt = str(system_prompt or "").strip()
        self.double_verbose = bool(double_verbose)

    @property
    def interface_model_enabled(self) -> bool:
        return bool(self.model_alias) and self.model_alias in MODELS

    def decide(self, query_text: str) -> InterfaceQueryPolicyDecision:
        """Resolve adaptive policy for standard non-research turns."""
        if not self.interface_model_enabled or not self.system_prompt:
            return InterfaceQueryPolicyDecision(
                reason="interface_model_not_configured",
                source="fallback",
            )

        model_config = MODELS.get(self.model_alias)
        model_id = str((model_config or {}).get("id", "")).strip()
        if not model_id:
            return InterfaceQueryPolicyDecision(
                reason="interface_model_config_invalid",
                source="fallback",
            )

        try:
            response = get_llm_msg(
                model_id,
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": query_text},
                ],
                use_tools=False,
                model_alias=self.model_alias,
                verbose=self.double_verbose,
                trace_context={
                    "phase": "plain_query_interface",
                    "source": "interface_query_policy_engine",
                },
            )
        except Exception as exc:
            return InterfaceQueryPolicyDecision(
                reason=f"interface_model_transport_error: {exc}",
                source="fallback",
            )

        if not isinstance(response, dict):
            return InterfaceQueryPolicyDecision(
                reason="interface_model_invalid_response",
                source="fallback",
            )

        content = str(response.get("content", "") or "").strip()
        payload = self._parse_payload(content)

        if not payload:
            return InterfaceQueryPolicyDecision(
                reason="interface_model_parse_failure",
                source="fallback",
                diagnostics={"raw_content": content},
            )

        # Validate web_tools_mode
        web_tools_mode = str(payload.get("web_tools_mode", "full")).lower()
        if web_tools_mode not in {"full", "search_only", "off"}:
            web_tools_mode = "full"

        # Extract and validate memory_action
        raw_memory_action = payload.get("memory_action")
        memory_action = None
        if isinstance(raw_memory_action, dict):
            mem_text = str(raw_memory_action.get("memory", "") or "").strip()
            # Requirement: scope == "global", non-empty memory
            if mem_text and raw_memory_action.get("scope") == "global":
                # Normalize tags to a list of non-empty strings
                raw_tags = raw_memory_action.get("tags")
                tags = []
                if isinstance(raw_tags, list):
                    tags = [str(t).strip() for t in raw_tags if str(t).strip()]
                elif isinstance(raw_tags, str):
                    tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

                # Sanitize: only allow {memory, tags, scope}
                memory_action = {
                    "memory": mem_text,
                    "tags": tags,
                    "scope": "global",
                }

        return InterfaceQueryPolicyDecision(
            shortlist_enabled=bool(payload.get("shortlist_enabled", True)),
            web_tools_mode=web_tools_mode,
            prompt_enrichment=payload.get("prompt_enrichment"),
            memory_action=memory_action,
            reason=str(payload.get("reason", "") or "interface_model_decision"),
            source="interface_model",
            diagnostics=payload,
        )

    def _parse_payload(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse JSON payload from model response."""
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

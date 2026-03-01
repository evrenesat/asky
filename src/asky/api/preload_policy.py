"""Shared adaptive interface policy for preload shortlist enablement."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import requests
from asky.config import MODELS
from asky.core.api_client import get_llm_msg

# Intent classification types
INTENT_WEB = "web"
INTENT_LOCAL = "local"
INTENT_AMBIGUOUS = "ambiguous"

# Decision source labels
SOURCE_DETERMINISTIC = "deterministic"
SOURCE_INTERFACE_MODEL = "interface_model"
SOURCE_FALLBACK = "fallback"

# Deterministic patterns
WEB_INTENT_PATTERNS = [
    r"\blatest\b",
    r"\bcurrent\b",
    r"\bnews\b",
    r"\bweather\b",
    r"\bstock\b",
    r"\bonline\b",
    r"\bweb\b",
    r"\bsearch\b",
    r"\bgoogle\b",
    r"\bbrowse\b",
    r"\burl\b",
    r"\bhttp\b",
    r"\bhttps\b",
    r"\brecent\b",
    r"\bnow\b",
]

LOCAL_INTENT_PATTERNS = [
    r"\blocal\b",
    r"\bcorpus\b",
    r"\bdocuments?\b",
    r"\bfiles?\b",
    r"\bpdf\b",
    r"\bcsv\b",
    r"\btxt\b",
    r"\bmd\b",
    r"\bjson\b",
    r"\bmy\s+files\b",
    r"\bthis\s+document\b",
    r"\bthese\s+documents\b",
    r"\bin\s+the\s+files\b",
    r"\bhere\b",
]

JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class PolicyDecision:
    """Structured result from the preload policy engine."""

    enabled: bool
    reason: str
    source: str
    intent: str
    confidence: float = 1.0
    diagnostics: Optional[Dict[str, Any]] = None


def resolve_shortlist_intent(query_text: str) -> str:
    """Classify query intent for shortlist enablement using deterministic patterns."""
    text = str(query_text or "").lower()
    if not text:
        return INTENT_AMBIGUOUS

    has_web = any(re.search(p, text) for p in WEB_INTENT_PATTERNS)
    has_local = any(re.search(p, text) for p in LOCAL_INTENT_PATTERNS)

    if has_web and not has_local:
        return INTENT_WEB
    if has_local and not has_web:
        return INTENT_LOCAL

    return INTENT_AMBIGUOUS


class PreloadPolicyEngine:
    """Adaptive policy engine for preload shortlist decisions."""

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

    def decide(
        self,
        query_text: str,
        research_source_mode: Optional[str] = None,
    ) -> PolicyDecision:
        """Resolve adaptive shortlist enablement for local-corpus turns."""
        normalized_query = str(query_text or "").strip()

        # 1. research_source_mode=local_only always skips shortlist
        if research_source_mode == "local_only":
            return PolicyDecision(
                enabled=False,
                reason="research_source_mode_local_only",
                source=SOURCE_DETERMINISTIC,
                intent=INTENT_LOCAL,
            )

        # 2. Deterministic intent check
        intent = resolve_shortlist_intent(normalized_query)
        if intent == INTENT_WEB:
            return PolicyDecision(
                enabled=True,
                reason="deterministic_web_intent",
                source=SOURCE_DETERMINISTIC,
                intent=INTENT_WEB,
            )
        if intent == INTENT_LOCAL:
            return PolicyDecision(
                enabled=False,
                reason="deterministic_local_intent",
                source=SOURCE_DETERMINISTIC,
                intent=INTENT_LOCAL,
            )

        # 3. Fallback to interface model if available
        if self.interface_model_enabled and self.system_prompt:
            return self._decide_with_model(normalized_query)

        # 4. Final fail-safe (ambiguous + no model or no prompt)
        return PolicyDecision(
            enabled=False,
            reason="ambiguous_no_planner_fallback",
            source=SOURCE_FALLBACK,
            intent=INTENT_AMBIGUOUS,
        )

    def _decide_with_model(self, query_text: str) -> PolicyDecision:
        """Use interface model to resolve ambiguous intent."""
        model_config = MODELS.get(self.model_alias)
        model_id = str((model_config or {}).get("id", "")).strip()
        if not model_id:
            return PolicyDecision(
                enabled=False,
                reason="interface_model_config_invalid",
                source=SOURCE_FALLBACK,
                intent=INTENT_AMBIGUOUS,
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
                    "phase": "preload_policy",
                    "source": "preload_policy_engine",
                },
            )
        except requests.exceptions.RequestException as exc:
            return PolicyDecision(
                enabled=False,
                reason=f"interface_model_transport_error: {exc}",
                source=SOURCE_FALLBACK,
                intent=INTENT_AMBIGUOUS,
            )

        if not isinstance(response, dict):
            return PolicyDecision(
                enabled=False,
                reason="interface_model_invalid_response",
                source=SOURCE_FALLBACK,
                intent=INTENT_AMBIGUOUS,
            )

        content = str(response.get("content", "") or "").strip()
        payload = self._parse_payload(content)

        if not payload:
            return PolicyDecision(
                enabled=False,
                reason="interface_model_parse_failure",
                source=SOURCE_FALLBACK,
                intent=INTENT_AMBIGUOUS,
                diagnostics={"raw_content": content},
            )

        enabled = bool(payload.get("shortlist_enabled", False))
        reason = str(payload.get("reason", "") or "interface_model_decision")
        intent = str(payload.get("intent", "") or INTENT_AMBIGUOUS).lower()
        if intent not in {INTENT_WEB, INTENT_LOCAL, INTENT_AMBIGUOUS}:
            intent = INTENT_AMBIGUOUS

        return PolicyDecision(
            enabled=enabled,
            reason=reason,
            source=SOURCE_INTERFACE_MODEL,
            intent=intent,
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

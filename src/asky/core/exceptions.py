"""Core exception types for asky orchestration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class AskyError(Exception):
    """Base error for asky runtime failures."""


class ContextOverflowError(AskyError):
    """Raised when the model rejects a request due to context size constraints."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        model_alias: Optional[str] = None,
        model_id: Optional[str] = None,
        compacted_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.model_alias = model_alias
        self.model_id = model_id
        self.compacted_messages = compacted_messages or []

"""Plugin hook registry implementation."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from asky.plugins.hook_types import DEFERRED_HOOK_NAMES, SUPPORTED_HOOK_NAMES

logger = logging.getLogger(__name__)
DEFAULT_HOOK_PRIORITY = 100


@dataclass(frozen=True)
class HookRegistration:
    """One registered hook callback."""

    hook_name: str
    callback: Callable[..., Any]
    plugin_name: str
    priority: int
    registration_index: int


class HookRegistry:
    """Thread-safe ordered hook callback registry."""

    def __init__(self) -> None:
        self._callbacks: Dict[str, List[HookRegistration]] = {}
        self._lock = threading.RLock()
        self._registration_counter = 0
        self._frozen = False

    def freeze(self) -> None:
        """Disallow future registrations."""
        with self._lock:
            self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """Return whether registry has been frozen."""
        with self._lock:
            return self._frozen

    def register(
        self,
        hook_name: str,
        callback: Callable[..., Any],
        *,
        plugin_name: str,
        priority: int = DEFAULT_HOOK_PRIORITY,
    ) -> None:
        """Register one callback for a hook."""
        normalized_hook = str(hook_name or "").strip()
        if normalized_hook in DEFERRED_HOOK_NAMES:
            raise ValueError(f"Deferred hook is not supported in v1: {normalized_hook}")
        if normalized_hook not in SUPPORTED_HOOK_NAMES:
            raise ValueError(f"Unknown hook name: {normalized_hook}")
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._lock:
            if self._frozen:
                raise RuntimeError("hook registry is frozen")
            self._registration_counter += 1
            registration = HookRegistration(
                hook_name=normalized_hook,
                callback=callback,
                plugin_name=str(plugin_name or "").strip() or "unknown_plugin",
                priority=int(priority),
                registration_index=self._registration_counter,
            )
            bucket = self._callbacks.setdefault(normalized_hook, [])
            bucket.append(registration)
            bucket.sort(
                key=lambda item: (
                    item.priority,
                    item.plugin_name,
                    item.registration_index,
                )
            )

    def invoke(self, hook_name: str, payload: Any) -> Any:
        """Invoke all callbacks with mutable payload; ignore callback failures."""
        callbacks = self._snapshot(hook_name)
        for registration in callbacks:
            try:
                registration.callback(payload)
            except Exception:
                logger.exception(
                    "plugin hook callback failed hook=%s plugin=%s callback=%s",
                    registration.hook_name,
                    registration.plugin_name,
                    _qualified_name(registration.callback),
                )
        return payload

    def invoke_chain(self, hook_name: str, value: Any) -> Any:
        """Invoke chain-return callbacks in deterministic order."""
        callbacks = self._snapshot(hook_name)
        chained_value = value
        for registration in callbacks:
            try:
                candidate_value = registration.callback(chained_value)
            except Exception:
                logger.exception(
                    "plugin chain hook failed hook=%s plugin=%s callback=%s",
                    registration.hook_name,
                    registration.plugin_name,
                    _qualified_name(registration.callback),
                )
                continue
            if candidate_value is not None:
                chained_value = candidate_value
        return chained_value

    def _snapshot(self, hook_name: str) -> List[HookRegistration]:
        normalized_hook = str(hook_name or "").strip()
        with self._lock:
            return list(self._callbacks.get(normalized_hook, []))


def _qualified_name(callback: Callable[..., Any]) -> str:
    owner = getattr(callback, "__module__", "")
    name = getattr(callback, "__qualname__", repr(callback))
    if owner:
        return f"{owner}.{name}"
    return str(name)

"""Small helpers for lazy import patterns."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any


def load_module(module_name: str) -> ModuleType:
    """Import and return a module by name."""
    return import_module(module_name)


def load_attr(module_name: str, attr_name: str) -> Any:
    """Import a module and return one attribute from it."""
    module = load_module(module_name)
    return getattr(module, attr_name)


def call_attr(module_name: str, attr_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a lazily imported callable attribute."""
    func = load_attr(module_name, attr_name)
    return func(*args, **kwargs)

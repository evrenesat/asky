"""Tests for GUI server authentication."""

from __future__ import annotations

import logging
from pathlib import Path

from asky.plugins.gui_server.pages.plugin_registry import PluginPageRegistry
from asky.plugins.gui_server.server import NiceGUIServer


def test_gui_server_fails_without_password(tmp_path: Path):
    """Server start fails if no password is provided in config or env."""
    registry = PluginPageRegistry()
    server = NiceGUIServer(
        config_dir=tmp_path,
        data_dir=tmp_path,
        page_registry=registry,
        password=None,
    )
    import pytest
    with pytest.raises(RuntimeError, match="password"):
        server.start()


def test_gui_server_starts_with_password(tmp_path: Path):
    """Server start succeeds if password is provided."""
    registry = PluginPageRegistry()
    
    import threading
    started = threading.Event()
    stop = threading.Event()
    def _runner(host, port, config_dir, data_dir, page_registry, password, job_queue):
        started.set()
        stop.wait(timeout=2)

    server = NiceGUIServer(
        config_dir=tmp_path,
        data_dir=tmp_path,
        page_registry=registry,
        password="test-password",
        runner=_runner,
        shutdown=lambda: stop.set(),
    )
    server.start()
    assert started.wait(timeout=1)
    assert server.health_check()["running"]
    server.stop()
    assert not server.health_check()["running"]

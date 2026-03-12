from __future__ import annotations

import threading

from asky.plugins.hook_types import DaemonServerSpec
from asky.plugins.hooks import HookRegistry


class _Runtime:
    def __init__(self, hooks: HookRegistry):
        self.hooks = hooks

    def shutdown(self) -> None:
        return None


def test_daemon_server_register_hook_collects_servers(monkeypatch):
    from asky.plugins.hook_types import DaemonTransportSpec

    hooks = HookRegistry()

    hooks.register(
        "DAEMON_SERVER_REGISTER",
        lambda payload: payload.servers.append(
            DaemonServerSpec(name="extra", start=lambda: None, stop=lambda: None)
        ),
        plugin_name="plug",
    )
    hooks.register(
        "DAEMON_TRANSPORT_REGISTER",
        lambda payload: payload.transports.append(
            DaemonTransportSpec(name="mock", run=lambda: None, stop=lambda: None)
        ),
        plugin_name="mock_transport",
    )

    from asky.daemon import service as daemon_service

    monkeypatch.setattr(daemon_service, "init_db", lambda: None)

    service = daemon_service.DaemonService(plugin_runtime=_Runtime(hooks))
    assert any(spec.name == "extra" for spec in service._plugin_servers)


def test_daemon_runs_without_transport(monkeypatch):
    """Sidecar-only mode: no transport registered, daemon blocks on event until stop()."""
    hooks = HookRegistry()
    started = []
    stopped = []

    hooks.register(
        "DAEMON_SERVER_REGISTER",
        lambda payload: payload.servers.append(
            DaemonServerSpec(
                name="sidecar",
                start=lambda: started.append(True),
                stop=lambda: stopped.append(True),
            )
        ),
        plugin_name="plug",
    )

    from asky.daemon import service as daemon_service

    monkeypatch.setattr(daemon_service, "init_db", lambda: None)

    service = daemon_service.DaemonService(plugin_runtime=_Runtime(hooks))
    assert service._transport is None

    def _run():
        service.run_foreground()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=0.05)
    assert service._running
    service.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert started == [True]
    assert stopped == [True]

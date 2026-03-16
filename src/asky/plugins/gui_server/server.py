"""NiceGUI sidecar server for daemon plugin runtime."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from asky.daemon.job_queue import JobQueue
from asky.plugins.gui_server.pages.general_settings import mount_general_settings_page
from asky.plugins.gui_server.pages.jobs import mount_jobs_page
from asky.plugins.gui_server.pages.layout import page_layout
from asky.plugins.gui_server.pages.plugin_registry import (
    PluginPageRegistry,
    mount_plugin_registry_page,
)
from starlette.responses import RedirectResponse

logger = logging.getLogger(__name__)

DEFAULT_GUI_HOST = "127.0.0.1"
DEFAULT_GUI_PORT = 8766
SERVER_STOP_JOIN_TIMEOUT_SECONDS = 2.0
ASKY_GUI_PASSWORD_ENV = "ASKY_GUI_PASSWORD"
AUTH_EXEMPT_PATHS = frozenset({"/login", "/logout"})

_nicegui_pages_mounted = False

Runner = Callable[[str, int, Path, Path, PluginPageRegistry, str, JobQueue], None]
Shutdown = Callable[[], None]


class NiceGUIServer:
    """Manage NiceGUI lifecycle in a background thread."""

    def __init__(
        self,
        *,
        config_dir: Path,
        data_dir: Path,
        page_registry: PluginPageRegistry,
        host: str = DEFAULT_GUI_HOST,
        port: int = DEFAULT_GUI_PORT,
        password: Optional[str] = None,
        job_queue: Optional[JobQueue] = None,
        runner: Optional[Runner] = None,
        shutdown: Optional[Shutdown] = None,
    ) -> None:
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.page_registry = page_registry
        self.host = str(host or DEFAULT_GUI_HOST)
        self.port = int(port)
        self._password = password or os.environ.get(ASKY_GUI_PASSWORD_ENV)
        self._job_queue = job_queue
        self._runner = runner or _default_runner
        self._shutdown = shutdown or _default_shutdown
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start GUI server in background thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            if not self._password:
                self._last_error = (
                    "GUI password is not configured and ASKY_GUI_PASSWORD is not set. "
                    "GUI server will not start in an insecure state."
                )
                logger.error(self._last_error)
                raise RuntimeError(self._last_error)

            self._running = True
            self._last_error = None
            self._thread = threading.Thread(
                target=self._run_thread,
                name="asky-gui-server",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop GUI server if running."""
        with self._lock:
            thread = self._thread
        if thread is None:
            return

        try:
            self._shutdown()
        except Exception:
            logger.exception("GUI shutdown hook failed")

        thread.join(timeout=SERVER_STOP_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            self._running = False

    def health_check(self) -> dict[str, Any]:
        """Return basic runtime health payload."""
        thread = self._thread
        return {
            "running": bool(thread and thread.is_alive() and self._running),
            "host": self.host,
            "port": self.port,
            "error": self._last_error,
        }

    def _run_thread(self) -> None:
        try:
            self._runner(
                self.host,
                self.port,
                self.config_dir,
                self.data_dir,
                self.page_registry,
                self._password,
                self._job_queue,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            logger.exception("GUI server failed to start")
        finally:
            self._running = False


def _default_runner(
    host: str,
    port: int,
    config_dir: Path,
    data_dir: Path,
    page_registry: PluginPageRegistry,
    password: str,
    job_queue: JobQueue,
) -> None:
    global _nicegui_pages_mounted
    import os
    os.environ["NICEGUI_STORAGE_PATH"] = str((data_dir / ".nicegui").absolute())
    from nicegui import app, ui
    import nicegui.core as core

    if _nicegui_pages_mounted:
        if getattr(core.app, "middleware_stack", None) is not None:
            core.app.middleware_stack = None
        if isinstance(getattr(core.app, "middleware", None), list):
            core.app.middleware.clear()
    else:

        @ui.page("/login")
        def login() -> Optional[None]:
            def try_login() -> None:
                if password_input.value == password:
                    app.storage.user.update({"authenticated": True})
                    ui.navigate.to(app.storage.user.get("referrer", "/"))
                else:
                    ui.notify("Wrong password", color="negative")

            if app.storage.user.get("authenticated", False):
                return ui.navigate.to("/")
            
            with page_layout("Login", show_nav=False):
                with ui.card().classes("fixed-center w-80 asky-card"):
                    ui.label("Authentication Required").classes("text-lg font-semibold mb-2")
                    password_input = ui.input("Password", password=True).classes("w-full")
                    password_input.on("keydown.enter", try_login)
                    ui.button("Login", on_click=try_login).classes("w-full mt-4")
            return None

        @ui.page("/logout")
        def logout() -> None:
            app.storage.user.update({"authenticated": False})
            ui.navigate.to("/login")

        @ui.page("/")
        def index() -> None:
            if not app.storage.user.get("authenticated", False):
                app.storage.user["referrer"] = "/"
                return ui.navigate.to("/login")
            with page_layout("Dashboard"):
                ui.label("Welcome to asky admin console.")
                with ui.row().classes("gap-4"):
                    with ui.card().classes("asky-card"):
                        ui.label("Plugins").classes("text-xl font-bold")
                        ui.label(f"{len(page_registry.list_pages())} extensions registered")
                        ui.button("View Plugins", on_click=lambda: ui.navigate.to("/plugins")).props("outline")
                    with ui.card().classes("asky-card"):
                        ui.label("Settings").classes("text-xl font-bold")
                        ui.label("Daemon and general configuration")
                        ui.button("Open Settings", on_click=lambda: ui.navigate.to("/settings/general")).props("outline")
            return None

        # Wrap existing page mounting with auth check
        def auth_wrapper(mount_fn: Callable[..., None], **kwargs: Any) -> None:
            orig_mount = mount_fn
            
            # Since mount_fn defines the @ui.page internal function, we can't easily wrap it 
            # after it's been called. We need to modify the mount functions themselves 
            # or rely on the fact that they are called once.
            # Actually, for this milestone, we'll manually add the auth check to the pages 
            # or use a global request interceptor if NiceGUI supports it.
            pass

    if _nicegui_pages_mounted:
        if getattr(core.app, "middleware_stack", None) is not None:
            core.app.middleware_stack = None
        if isinstance(getattr(core.app, "middleware", None), list):
            core.app.middleware.clear()
            # Since we cleared it, re-add our auth middleware if needed
            if hasattr(app, "_auth_middleware_added"):
                delattr(app, "_auth_middleware_added")

    # Re-check/re-add auth middleware if it was cleared or never added
    if not hasattr(app, "_auth_middleware_added"):
        @app.middleware("http")
        async def auth_middleware(request, call_next):
            if not app.storage.user.get("authenticated", False):
                if request.url.path not in AUTH_EXEMPT_PATHS and not request.url.path.startswith("/_nicegui"):
                    app.storage.user["referrer"] = request.url.path
                    return RedirectResponse("/login")
            return await call_next(request)
        app._auth_middleware_added = True

    if not _nicegui_pages_mounted:

        @ui.page("/login")
        def login() -> Optional[None]:
            def try_login() -> None:
                if password_input.value == password:
                    app.storage.user.update({"authenticated": True})
                    ui.navigate.to(app.storage.user.get("referrer", "/"))
                else:
                    ui.notify("Wrong password", color="negative")

            if app.storage.user.get("authenticated", False):
                return ui.navigate.to("/")
            
            with page_layout("Login", show_nav=False):
                with ui.card().classes("fixed-center w-80 asky-card"):
                    ui.label("Authentication Required").classes("text-lg font-semibold mb-2")
                    password_input = ui.input("Password", password=True).classes("w-full")
                    password_input.on("keydown.enter", try_login)
                    ui.button("Login", on_click=try_login).classes("w-full mt-4")
            return None

        @ui.page("/logout")
        def logout() -> None:
            app.storage.user.update({"authenticated": False})
            ui.navigate.to("/login")

        @ui.page("/")
        def index() -> None:
            if not app.storage.user.get("authenticated", False):
                app.storage.user["referrer"] = "/"
                return ui.navigate.to("/login")
            with page_layout("Dashboard"):
                ui.label("Welcome to asky admin console.")
                with ui.row().classes("gap-4"):
                    with ui.card().classes("asky-card"):
                        ui.label("Plugins").classes("text-xl font-bold")
                        ui.label(f"{len(page_registry.list_pages())} extensions registered")
                        ui.button("View Plugins", on_click=lambda: ui.navigate.to("/plugins")).props("outline")
                    with ui.card().classes("asky-card"):
                        ui.label("Settings").classes("text-xl font-bold")
                        ui.label("Daemon and general configuration")
                        ui.button("Open Settings", on_click=lambda: ui.navigate.to("/settings/general")).props("outline")
            return None

        mount_general_settings_page(ui, config_dir=config_dir)
        mount_jobs_page(ui, job_queue)
        mount_plugin_registry_page(ui, page_registry)
        page_registry.mount_pages(ui)
        _nicegui_pages_mounted = True

    ui.run(
        host=host,
        port=port,
        show=False,
        reload=False,
        title="Asky GUI",
        storage_secret="asky-secret-change-me-in-production", # We should probably derive this from password
    )


def _default_shutdown() -> None:
    try:
        from nicegui import app

        app.shutdown()
    except Exception:
        logger.debug("NiceGUI app shutdown unavailable", exc_info=True)

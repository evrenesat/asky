"""Session management and persona binding pages."""

from __future__ import annotations

from typing import Any

from nicegui import ui
from asky.plugins.gui_server.pages.layout import page_layout
from asky.plugins.persona_manager.gui_service import list_sessions_with_bindings, bind_persona_to_session
from asky.plugins.manual_persona_creator.storage import list_persona_names


from asky.plugins.hook_types import GUIPageSpec


def register_session_pages(register_page: Any, data_dir: Any) -> None:
    """Register session list and binding pages."""

    def _session_list_page(ui: Any) -> None:
        sessions = list_sessions_with_bindings(data_dir)
        personas = list_persona_names(data_dir)

        if not sessions:
            ui.label("No sessions found.").classes("text-slate-500 italic")
            return

        with ui.card().classes("w-full asky-card p-0"):
            with ui.element("table").classes("asky-table"):
                with ui.element("thead"):
                    with ui.element("tr"):
                        with ui.element("th"):
                            ui.label("ID")
                        with ui.element("th"):
                            ui.label("Name")
                        with ui.element("th"):
                            ui.label("Model")
                        with ui.element("th"):
                            ui.label("Persona Binding")

                with ui.element("tbody"):
                    for s in sessions:
                        with ui.element("tr"):
                            with ui.element("td"):
                                ui.label(str(s["id"]))
                            with ui.element("td"):
                                ui.label(s["name"] or "Untitled")
                            with ui.element("td"):
                                ui.label(s["model"])
                            with ui.element("td"):
                                options = ["(None)"] + personas
                                current = s["persona_binding"] or "(None)"

                                def _on_change(val, sid=s["id"]):
                                    pname = None if val == "(None)" else val
                                    bind_persona_to_session(data_dir, sid, pname)
                                    ui.notify(f"Session {sid} bound to {val}")

                                ui.select(
                                    options,
                                    value=current,
                                    on_change=lambda e, sid=s["id"]: _on_change(e.value, sid),
                                ).props("dense outlined")

    register_page(
        GUIPageSpec(
            route="/sessions",
            title="Sessions",
            render=_session_list_page,
            nav_title="Sessions",
        )
    )

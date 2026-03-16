"""Web collection review and intake pages."""

from __future__ import annotations

from typing import Any

from nicegui import ui
from asky.plugins.gui_server.pages.layout import page_layout
from asky.plugins.manual_persona_creator.web_service import (
    get_collection_review_pages,
    approve_web_page,
    reject_web_page,
    intake_url,
)


from asky.plugins.hook_types import GUIPageSpec


def register_web_review_pages(register_page: Any, data_dir: Any) -> None:
    """Register web collection review and intake pages."""

    def _web_collection_page(ui: Any, collection_id: str) -> None:
        from asky.plugins.manual_persona_creator.storage import (
            get_persona_paths,
            list_persona_names,
            list_web_collections,
        )

        persona_name = None
        for p in list_persona_names(data_dir):
            paths = get_persona_paths(data_dir, p)
            if collection_id in list_web_collections(paths.root_dir):
                persona_name = p
                break

        if not persona_name:
            ui.label("Collection not found.").classes("text-red-600")
            return

        pages = get_collection_review_pages(
            data_dir=data_dir, persona_name=persona_name, collection_id=collection_id
        )

        if not pages:
            ui.label("No pages found in this collection.").classes("italic")
            return

        with ui.card().classes("w-full asky-card p-0"):
            with ui.element("table").classes("asky-table"):
                with ui.element("thead"):
                    with ui.element("tr"):
                        with ui.element("th"):
                            ui.label("Title")
                        with ui.element("th"):
                            ui.label("URL")
                        with ui.element("th"):
                            ui.label("Status")
                        with ui.element("th"):
                            ui.label("Actions")

                with ui.element("tbody"):
                    for p in pages:
                        with ui.element("tr"):
                            with ui.element("td"):
                                ui.label(p.get("title") or "No title")
                            with ui.element("td"):
                                ui.label(p["final_url"])
                            with ui.element("td"):
                                status = p["status"]
                                cls = (
                                    "asky-status-info"
                                    if status == "review_ready"
                                    else "asky-status-success"
                                    if status == "approved"
                                    else "asky-status-error"
                                )
                                ui.label(status).classes(f"asky-status-badge {cls}")
                            with ui.element("td"):
                                with ui.row().classes("gap-2"):
                                    ui.button(
                                        icon="visibility",
                                        on_click=lambda p=p: ui.navigate.to(
                                            f"/web-review/{collection_id}/{p['page_id']}"
                                        ),
                                    ).props("flat dense")
                                    if status == "review_ready":
                                        ui.button(
                                            icon="check",
                                            on_click=lambda p=p: _approve(
                                                ui, persona_name, collection_id, p["page_id"]
                                            ),
                                        ).props("flat dense color=positive")
                                        ui.button(
                                            icon="close",
                                            on_click=lambda p=p: _reject(
                                                ui, persona_name, collection_id, p["page_id"]
                                            ),
                                        ).props("flat dense color=negative")

    register_page(
        GUIPageSpec(
            route="/web-review/{collection_id}",
            title="Web Review: {collection_id}",
            render=_web_collection_page,
        )
    )

    def _approve(ui, pname, cid, pid):
        approve_web_page(data_dir=data_dir, persona_name=pname, collection_id=cid, page_id=pid)
        ui.notify(f"Approved {pid}")
        ui.navigate.reload()

    def _reject(ui, pname, cid, pid):
        reject_web_page(data_dir=data_dir, persona_name=pname, collection_id=cid, page_id=pid)
        ui.notify(f"Rejected {pid}")
        ui.navigate.reload()

    def _web_page_detail(ui: Any, collection_id: str, page_id: str) -> None:
        from asky.plugins.manual_persona_creator.storage import (
            get_persona_paths,
            get_web_collection_paths,
            get_web_page_paths,
            list_persona_names,
            list_web_collections,
        )

        persona_name = None
        for p in list_persona_names(data_dir):
            paths = get_persona_paths(data_dir, p)
            if collection_id in list_web_collections(paths.root_dir):
                persona_name = p
                break

        if not persona_name:
            ui.label("Not found")
            return

        c_paths = get_web_collection_paths(
            get_persona_paths(data_dir, persona_name).root_dir, collection_id
        )
        p_paths = get_web_page_paths(c_paths.collection_dir, page_id)

        import tomllib

        with p_paths.manifest_path.open("rb") as f:
            manifest = tomllib.load(f)

        import json

        preview = {}
        if p_paths.preview_path.exists():
            preview = json.loads(p_paths.preview_path.read_text(encoding="utf-8"))

        with ui.row().classes("w-full justify-between items-center"):
            ui.link(manifest["final_url"], manifest["final_url"], new_tab=True)
            with ui.row().classes("gap-2"):
                ui.button(
                    "Approve as Authored",
                    on_click=lambda: _approve_ext(ui, persona_name, collection_id, page_id, "authored"),
                ).props("color=positive")
                ui.button(
                    "Approve as About",
                    on_click=lambda: _approve_ext(ui, persona_name, collection_id, page_id, "about"),
                ).props("color=secondary")
                ui.button(
                    "Reject", on_click=lambda: _reject(ui, persona_name, collection_id, page_id)
                ).props("color=negative outline")

        with ui.card().classes("w-full asky-card"):
            ui.label("Classification").classes("text-sm font-semibold text-slate-500 uppercase")
            ui.label(manifest.get("classification", "uncertain")).classes("text-lg mb-4")

            if preview:
                ui.label("Extracted Viewpoints").classes(
                    "text-sm font-semibold text-slate-500 uppercase"
                )
                for vp in preview.get("candidate_viewpoints", []):
                    with ui.card().classes("bg-blue-50 p-2 mb-2"):
                        ui.label(vp.get("viewpoint")).classes("font-bold")
                        ui.label(vp.get("evidence")).classes("text-sm italic")

        with ui.card().classes("w-full asky-card"):
            ui.label("Content").classes("text-sm font-semibold text-slate-500 uppercase")
            ui.markdown(
                p_paths.content_path.read_text(encoding="utf-8")[:2000] + "..."
            ).classes("text-sm")

    register_page(
        GUIPageSpec(
            route="/web-review/{collection_id}/{page_id}",
            title="Review Page: {page_id}",
            render=_web_page_detail,
        )
    )

    def _approve_ext(ui, pname, cid, pid, trust):
        approve_web_page(
            data_dir=data_dir, persona_name=pname, collection_id=cid, page_id=pid, trust_as=trust
        )
        ui.notify(f"Approved {pid} as {trust}")
        ui.navigate.to(f"/web-review/{cid}")

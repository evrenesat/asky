"""Persona management pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from asky.daemon.job_queue import JobQueue
from asky.plugins.gui_server.pages.layout import page_layout
from asky.plugins.manual_persona_creator.gui_service import (
    get_persona_detail,
    list_personas_summary,
)
from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind
from asky.plugins.manual_persona_creator.creation_service import (
    PersonaCreationSpecs,
    StagedSourceSpec,
    create_persona_from_scratch,
)
from asky.plugins.manual_persona_creator.book_types import BookMetadata, ExtractionTargets
from asky.plugins.hook_types import GUIPageSpec
from asky.plugins.manual_persona_creator.feature_docs import load_topic


def _field_help(ui: Any, topic_id: str):
    """Render a help icon that opens a dialog with the specified topic."""

    def show_help():
        try:
            topic = load_topic(topic_id)
        except Exception as e:
            ui.notify(str(e), type="negative")
            return

        with ui.dialog() as d, ui.card().classes("w-[600px]"):
            ui.label(topic.title).classes("text-lg font-bold")
            ui.separator()
            ui.markdown(topic.body).classes("mt-4")
            with ui.row().classes("w-full justify-end mt-4"):
                ui.button("Close", on_click=d.close).props("flat")
        d.open()

    ui.button(on_click=show_help, icon="help_outline").props(
        "flat round dense size=sm"
    ).classes("text-slate-400")


def register_persona_pages(register_page: Any, data_dir: Any, queue: JobQueue) -> None:
    """Register persona list and detail pages."""

    def _persona_list_page(ui: Any) -> None:
        summaries = list_personas_summary(data_dir)

        with ui.row().classes("w-full justify-between items-center mb-6"):
            ui.label("Your Personas").classes("text-h4")
            ui.button(
                "New Persona",
                icon="add",
                on_click=lambda: ui.navigate.to("/personas/new"),
            ).props("color=primary")

        if not summaries:
            ui.label("No personas found.").classes("text-slate-500 italic")
            return

        with ui.row().classes("w-full gap-6"):
            for p in summaries:
                with ui.card().classes("w-80 asky-card cursor-pointer").on(
                    "click", lambda p=p: ui.navigate.to(f"/personas/{p.name}")
                ):
                    ui.label(p.name).classes("text-xl font-bold")
                    ui.label(p.description).classes("text-sm text-slate-600 line-clamp-2")
                    ui.separator().classes("my-2")
                    with ui.row().classes("gap-4 text-xs font-mono text-slate-500"):
                        ui.label(f"Books: {p.book_count}")
                        ui.label(f"Sources: {p.source_count}")
                        ui.label(f"Web: {p.web_collection_count}")

    register_page(
        GUIPageSpec(
            route="/personas",
            title="Personas",
            render=_persona_list_page,
            nav_title="Personas",
        )
    )

    def _persona_detail_page(ui: Any, name: str) -> None:
        try:
            detail = get_persona_detail(data_dir, name)
        except Exception as exc:
            ui.label(str(exc)).classes("text-red-600")
            return

        with ui.tabs().classes("w-full") as tabs:
            one = ui.tab("Overview")
            two = ui.tab("Authored Books")
            three = ui.tab("Knowledge Sources")
            four = ui.tab("Web Collections")

        with ui.tab_panels(tabs, value=one).classes("w-full bg-transparent"):
            with ui.tab_panel(one):
                with ui.card().classes("asky-card"):
                    ui.label("Description").classes(
                        "text-sm font-semibold text-slate-500 uppercase"
                    )
                    ui.label(
                        detail["metadata"].get("persona", {}).get("description", "No description")
                    ).classes("text-lg mb-4")

                    ui.label("Behavior Prompt").classes(
                        "text-sm font-semibold text-slate-500 uppercase"
                    )
                    ui.markdown(
                        f"```markdown\n{detail.get('behavior_prompt', 'No prompt')[:500]}...\n```"
                    ).classes("bg-slate-50 p-2 rounded")

            with ui.tab_panel(two):
                with ui.row().classes("w-full justify-end mb-4"):
                    ui.button(
                        "Add Authored Book",
                        icon="add",
                        on_click=lambda: _add_authored_book_dialog(ui, name, data_dir, queue),
                    ).props("outline")

                books = detail["books"]
                if not books:
                    ui.label("No authored books ingested.").classes("italic")
                else:
                    with ui.element("table").classes("asky-table"):
                        with ui.element("thead"):
                            with ui.element("tr"):
                                with ui.element("th"):
                                    ui.label("Title")
                                with ui.element("th"):
                                    ui.label("Author")
                                with ui.element("th"):
                                    ui.label("Year")
                                with ui.element("th"):
                                    ui.label("Viewpoints")
                        with ui.element("tbody"):
                            for b in books:
                                with ui.element("tr"):
                                    with ui.element("td"):
                                        ui.label(b["title"])
                                    with ui.element("td"):
                                        ui.label(", ".join(b["authors"]))
                                    with ui.element("td"):
                                        ui.label(str(b["publication_year"]))
                                    with ui.element("td"):
                                        ui.label(str(b["viewpoint_count"]))

            with ui.tab_panel(three):
                with ui.row().classes("w-full justify-end mb-4"):
                    ui.button(
                        "Add Knowledge Source",
                        icon="add",
                        on_click=lambda: _add_source_dialog(ui, name, data_dir, queue),
                    ).props("outline")

                sources = detail["approved_sources"] + detail["pending_sources"]
                if not sources:
                    ui.label("No knowledge sources found.").classes("italic")
                else:
                    with ui.element("table").classes("asky-table"):
                        with ui.element("thead"):
                            with ui.element("tr"):
                                with ui.element("th"):
                                    ui.label("Label")
                                with ui.element("th"):
                                    ui.label("Kind")
                                with ui.element("th"):
                                    ui.label("Status")
                        with ui.element("tbody"):
                            for s in sources:
                                with ui.element("tr"):
                                    with ui.element("td"):
                                        ui.label(s["label"])
                                    with ui.element("td"):
                                        ui.label(s["kind"])
                                    with ui.element("td"):
                                        cls = (
                                            "asky-status-success"
                                            if s["review_status"] == "approved"
                                            else "asky-status-warning"
                                        )
                                        ui.label(s["review_status"]).classes(
                                            f"asky-status-badge {cls}"
                                        )

            with ui.tab_panel(four):
                with ui.row().classes("w-full justify-end mb-4"):
                    ui.button(
                        "Add URL",
                        icon="link",
                        on_click=lambda: _add_url_dialog(ui, name, data_dir),
                    ).props("outline")

                collections = detail["web_collections"]
                if not collections:
                    ui.label("No web collections found.").classes("italic")
                else:
                    with ui.column().classes("gap-2"):
                        for c in collections:
                            with ui.card().classes("w-full asky-card cursor-pointer").on(
                                "click",
                                lambda c=c: ui.navigate.to(f"/web-review/{c['collection_id']}"),
                            ):
                                with ui.row().classes("w-full justify-between items-center"):
                                    ui.label(f"Collection: {c['collection_id']}").classes(
                                        "font-mono font-bold"
                                    )
                                    ui.button("Review", icon="visibility").props("flat")

    register_page(
        GUIPageSpec(
            route="/personas/{name}",
            title="Persona: {name}",
            render=_persona_detail_page,
        )
    )

    def _new_persona_page(ui: Any) -> None:
        staged_sources: List[StagedSourceSpec] = []

        with ui.column().classes("gap-6"):
            ui.label("Create New Persona").classes("text-h4 mb-4")

            with ui.card().classes("w-full asky-card p-6"):
                # Basic Info
                try:
                    create_topic = load_topic("create-persona")
                except Exception:
                    create_topic = None

                with ui.row().classes("w-full items-center"):
                    with ui.column().classes("flex-grow"):
                        name_input = (
                            ui.input("Persona Name", placeholder="e.g. detective-smith")
                            .classes("w-full")
                            .props("outlined")
                        )
                        if create_topic and "persona_name" in create_topic.fields:
                            ui.label(create_topic.fields["persona_name"]).classes("text-xs text-slate-500 mt-1 ml-1")
                    _field_help(ui, "create-persona")

                desc_input = (
                    ui.input("Description").classes("w-full mt-4").props("outlined")
                )

                with ui.column().classes("w-full mt-6"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Behavior Prompt").classes("text-lg font-semibold")
                        _field_help(ui, "create-persona")
                    prompt_input = (
                        ui.textarea("Enter markdown behavior definition...")
                        .classes("w-full h-48 font-mono text-sm")
                        .props("outlined")
                    )
                    if create_topic and "behavior_prompt" in create_topic.fields:
                        ui.label(create_topic.fields["behavior_prompt"]).classes("text-xs text-slate-500 mt-1 ml-1")

            # Initial Sources
            with ui.card().classes("w-full asky-card p-6"):
                ui.label("Initial Knowledge Sources").classes("text-lg font-semibold mb-2")
                if create_topic and "initial_sources" in create_topic.fields:
                    ui.label(create_topic.fields["initial_sources"]).classes("text-sm text-slate-500 mb-4")
                else:
                    ui.label(
                        "At least one source is required to ground the persona's knowledge."
                    ).classes("text-sm text-slate-500 mb-4")

                sources_col = ui.column().classes("w-full gap-2 mb-6")

                def refresh_sources_list():
                    sources_col.clear()
                    if not staged_sources:
                        with sources_col:
                            ui.label(
                                "No sources staged yet. Use the buttons below to add."
                            ).classes("italic text-slate-500")
                        return

                    for i, s in enumerate(staged_sources):
                        with sources_col, ui.card().classes("w-full p-3 bg-slate-50"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-3"):
                                    icon = (
                                        "book"
                                        if s.kind == "authored_book"
                                        else "article"
                                    )
                                    ui.icon(icon).classes("text-slate-400")
                                    with ui.column().classes("gap-0"):
                                        ui.label(Path(s.path).name).classes(
                                            "font-bold text-sm"
                                        )
                                        ui.label(str(s.kind)).classes(
                                            "text-xs text-slate-500"
                                        )
                                ui.button(
                                    icon="delete",
                                    on_click=lambda i=i: remove_source(i),
                                ).props("flat round dense color=red")

                def remove_source(index):
                    staged_sources.pop(index)
                    refresh_sources_list()

                refresh_sources_list()

                with ui.row().classes("gap-4"):
                    ui.button(
                        "Stage Authored Book",
                        icon="book",
                        on_click=lambda: _stage_book_dialog(
                            ui, staged_sources, refresh_sources_list, data_dir, name_input.value
                        ),
                    ).props("outline")
                    ui.button(
                        "Stage Manual Source",
                        icon="article",
                        on_click=lambda: _stage_manual_source_dialog(
                            ui, staged_sources, refresh_sources_list
                        ),
                    ).props("outline")

            # Submit
            with ui.row().classes("w-full justify-end mt-4"):
                ui.button("Cancel", on_click=lambda: ui.navigate.to("/personas")).props(
                    "flat"
                )
                ui.button(
                    "SUBMIT PERSONA",
                    icon="check",
                    on_click=lambda: _submit_persona(),
                ).props("color=primary size=lg")

        def _submit_persona():
            if not name_input.value:
                ui.notify("Persona Name is required", type="warning")
                return
            if not prompt_input.value:
                ui.notify("Behavior Prompt is required", type="warning")
                return
            if not staged_sources:
                ui.notify("At least one initial source is required", type="warning")
                return

            specs = PersonaCreationSpecs(
                name=name_input.value,
                description=desc_input.value,
                behavior_prompt=prompt_input.value,
                initial_sources=list(staged_sources),
            )
            try:
                name, created_jobs = create_persona_from_scratch(data_dir, specs)
                
                # Enqueue all created jobs
                for job in created_jobs:
                    queue.enqueue(job.kind, job.job_id, persona_name=name)
                
                ui.notify(f"Persona '{name}' created and {len(created_jobs)} jobs enqueued!", type="positive")
                ui.navigate.to(f"/personas/{name}")
            except Exception as e:
                ui.notify(f"Creation failed: {e}", type="negative")

    register_page(
        GUIPageSpec(
            route="/personas/new",
            title="Create Persona",
            render=_new_persona_page,
            nav_title="New Persona",
        )
    )


def _add_authored_book_dialog(ui, name, data_dir, queue):
    from asky.plugins.manual_persona_creator.book_service import prepare_ingestion_preflight
    from asky.plugins.manual_persona_creator.book_types import BookMetadata, ExtractionTargets
    from asky.plugins.manual_persona_creator.gui_service import (
        from_preflight_result,
        submit_authored_book,
        validate_authored_book_input,
    )

    with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-2xl"):
        ui.label("Add Authored Book").classes("text-h6 mb-4")

        # Stage 1: Path Input
        path_container = ui.column().classes("w-full gap-4")
        with path_container:
            path_input = ui.input("Local Path to Book").classes("w-full").props("outlined")
            ui.label("Path must be a local text or markdown file visible to the daemon.").classes(
                "text-xs text-slate-500"
            )

        # Stage 2: Results & Metadata (initially hidden)
        results_container = ui.column().classes("w-full gap-4").hide()

        # State vars - using a dict so closures can mutate them if needed
        state = {
            "preflight_dto": None,
            "preflight_result": None,
        }

        def _on_preflight():
            path = path_input.value
            if not path:
                ui.notify("Path is required", type="warning")
                return

            try:
                result = prepare_ingestion_preflight(
                    data_dir=data_dir, persona_name=name, source_path=path
                )
                state["preflight_result"] = result
                state["preflight_dto"] = from_preflight_result(result)
                _show_results(state["preflight_dto"])
            except Exception as e:
                ui.notify(f"Preflight failed: {e}", type="negative")

        def _show_results(dto):
            path_container.hide()
            results_container.show()
            results_container.clear()
            preflight_btn.hide()

            with results_container:
                if dto.is_duplicate:
                    ui.label("Duplicate Detected").classes("text-red-600 font-bold")
                    ui.label(
                        f"This book matches an existing record: {dto.existing_book_key}"
                    ).classes("text-sm")
                    ui.button("Back", on_click=_reset).props("flat")
                    return

                if dto.resumable_job_id:
                    ui.label("Resumable Job Found").classes("text-amber-600 font-bold")
                    ui.label(
                        f"A previous ingestion attempt for this file exists (Job {dto.resumable_job_id}). Continuing will update and resume it."
                    ).classes("text-sm")

                # Normal case: New Job or Resume (both show form)
                _render_authored_book_form(dto)

        def _render_authored_book_form(dto):
            with results_container:
                ui.label("Book Analysis").classes("text-sm font-semibold uppercase text-slate-500")
                with ui.row().classes("gap-4 text-xs"):
                    ui.label(f"Words: {state['preflight_result'].stats['word_count']}")
                    ui.label(f"Sections: {state['preflight_result'].stats['section_count']}")

                ui.separator()

                # Metadata form
                title_input = (
                    ui.input("Title", value=dto.title if dto.title else "")
                    .classes("w-full")
                    .props("outlined dense")
                )
                authors_input = (
                    ui.input("Authors", value=", ".join(dto.authors) if dto.authors else "")
                    .classes("w-full")
                    .props("outlined dense")
                )
                year_input = (
                    ui.number("Year", value=dto.publication_year)
                    .classes("w-24")
                    .props("outlined dense")
                )
                isbn_input = (
                    ui.input("ISBN", value=dto.isbn if dto.isbn else "").classes("w-40").props("outlined dense")
                )

                ui.separator()

                with ui.row().classes("w-full gap-4"):
                    topic_input = (
                        ui.number("Topic Target", value=dto.topic_target)
                        .props("outlined dense")
                        .classes("flex-1")
                    )
                    vp_input = (
                        ui.number("Viewpoint Target", value=dto.viewpoint_target)
                        .props("outlined dense")
                        .classes("flex-1")
                    )

                with ui.row().classes("w-full justify-end mt-4"):
                    ui.button("Back", on_click=_reset).props("flat")
                    ui.button(
                        "Start Ingestion" if not dto.resumable_job_id else "Resume Ingestion",
                        on_click=lambda: _on_submit(
                            title_input.value,
                            authors_input.value.split(","),
                            year_input.value,
                            isbn_input.value,
                            int(topic_input.value) if topic_input.value else 0,
                            int(vp_input.value) if vp_input.value else 0,
                        ),
                    ).props("color=primary")

        def _reset():
            path_container.show()
            results_container.hide()
            results_container.clear()
            preflight_btn.show()

        def _on_submit(title, authors, year, isbn, topics, viewpts):
            dto = state["preflight_dto"]
            metadata = BookMetadata(
                title=title,
                authors=[a.strip() for a in authors if a.strip()],
                publication_year=int(year) if year else None,
                isbn=isbn if isbn else None,
            )
            targets = ExtractionTargets(topic_target=topics, viewpoint_target=viewpts)

            errors = validate_authored_book_input(metadata, targets)
            if errors:
                for error in errors:
                    ui.notify(error, type="negative")
                return

            try:
                job_id = submit_authored_book(
                    data_dir=data_dir,
                    persona_name=name,
                    dto=dto,
                    metadata=metadata,
                    targets=targets,
                )
                _queue_ingestion(ui, name, job_id, queue)
                dialog.close()
            except Exception as e:
                ui.notify(f"Submit failed: {e}", type="negative")

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            preflight_btn = ui.button("Preflight", on_click=_on_preflight)

    dialog.open()


def _queue_ingestion(ui, name, job_id, queue):
    queue.enqueue("authored_book_ingest", job_id, persona_name=name)
    ui.notify(f"Enqueued authored book ingestion: {job_id}")


def _add_source_dialog(ui: Any, persona_name: str, data_dir: Any, queue: JobQueue) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(f"Add Source to {persona_name}").classes("text-lg font-bold")
        path_input = ui.input("File or Directory Path").classes("w-full")
        kind_select = (
            ui.select(
                ["article", "interview", "biography", "autobiography", "essay", "speech", "notes", "posts"],
                value="article",
                label="Kind",
            )
            .classes("w-full")
        )
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button(
                "Queue Ingest",
                on_click=lambda: _queue_source(
                    ui, data_dir, queue, persona_name, path_input.value, kind_select.value, dialog
                ),
            ).props("primary")
    dialog.open()


def _queue_source(ui, data_dir, queue, pname: str, path: str, kind: str, dialog: Any) -> None:
    if not path:
        ui.notify("Path is required", color="negative")
        return

    from asky.plugins.manual_persona_creator.source_service import create_source_ingestion_job
    from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind

    try:
        job_id = create_source_ingestion_job(
            data_dir=data_dir,
            persona_name=pname,
            kind=PersonaSourceKind(kind),
            source_path=Path(path),
        )
        queue.enqueue("source_ingest", job_id, persona_name=pname)
        ui.notify(f"Enqueued source ingestion: {job_id}")
        dialog.close()
    except Exception as exc:
        ui.notify(str(exc), color="negative")


def _add_url_dialog(ui: Any, persona_name: str, data_dir: Any) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(f"Web Intake for {persona_name}").classes("text-lg font-bold")
        url_input = ui.input("URL").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button(
                "Intake", on_click=lambda: _do_intake(ui, data_dir, persona_name, url_input.value, dialog)
            ).props("primary")
    dialog.open()


def _do_intake(ui: Any, data_dir, pname: str, url: str, dialog: Any) -> None:
    if not url:
        ui.notify("URL is required", color="negative")
        return

    from asky.plugins.manual_persona_creator.web_service import intake_url

    try:
        collection_id = intake_url(data_dir=data_dir, persona_name=pname, url=url)
        ui.notify(f"Created web collection: {collection_id}")
        dialog.close()
        ui.navigate.to(f"/web-review/{collection_id}")
    except Exception as exc:
        ui.notify(str(exc), color="negative")


def _stage_book_dialog(ui, staged_list: list, refresh_fn, data_dir, persona_name: Optional[str] = None):
    from asky.plugins.manual_persona_creator.book_service import (
        prepare_ingestion_preflight,
    )
    from asky.plugins.manual_persona_creator.book_types import (
        BookMetadata,
        ExtractionTargets,
    )
    from asky.plugins.manual_persona_creator.gui_service import (
        from_preflight_result,
        validate_authored_book_input,
    )
    from asky.plugins.manual_persona_creator import storage

    with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-2xl"):
        ui.label("Stage Authored Book").classes("text-h6 mb-4")

        # Stage 1: Path Input
        path_container = ui.column().classes("w-full gap-4")
        with path_container:
            path_input = (
                ui.input("Local Path to Book").classes("w-full").props("outlined")
            )
            ui.label(
                "Path must be a local text or markdown file visible to the daemon."
            ).classes("text-xs text-slate-500")

        # Stage 2: Results & Metadata
        results_container = ui.column().classes("w-full gap-4").hide()

        state = {
            "preflight_dto": None,
            "preflight_result": None,
        }

        def _on_preflight():
            path = path_input.value
            if not path:
                ui.notify("Path is required", type="warning")
                return

            if not persona_name:
                ui.notify("Persona Name is required before staging a book", type="warning")
                return

            try:
                storage.validate_persona_name(persona_name)
            except ValueError as e:
                ui.notify(f"Invalid persona name: {e}", type="warning")
                return

            try:
                result = prepare_ingestion_preflight(
                    data_dir=data_dir,
                    persona_name=persona_name,
                    source_path=path
                )
                state["preflight_result"] = result
                state["preflight_dto"] = from_preflight_result(result)
                _show_results(state["preflight_dto"])
            except Exception as e:
                ui.notify(f"Preflight failed: {e}", type="negative")

        def _show_results(dto):
            path_container.hide()
            results_container.show()
            results_container.clear()
            preflight_btn.hide()

            with results_container:
                if dto.is_duplicate:
                    ui.label("Duplicate Detected").classes("text-red-600 font-bold")
                    ui.label(
                        f"This book matches an existing record: {dto.existing_book_key}"
                    ).classes("text-sm")
                    ui.button("Back", on_click=_reset).props("flat")
                    return

                if dto.resumable_job_id:
                    ui.label("Resumable Job Found").classes("text-amber-600 font-bold")
                    ui.label(
                        f"A previous ingestion attempt for this file exists (Job {dto.resumable_job_id}). Continuing will update and resume it."
                    ).classes("text-sm")

                # Normal case: New Job or Resume (both show form)
                _render_authored_book_form(dto)

        def _render_authored_book_form(dto):
            with results_container:
                with ui.row().classes("gap-4 text-xs"):
                    ui.label(f"Words: {state['preflight_result'].stats['word_count']}")
                    ui.label(
                        f"Sections: {state['preflight_result'].stats['section_count']}"
                    )

                ui.separator()

                title_input = (
                    ui.input("Title", value=dto.title if dto.title else "")
                    .classes("w-full")
                    .props("outlined dense")
                )
                authors_input = (
                    ui.input(
                        "Authors", value=", ".join(dto.authors) if dto.authors else ""
                    )
                    .classes("w-full")
                    .props("outlined dense")
                )
                year_input = (
                    ui.number("Year", value=dto.publication_year)
                    .classes("w-24")
                    .props("outlined dense")
                )
                isbn_input = (
                    ui.input("ISBN", value=dto.isbn if dto.isbn else "")
                    .classes("w-40")
                    .props("outlined dense")
                )

                ui.separator()

                with ui.row().classes("w-full gap-4"):
                    topic_input = (
                        ui.number("Topic Target", value=dto.topic_target)
                        .props("outlined dense")
                        .classes("flex-1")
                    )
                    vp_input = (
                        ui.number("Viewpoint Target", value=dto.viewpoint_target)
                        .props("outlined dense")
                        .classes("flex-1")
                    )

                with ui.row().classes("w-full justify-end mt-4"):
                    ui.button("Back", on_click=_reset).props("flat")
                    ui.button(
                        "Stage Source",
                        on_click=lambda: _on_stage(
                            title_input.value,
                            authors_input.value.split(","),
                            year_input.value,
                            isbn_input.value,
                            int(topic_input.value) if topic_input.value else 0,
                            int(vp_input.value) if vp_input.value else 0,
                        ),
                    ).props("color=primary")

        def _reset():
            path_container.show()
            results_container.hide()
            results_container.clear()
            preflight_btn.show()

        def _on_stage(title, authors, year, isbn, topics, viewpts):
            dto = state["preflight_dto"]
            metadata = BookMetadata(
                title=title,
                authors=[a.strip() for a in authors if a.strip()],
                publication_year=int(year) if year else None,
                isbn=isbn if isbn else None,
            )
            targets = ExtractionTargets(topic_target=topics, viewpoint_target=viewpts)

            errors = validate_authored_book_input(metadata, targets)
            if errors:
                for error in errors:
                    ui.notify(error, type="negative")
                return

            staged_list.append(
                StagedSourceSpec(
                    kind="authored_book",
                    path=dto.source_path,
                    metadata=metadata,
                    targets=targets,
                    resumable_job_id=dto.resumable_job_id,
                )
            )
            refresh_fn()
            dialog.close()

        with ui.row().classes("w-full justify-end mt-4"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            preflight_btn = ui.button("Preflight", on_click=_on_preflight)

    dialog.open()


def _stage_manual_source_dialog(ui, staged_list: list, refresh_fn):
    from asky.plugins.manual_persona_creator.source_service import validate_manual_source

    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label("Stage Manual Knowledge Source").classes("text-lg font-bold")
        path_input = ui.input("File or Directory Path").classes("w-full")
        kind_select = (
            ui.select(
                ["article", "interview", "biography", "autobiography", "essay", "speech", "notes", "posts"],
                value="article",
                label="Kind",
            )
            .classes("w-full")
            .props("outlined")
        )
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            ui.button(
                "Stage Source",
                on_click=lambda: _on_stage(path_input.value, kind_select.value),
            ).props("primary")

        def _on_stage(path, kind):
            if not path:
                ui.notify("Path is required", type="negative")
                return

            try:
                validate_manual_source(kind, path)
            except ValueError as e:
                ui.notify(str(e), type="negative")
                return

            staged_list.append(StagedSourceSpec(kind=kind, path=path))
            refresh_fn()
            dialog.close()

    dialog.open()

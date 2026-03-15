"""Jobs management page placeholder."""

from __future__ import annotations

from typing import Any

from asky.daemon.job_queue import JobQueue, JobStatus
from asky.plugins.gui_server.pages.layout import page_layout


def mount_jobs_page(ui: Any, queue: JobQueue) -> None:
    """Mount the jobs list page."""

    @ui.page("/jobs")
    def _jobs_page() -> None:
        with page_layout("Background Jobs"):
            jobs = queue.list_jobs()
            if not jobs:
                with ui.card().classes("w-full asky-card"):
                    ui.label("No active or recent jobs found.").classes("text-slate-500 italic")
                    ui.label("Jobs submitted through the persona console or other plugins will appear here.").classes("text-sm text-slate-400 mt-2")
                return

            def get_status_class(status: JobStatus) -> str:
                if status == JobStatus.SUCCESS: return "asky-status-success"
                if status == JobStatus.FAILED: return "asky-status-error"
                if status == JobStatus.RUNNING: return "asky-status-info"
                return "asky-status-warning"

            with ui.card().classes("w-full asky-card p-0"):
                with ui.element("table").classes("asky-table"):
                    with ui.element("thead"):
                        with ui.element("tr"):
                            ui.element("th").set_text("ID")
                            ui.element("th").set_text("Job Type")
                            ui.element("th").set_text("Status")
                            ui.element("th").set_text("Created At")
                            ui.element("th").set_text("Attempts")

                    with ui.element("tbody"):
                        for job in jobs:
                            with ui.element("tr"):
                                ui.element("td").set_text(job.id[:8] + "...")
                                ui.element("td").set_text(job.func_name)
                                with ui.element("td"):
                                    ui.label(job.status.value).classes(f"asky-status-badge {get_status_class(job.status)}")
                                ui.element("td").set_text(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(job.created_at)))
                                ui.element("td").set_text(str(job.attempts))
                                
                            if job.error:
                                with ui.element("tr").classes("bg-red-50"):
                                    with ui.element("td").props('colspan=5').classes("p-4"):
                                        ui.label(f"Error: {job.error}").classes("text-red-700 text-sm font-mono")

            # Refresh button
            ui.button("Refresh", on_click=ui.navigate.reload).classes("w-fit mt-4").props("outline")

import time

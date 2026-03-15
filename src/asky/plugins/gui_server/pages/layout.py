"""Shared layout shell for all GUI pages."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional

from nicegui import ui

def theme() -> None:
    """Apply global theme/styles."""
    ui.colors(primary='#3872c1', secondary='#5891d4', accent='#111b1e', positive='#53b689')
    ui.add_head_html('''
        <style>
            .asky-card {
                box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
                border-radius: 0.5rem;
                padding: 1.5rem;
                background-color: white;
            }
            .asky-table {
                width: 100%;
                border-collapse: collapse;
            }
            .asky-table th, .asky-table td {
                padding: 0.75rem;
                text-align: left;
                border-bottom: 1px solid #e5e7eb;
            }
            .asky-status-badge {
                padding: 0.25rem 0.5rem;
                border-radius: 9999px;
                font-size: 0.75rem;
                font-weight: 600;
            }
            .asky-status-success { background-color: #dcfce7; color: #166534; }
            .asky-status-warning { background-color: #fef9c3; color: #854d0e; }
            .asky-status-error { background-color: #fee2e2; color: #991b1b; }
            .asky-status-info { background-color: #e0f2fe; color: #075985; }
        </style>
    ''')

@contextmanager
def page_layout(title: str, *, show_nav: bool = True):
    """Context manager for consistent page layout."""
    theme()
    
    with ui.header().classes('items-center justify-between px-8'):
        with ui.row().classes('items-center gap-6'):
            ui.label('asky').classes('text-2xl font-bold text-white')
            if show_nav:
                with ui.row().classes('gap-4'):
                    ui.link('General', '/settings/general').classes('text-white hover:text-blue-100')
                    ui.link('Plugins', '/plugins').classes('text-white hover:text-blue-100')
                    ui.link('Jobs', '/jobs').classes('text-white hover:text-blue-100')
                    ui.link('Sessions', '/sessions').classes('text-white hover:text-blue-100')
                    ui.link('Personas', '/personas').classes('text-white hover:text-blue-100')
        
        if show_nav:
            with ui.row().classes('items-center gap-4'):
                ui.button(icon='logout', on_click=lambda: ui.navigate.to('/logout')).props('flat color=white text-color=white')

    with ui.column().classes('w-full max-w-6xl mx-auto p-8 gap-6'):
        ui.label(title).classes('text-3xl font-bold mb-4 text-slate-800')
        yield

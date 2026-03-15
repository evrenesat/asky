"""General settings page helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List

import tomlkit

GENERAL_CONFIG_FILENAME = "general.toml"
MIN_POSITIVE_VALUE = 1
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def load_general_settings(config_dir: Path) -> Dict[str, Any]:
    """Load [general] table from general.toml."""
    config_path = config_dir / GENERAL_CONFIG_FILENAME
    if not config_path.exists():
        return {}

    with config_path.open("rb") as file_obj:
        payload = tomllib.load(file_obj)
    general = payload.get("general", {}) if isinstance(payload, dict) else {}
    return dict(general) if isinstance(general, dict) else {}


def validate_general_updates(updates: Dict[str, Any]) -> List[str]:
    """Validate general.toml update payload and return user-facing errors."""
    errors: List[str] = []

    if "default_model" in updates:
        model_alias = str(updates.get("default_model", "") or "").strip()
        if not model_alias:
            errors.append("default_model must be a non-empty string")

    if "summarization_model" in updates:
        model_alias = str(updates.get("summarization_model", "") or "").strip()
        if not model_alias:
            errors.append("summarization_model must be a non-empty string")

    if "max_turns" in updates:
        try:
            max_turns = int(updates.get("max_turns"))
            if max_turns < MIN_POSITIVE_VALUE:
                errors.append("max_turns must be >= 1")
        except Exception:
            errors.append("max_turns must be an integer")

    if "log_level" in updates:
        level = str(updates.get("log_level", "") or "").upper()
        if level not in VALID_LOG_LEVELS:
            errors.append(
                "log_level must be one of: " + ", ".join(sorted(VALID_LOG_LEVELS))
            )

    return errors


def save_general_settings(config_dir: Path, updates: Dict[str, Any]) -> None:
    """Update [general] keys while preserving unrelated TOML content."""
    errors = validate_general_updates(updates)
    if errors:
        raise ValueError("; ".join(errors))

    config_path = config_dir / GENERAL_CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")
        document = tomlkit.parse(content)
    else:
        document = tomlkit.document()

    general_table = document.get("general")
    if general_table is None or not isinstance(general_table, dict):
        general_table = tomlkit.table()
        document["general"] = general_table

    for key, value in updates.items():
        general_table[key] = value

    rendered = tomlkit.dumps(document)
    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    temp_path.replace(config_path)


from asky.plugins.gui_server.pages.layout import page_layout


def mount_general_settings_page(ui: Any, *, config_dir: Path) -> None:
    """Mount editable general settings page."""

    @ui.page("/settings/general")
    def _general_settings_page() -> None:
        with page_layout("General Settings"):
            current_settings = load_general_settings(config_dir)

            with ui.card().classes("w-full asky-card"):
                with ui.column().classes("w-full gap-4"):
                    default_model = ui.input(
                        "Default model",
                        value=str(current_settings.get("default_model", "")),
                    ).classes("w-full")
                    summarization_model = ui.input(
                        "Summarization model",
                        value=str(current_settings.get("summarization_model", "")),
                    ).classes("w-full")
                    max_turns = ui.number(
                        "Max turns",
                        value=int(current_settings.get("max_turns", 10) or 10),
                        precision=0,
                    ).classes("w-full")
                    log_level = ui.select(
                        sorted(VALID_LOG_LEVELS),
                        value=str(current_settings.get("log_level", "INFO")).upper()
                        or "INFO",
                        label="Log level",
                    ).classes("w-full")

                    ui.separator().classes("my-2")

                    status = ui.label("").classes("text-sm font-medium")

                    def _save() -> None:
                        updates = {
                            "default_model": str(default_model.value or "").strip(),
                            "summarization_model": str(
                                summarization_model.value or ""
                            ).strip(),
                            "max_turns": int(max_turns.value or 0),
                            "log_level": str(log_level.value or "").upper(),
                        }
                        errors = validate_general_updates(updates)
                        if errors:
                            status.text = "Validation error: " + "; ".join(errors)
                            status.classes("text-red-600", remove="text-green-600")
                            return

                        try:
                            save_general_settings(config_dir, updates)
                            status.text = "Saved general.toml"
                            status.classes("text-green-600", remove="text-red-600")
                        except Exception as exc:
                            status.text = f"Error: {exc}"
                            status.classes("text-red-600", remove="text-green-600")

                    ui.button("Save Changes", on_click=lambda: _save()).classes("w-fit")

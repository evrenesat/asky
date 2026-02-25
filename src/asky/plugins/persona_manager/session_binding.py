"""Session-to-persona binding persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import tomlkit
import tomllib

SESSION_BINDING_FILENAME = "session_bindings.toml"


def bindings_path(data_dir: Path) -> Path:
    """Return canonical binding file path."""
    return data_dir / SESSION_BINDING_FILENAME


def load_bindings(data_dir: Path) -> Dict[str, str]:
    """Load persisted bindings from disk."""
    path = bindings_path(data_dir)
    if not path.exists():
        return {}

    with path.open("rb") as file_obj:
        payload = tomllib.load(file_obj)

    table = payload.get("binding", {}) if isinstance(payload, dict) else {}
    if not isinstance(table, dict):
        return {}

    bindings: Dict[str, str] = {}
    for session_id, persona_name in table.items():
        sid = str(session_id or "").strip()
        pname = str(persona_name or "").strip()
        if sid and pname:
            bindings[sid] = pname
    return bindings


def save_bindings(data_dir: Path, bindings: Dict[str, str]) -> None:
    """Write bindings atomically."""
    path = bindings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    document = tomlkit.document()
    document["binding"] = dict(bindings)
    rendered = tomlkit.dumps(document)

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    temp_path.replace(path)


def get_session_binding(data_dir: Path, session_id: int | str) -> Optional[str]:
    """Resolve persona binding for one session."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    return load_bindings(data_dir).get(sid)


def set_session_binding(
    data_dir: Path,
    *,
    session_id: int | str,
    persona_name: Optional[str],
) -> None:
    """Create/update/remove a session binding."""
    sid = str(session_id or "").strip()
    if not sid:
        return

    bindings = load_bindings(data_dir)
    if persona_name is None:
        bindings.pop(sid, None)
    else:
        name = str(persona_name or "").strip()
        if name:
            bindings[sid] = name
        else:
            bindings.pop(sid, None)
    save_bindings(data_dir, bindings)

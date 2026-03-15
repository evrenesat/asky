"""Service adapters for Persona Manager GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins.persona_manager.session_binding import (
    load_bindings,
    set_session_binding,
)
from asky.storage import list_sessions, get_session_by_id


def list_sessions_with_bindings(data_dir: Path, limit: int = 100) -> List[Dict[str, Any]]:
    """List sessions with their current persona bindings."""
    sessions = list_sessions(limit)
    bindings = load_bindings(data_dir)
    
    results = []
    for s in sessions:
        results.append({
            "id": s.id,
            "name": s.name,
            "created_at": s.created_at,
            "model": s.model,
            "persona_binding": bindings.get(str(s.id)),
        })
    return results


def bind_persona_to_session(data_dir: Path, session_id: int, persona_name: Optional[str]) -> None:
    """Update persona binding for a session."""
    set_session_binding(data_dir, session_id=session_id, persona_name=persona_name)

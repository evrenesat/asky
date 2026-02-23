"""Session/profile binding and override management for daemon conversations."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from typing import Optional

import tomlkit

from asky.config import DEFAULT_MODEL, MODELS, SUMMARIZATION_MODEL, USER_PROMPTS
from asky.storage import (
    copy_session_override_files,
    create_session,
    get_room_session_binding,
    get_session_by_id,
    get_session_by_name,
    get_sessions_by_name,
    list_room_session_bindings,
    list_session_override_files,
    list_sessions,
    save_session_override_file,
    set_room_session_binding,
)

logger = logging.getLogger(__name__)

DIRECT_SESSION_PREFIX = "xmpp:"
ROOM_SESSION_PREFIX = "xmpp-room:"
SESSION_LIST_LIMIT_DEFAULT = 20
ALLOWED_OVERRIDE_FILENAMES = ("general.toml", "user.toml")
GENERAL_OVERRIDE_KEYS = ("default_model", "summarization_model")


@dataclass(frozen=True)
class EffectiveSessionProfile:
    """Resolved runtime profile for one daemon session."""

    default_model: str
    summarization_model: str
    user_prompts: dict[str, str]


@dataclass(frozen=True)
class OverrideApplyResult:
    """Result for one override upload/apply operation."""

    filename: str
    saved: bool
    ignored_keys: tuple[str, ...]
    applied_keys: tuple[str, ...]
    error: Optional[str] = None


class SessionProfileManager:
    """Manage conversation/session bindings and session-scoped override files."""

    def __init__(self):
        self._direct_session_cache: dict[str, int] = {}

    def get_or_create_direct_session_id(self, jid: str) -> int:
        """Get or create session id for one direct-chat JID."""
        normalized_jid = _normalize_jid(jid)
        if not normalized_jid:
            raise ValueError("jid is required")
        cached = self._direct_session_cache.get(normalized_jid)
        if cached is not None:
            return cached

        session_name = f"{DIRECT_SESSION_PREFIX}{normalized_jid}"
        existing = get_session_by_name(session_name)
        if existing is None:
            session_id = create_session(model=DEFAULT_MODEL, name=session_name)
        else:
            session_id = int(existing.id)
        self._direct_session_cache[normalized_jid] = session_id
        return session_id

    def get_or_create_room_session_id(self, room_jid: str) -> int:
        """Get or create persisted session id bound to a room."""
        normalized_room = _normalize_room_jid(room_jid)
        if not normalized_room:
            raise ValueError("room_jid is required")

        binding = get_room_session_binding(room_jid=normalized_room)
        if binding is not None:
            return int(binding.session_id)

        session_name = f"{ROOM_SESSION_PREFIX}{normalized_room}"
        existing = get_session_by_name(session_name)
        if existing is None:
            session_id = create_session(model=DEFAULT_MODEL, name=session_name)
        else:
            session_id = int(existing.id)
        set_room_session_binding(room_jid=normalized_room, session_id=session_id)
        return session_id

    def bind_room_to_session(self, *, room_jid: str, session_id: int) -> None:
        """Bind room to an existing session."""
        normalized_room = _normalize_room_jid(room_jid)
        if not normalized_room:
            raise ValueError("room_jid is required")
        set_room_session_binding(room_jid=normalized_room, session_id=int(session_id))

    def is_room_bound(self, room_jid: str) -> bool:
        """Return whether room already has a persisted binding."""
        normalized_room = _normalize_room_jid(room_jid)
        if not normalized_room:
            return False
        return get_room_session_binding(room_jid=normalized_room) is not None

    def list_bound_room_jids(self) -> list[str]:
        """List room JIDs that have persisted bindings."""
        return [item.room_jid for item in list_room_session_bindings()]

    def list_recent_sessions(self, limit: int = SESSION_LIST_LIMIT_DEFAULT) -> list:
        """List latest sessions for /session command output."""
        return list_sessions(limit=max(1, int(limit)))

    def create_new_conversation_session(
        self,
        *,
        room_jid: Optional[str],
        jid: Optional[str],
        inherit_current: bool,
    ) -> int:
        """Create a brand new session and attach current conversation to it."""
        source_session_id = self.resolve_conversation_session_id(
            room_jid=room_jid,
            jid=jid,
        )
        new_session_name = _build_child_session_name(room_jid=room_jid, jid=jid)
        new_session_id = create_session(model=DEFAULT_MODEL, name=new_session_name)
        if inherit_current:
            copy_session_override_files(
                source_session_id=source_session_id,
                target_session_id=new_session_id,
            )
        self._assign_conversation_session(
            room_jid=room_jid, jid=jid, session_id=new_session_id
        )
        return int(new_session_id)

    def switch_conversation_session(
        self,
        *,
        room_jid: Optional[str],
        jid: Optional[str],
        selector: str,
    ) -> tuple[Optional[int], Optional[str]]:
        """Switch current conversation to an existing session by id or exact name."""
        selected, error = self._resolve_session_selector(selector)
        if selected is None:
            return None, error or "Session not found."
        session_id = int(selected.id)
        self._assign_conversation_session(
            room_jid=room_jid, jid=jid, session_id=session_id
        )
        return session_id, None

    def resolve_conversation_session_id(
        self,
        *,
        room_jid: Optional[str],
        jid: Optional[str],
    ) -> int:
        """Resolve the active session id for this conversation."""
        room_value = _normalize_room_jid(room_jid or "")
        if room_value:
            return self.get_or_create_room_session_id(room_value)
        return self.get_or_create_direct_session_id(str(jid or ""))

    def count_session_messages(self, session_id: int) -> int:
        """Return the number of conversation messages in a session."""
        from asky.storage import get_session_messages

        return len(get_session_messages(session_id))

    def clear_conversation(self, session_id: int) -> int:
        """Delete all conversation messages for a session. Returns deleted count."""
        from asky.storage import clear_session_messages

        return clear_session_messages(session_id)

    def get_effective_profile(self, *, session_id: int) -> EffectiveSessionProfile:
        """Build effective runtime profile from global defaults + session files."""
        default_model = str(DEFAULT_MODEL)
        summarization_model = str(SUMMARIZATION_MODEL)
        prompt_map = dict(USER_PROMPTS)

        files = list_session_override_files(session_id=int(session_id))
        for item in files:
            filename = str(item.filename or "").strip().lower()
            content = str(item.content or "")
            if filename == "general.toml":
                parsed = _safe_parse_toml(content)
                general = parsed.get("general", {}) if isinstance(parsed, dict) else {}
                if isinstance(general, dict):
                    model_candidate = general.get("default_model")
                    if isinstance(model_candidate, str) and model_candidate.strip():
                        default_model = model_candidate.strip()
                    summary_candidate = general.get("summarization_model")
                    if isinstance(summary_candidate, str) and summary_candidate.strip():
                        summarization_model = summary_candidate.strip()
            elif filename == "user.toml":
                parsed = _safe_parse_toml(content)
                table = (
                    parsed.get("user_prompts", {}) if isinstance(parsed, dict) else {}
                )
                if isinstance(table, dict):
                    prompt_map = {
                        str(key): str(value)
                        for key, value in table.items()
                        if str(key).strip() and isinstance(value, str)
                    }

        return EffectiveSessionProfile(
            default_model=default_model,
            summarization_model=summarization_model,
            user_prompts=prompt_map,
        )

    def apply_override_file(
        self,
        *,
        session_id: int,
        filename: str,
        content: str,
    ) -> OverrideApplyResult:
        """Validate and persist one supported override TOML file for a session."""
        normalized_filename = str(filename or "").strip().lower()
        if normalized_filename not in ALLOWED_OVERRIDE_FILENAMES:
            return OverrideApplyResult(
                filename=normalized_filename or str(filename or ""),
                saved=False,
                ignored_keys=(),
                applied_keys=(),
                error=(
                    "Unsupported filename. Allowed files: "
                    + ", ".join(ALLOWED_OVERRIDE_FILENAMES)
                ),
            )

        parsed = _safe_parse_toml(content, strict=True)
        if not isinstance(parsed, dict):
            return OverrideApplyResult(
                filename=normalized_filename,
                saved=False,
                ignored_keys=(),
                applied_keys=(),
                error="Invalid TOML payload.",
            )

        if normalized_filename == "general.toml":
            sanitized, applied_keys, ignored_keys = _sanitize_general_override(parsed)
        else:
            sanitized, applied_keys, ignored_keys = _sanitize_user_override(parsed)

        save_session_override_file(
            session_id=int(session_id),
            filename=normalized_filename,
            content=sanitized,
        )
        return OverrideApplyResult(
            filename=normalized_filename,
            saved=True,
            ignored_keys=tuple(ignored_keys),
            applied_keys=tuple(applied_keys),
            error=None,
        )

    def _assign_conversation_session(
        self,
        *,
        room_jid: Optional[str],
        jid: Optional[str],
        session_id: int,
    ) -> None:
        room_value = _normalize_room_jid(room_jid or "")
        if room_value:
            self.bind_room_to_session(room_jid=room_value, session_id=session_id)
            return
        jid_value = _normalize_jid(jid or "")
        if jid_value:
            self._direct_session_cache[jid_value] = int(session_id)

    def _resolve_session_selector(self, selector: str):
        normalized = str(selector or "").strip()
        if not normalized:
            return None, "Session selector is required."
        if normalized.isdigit():
            session = get_session_by_id(int(normalized))
            if session is None:
                return None, f"Session {normalized} not found."
            return session, None
        exact = get_session_by_name(normalized)
        if exact is not None:
            return exact, None
        matches = get_sessions_by_name(normalized)
        if not matches:
            return None, f"Session '{normalized}' not found."
        if len(matches) > 1:
            session_ids = ", ".join(str(item.id) for item in matches[:5])
            return (
                None,
                f"Session name '{normalized}' is ambiguous. Use id ({session_ids}).",
            )
        return matches[0], None


def _normalize_jid(value: str) -> str:
    return str(value or "").strip()


def _normalize_room_jid(value: str) -> str:
    return str(value or "").strip().lower()


def _build_child_session_name(*, room_jid: Optional[str], jid: Optional[str]) -> str:
    base = _normalize_room_jid(room_jid or "")
    if base:
        return f"{ROOM_SESSION_PREFIX}{base}:child"
    direct = _normalize_jid(jid or "")
    if direct:
        return f"{DIRECT_SESSION_PREFIX}{direct}:child"
    return "xmpp:child"


def _safe_parse_toml(content: str, *, strict: bool = False):
    normalized = str(content or "")
    if not normalized.strip():
        return {}
    try:
        return tomllib.loads(normalized)
    except tomllib.TOMLDecodeError:
        if strict:
            return None
        logger.debug("failed to parse persisted session override TOML", exc_info=True)
        return {}


def _sanitize_general_override(parsed: dict) -> tuple[str, list[str], list[str]]:
    general = parsed.get("general", {})
    if not isinstance(general, dict):
        general = {}
    applied: list[str] = []
    ignored: list[str] = []

    table = tomlkit.table()
    for key, value in general.items():
        if key in GENERAL_OVERRIDE_KEYS and isinstance(value, str) and value.strip():
            candidate = value.strip()
            if candidate not in MODELS:
                ignored.append(f"general.{key}")
                continue
            table[key] = candidate
            applied.append(f"general.{key}")
        else:
            ignored.append(f"general.{key}")

    if not applied:
        return "", applied, ignored
    doc = tomlkit.document()
    doc["general"] = table
    return tomlkit.dumps(doc), applied, ignored


def _sanitize_user_override(parsed: dict) -> tuple[str, list[str], list[str]]:
    prompt_table = parsed.get("user_prompts", {})
    if not isinstance(prompt_table, dict):
        prompt_table = {}

    applied: list[str] = []
    ignored: list[str] = []
    table = tomlkit.table()
    for key, value in prompt_table.items():
        key_str = str(key).strip()
        if key_str and isinstance(value, str):
            table[key_str] = value
            applied.append(f"user_prompts.{key_str}")
        else:
            ignored.append(f"user_prompts.{key_str or key}")

    for top_level_key in parsed.keys():
        if str(top_level_key) != "user_prompts":
            ignored.append(str(top_level_key))

    if not applied:
        return "", applied, ignored
    doc = tomlkit.document()
    doc["user_prompts"] = table
    return tomlkit.dumps(doc), applied, ignored

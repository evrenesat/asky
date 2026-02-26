"""XEP-0050 Ad-Hoc Commands handler for asky XMPP daemon."""

from __future__ import annotations

import asyncio
import functools
import io
import logging
import shlex
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable, Optional, TYPE_CHECKING

from asky.config import MODELS, XMPP_JID

if TYPE_CHECKING:
    from asky.plugins.xmpp_daemon.command_executor import CommandExecutor
    from asky.plugins.xmpp_daemon.router import DaemonRouter

logger = logging.getLogger(__name__)

NODE_STATUS = "asky#status"
NODE_LIST_SESSIONS = "asky#list-sessions"
NODE_LIST_HISTORY = "asky#list-history"
NODE_LIST_TRANSCRIPTS = "asky#list-transcripts"
NODE_LIST_TOOLS = "asky#list-tools"
NODE_LIST_MEMORIES = "asky#list-memories"
NODE_LIST_PROMPTS = "asky#list-prompts"
NODE_LIST_PRESETS = "asky#list-presets"
NODE_QUERY = "asky#query"
NODE_NEW_SESSION = "asky#new-session"
NODE_SWITCH_SESSION = "asky#switch-session"
NODE_CLEAR_SESSION = "asky#clear-session"
NODE_USE_TRANSCRIPT = "asky#use-transcript"

ADHOC_COMMANDS = [
    (NODE_STATUS, "Status"),
    (NODE_LIST_SESSIONS, "List Sessions"),
    (NODE_LIST_HISTORY, "List History"),
    (NODE_LIST_TRANSCRIPTS, "List Transcripts"),
    (NODE_LIST_TOOLS, "List Tools"),
    (NODE_LIST_MEMORIES, "List Memories"),
    (NODE_LIST_PROMPTS, "List Prompts"),
    (NODE_LIST_PRESETS, "List Presets"),
    (NODE_QUERY, "Run Query"),
    (NODE_NEW_SESSION, "New Session"),
    (NODE_SWITCH_SESSION, "Switch Session"),
    (NODE_CLEAR_SESSION, "Clear Session"),
    (NODE_USE_TRANSCRIPT, "Use Transcript as Query"),
]

_FORM_UNAVAILABLE_ERROR = "Data forms not available (xep_0004 missing)."


class AdHocCommandHandler:
    """Registers and handles XEP-0050 ad-hoc commands for asky XMPP daemon."""

    def __init__(
        self,
        *,
        command_executor: "CommandExecutor",
        router: "DaemonRouter",
        voice_enabled: bool = False,
        image_enabled: bool = False,
    ):
        self.command_executor = command_executor
        self.router = router
        self.voice_enabled = voice_enabled
        self.image_enabled = image_enabled
        self._xep_0004 = None

    def register_all(self, xep_0050, xep_0004=None) -> None:
        """Register all ad-hoc commands with the xep_0050 plugin. Called at session start."""
        self._xep_0004 = xep_0004
        add_command = getattr(xep_0050, "add_command", None)
        if not callable(add_command):
            logger.warning("xep_0050 plugin has no add_command(); ad-hoc commands disabled")
            return

        handler_map: dict[str, Callable] = {
            NODE_STATUS: self._cmd_status,
            NODE_LIST_SESSIONS: self._cmd_list_sessions,
            NODE_LIST_HISTORY: self._cmd_list_history,
            NODE_LIST_TRANSCRIPTS: self._cmd_list_transcripts,
            NODE_LIST_TOOLS: self._cmd_list_tools,
            NODE_LIST_MEMORIES: self._cmd_list_memories,
            NODE_LIST_PROMPTS: self._cmd_list_prompts,
            NODE_LIST_PRESETS: self._cmd_list_presets,
            NODE_QUERY: self._cmd_query,
            NODE_NEW_SESSION: self._cmd_new_session,
            NODE_SWITCH_SESSION: self._cmd_switch_session,
            NODE_CLEAR_SESSION: self._cmd_clear_session,
            NODE_USE_TRANSCRIPT: self._cmd_use_transcript,
        }

        for node, name in ADHOC_COMMANDS:
            handler = handler_map.get(node)
            if handler is None:
                continue
            try:
                add_command(node=node, name=name, handler=handler)
                logger.debug("registered ad-hoc command node=%s name=%s", node, name)
            except Exception:
                logger.debug("failed to register ad-hoc command node=%s", node, exc_info=True)

    # --- Infrastructure helpers ---

    def _sender_jid(self, iq) -> str:
        """Extract bare JID string from an IQ stanza."""
        try:
            from_field = iq["from"]
            if hasattr(from_field, "bare"):
                return str(from_field.bare)
            return str(from_field).split("/")[0]
        except Exception:
            return ""

    def _is_authorized(self, iq) -> bool:
        """Return True if the IQ sender is on the daemon allowlist."""
        sender = self._sender_jid(iq)
        return bool(sender) and self.router.is_authorized(sender)

    def _unauthorized_response(self, session: dict) -> dict:
        session["notes"] = [("error", "Not authorized.")]
        session["has_next"] = False
        session["next"] = None
        session["payload"] = None
        return session

    def _complete_with_text(self, session: dict, text: str) -> dict:
        session["notes"] = [("info", str(text or "(no output)"))]
        session["has_next"] = False
        session["next"] = None
        session["payload"] = None
        return session

    def _complete_with_error(self, session: dict, error: str) -> dict:
        session["notes"] = [("error", str(error or "Unknown error"))]
        session["has_next"] = False
        session["next"] = None
        session["payload"] = None
        return session

    async def _run_blocking(self, fn: Callable, *args, **kwargs):
        """Run a blocking function in the default thread pool executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))

    def _make_form(self, title: str, fields: list[dict]) -> Optional[object]:
        """Build a XEP-0004 data form. Returns None if xep_0004 is unavailable."""
        if self._xep_0004 is None:
            return None
        try:
            form = self._xep_0004.make_form(ftype="form", title=title)
            for spec in fields:
                options = spec.get("options")
                field_kwargs = {k: v for k, v in spec.items() if k != "options"}
                try:
                    field = form.add_field(**field_kwargs)
                except TypeError:
                    minimal = {k: v for k, v in field_kwargs.items() if k in ("var", "ftype", "label")}
                    field = form.add_field(**minimal)
                if options and field is not None:
                    for opt in options:
                        try:
                            field.add_option(
                                value=opt.get("value", ""),
                                label=opt.get("label", opt.get("value", "")),
                            )
                        except Exception:
                            logger.debug("failed to add form option", exc_info=True)
            return form
        except Exception:
            logger.debug("failed to create data form", exc_info=True)
            return None

    @staticmethod
    def _form_values(iq) -> dict:
        """Extract submitted form values from an IQ stanza."""
        try:
            return dict(iq["command"]["form"].get_values() or {})
        except Exception:
            return {}

    # --- Single-step informational commands ---

    async def _cmd_status(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        lines = [
            f"Connected JID: {XMPP_JID}",
            f"Voice transcription: {'enabled' if self.voice_enabled else 'disabled'}",
            f"Image transcription: {'enabled' if self.image_enabled else 'disabled'}",
        ]
        return self._complete_with_text(session, "\n".join(lines))

    async def _cmd_list_sessions(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        result = await self._run_blocking(
            self.command_executor.execute_session_command,
            jid=sender,
            room_jid=None,
            command_text="/session",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_history(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text="--history 20",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_transcripts(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text="transcript list",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_tools(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)

        def _get_tools() -> str:
            from asky.core.tool_registry_factory import get_all_available_tool_names

            tools = get_all_available_tool_names()
            if not tools:
                return "No tools available."
            lines = ["Available LLM tools:"] + [f"  - {t}" for t in sorted(tools)]
            return "\n".join(lines)

        result = await self._run_blocking(_get_tools)
        return self._complete_with_text(session, result)

    async def _cmd_list_memories(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)

        def _get_memories() -> str:
            from asky.cli.memory_commands import handle_list_memories
            from asky.storage import init_db

            init_db()
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                handle_list_memories()
            return buf.getvalue().strip() or "No memories saved."

        result = await self._run_blocking(_get_memories)
        return self._complete_with_text(session, result)

    async def _cmd_list_prompts(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        result = await self._run_blocking(
            self.command_executor.execute_query_text,
            jid=sender,
            query_text="/",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_presets(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)

        def _get_presets() -> str:
            from asky.cli.presets import list_presets_text

            return list_presets_text()

        result = await self._run_blocking(_get_presets)
        return self._complete_with_text(session, result)

    # --- Form-based interactive commands ---

    async def _cmd_query(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        model_options = [{"value": "", "label": "(default)"}] + [
            {"value": alias, "label": alias} for alias in sorted(MODELS.keys())
        ]
        form = self._make_form(
            title="Run Query",
            fields=[
                {"var": "query", "ftype": "text-single", "label": "Query", "required": True},
                {"var": "research", "ftype": "boolean", "label": "Research mode", "value": "false"},
                {"var": "model", "ftype": "list-single", "label": "Model (optional)", "options": model_options},
                {"var": "turns", "ftype": "text-single", "label": "Max turns (optional)"},
                {"var": "lean", "ftype": "boolean", "label": "Lean mode (no shortlisting)", "value": "false"},
                {"var": "system_prompt", "ftype": "text-multi", "label": "System prompt override (optional)"},
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_query_submit
        session["has_next"] = True
        return session

    async def _cmd_query_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        values = self._form_values(iq)

        query = str(values.get("query") or "").strip()
        if not query:
            return self._complete_with_error(session, "Query is required.")

        tokens: list[str] = []
        if str(values.get("research") or "").strip().lower() in ("true", "1", "yes"):
            tokens.append("-r")
        model = str(values.get("model") or "").strip()
        if model:
            tokens.extend(["-m", model])
        turns_raw = str(values.get("turns") or "").strip()
        if turns_raw and turns_raw.isdigit():
            tokens.extend(["-t", turns_raw])
        if str(values.get("lean") or "").strip().lower() in ("true", "1", "yes"):
            tokens.append("-L")
        system_prompt = str(values.get("system_prompt") or "").strip()
        if system_prompt:
            tokens.extend(["--system-prompt", system_prompt])
        tokens.append(query)

        command_text = " ".join(shlex.quote(t) for t in tokens)
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text=command_text,
        )
        return self._complete_with_text(session, result)

    async def _cmd_new_session(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        result = await self._run_blocking(
            self.command_executor.execute_session_command,
            jid=sender,
            room_jid=None,
            command_text="/session new",
        )
        return self._complete_with_text(session, result)

    async def _cmd_switch_session(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        form = self._make_form(
            title="Switch Session",
            fields=[
                {"var": "selector", "ftype": "text-single", "label": "Session ID or name", "required": True},
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_switch_session_submit
        session["has_next"] = True
        return session

    async def _cmd_switch_session_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        values = self._form_values(iq)
        selector = str(values.get("selector") or "").strip()
        if not selector:
            return self._complete_with_error(session, "Session selector is required.")
        result = await self._run_blocking(
            self.command_executor.execute_session_command,
            jid=sender,
            room_jid=None,
            command_text=f"/session {selector}",
        )
        return self._complete_with_text(session, result)

    async def _cmd_clear_session(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        form = self._make_form(
            title="Clear Session",
            fields=[
                {
                    "var": "confirm",
                    "ftype": "boolean",
                    "label": "Clear all conversation messages? (transcripts and media are kept)",
                    "required": True,
                    "value": "false",
                }
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_clear_session_submit
        session["has_next"] = True
        return session

    async def _cmd_clear_session_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        values = self._form_values(iq)
        confirm = str(values.get("confirm") or "").strip().lower() in ("true", "1", "yes")
        if not confirm:
            return self._complete_with_text(session, "Session clear cancelled.")

        def _do_clear() -> str:
            session_id = self.command_executor.session_profile_manager.resolve_conversation_session_id(
                room_jid=None, jid=sender
            )
            deleted = self.command_executor.session_profile_manager.clear_conversation(session_id)
            return f"Cleared {deleted} message(s) from session {session_id}."

        result = await self._run_blocking(_do_clear)
        return self._complete_with_text(session, result)

    async def _cmd_use_transcript(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)

        def _list() -> list:
            return self.command_executor.transcript_manager.list_for_jid(sender, limit=20)

        records = await self._run_blocking(_list)
        if not records:
            return self._complete_with_text(session, "No transcripts available.")

        options = []
        for record in records:
            preview = (record.transcript_text or "").strip().replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            options.append(
                {
                    "value": str(record.session_transcript_id),
                    "label": f"#at{record.session_transcript_id}: {preview}",
                }
            )

        form = self._make_form(
            title="Use Transcript as Query",
            fields=[
                {
                    "var": "transcript_id",
                    "ftype": "list-single",
                    "label": "Select transcript",
                    "required": True,
                    "options": options,
                }
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_use_transcript_submit
        session["has_next"] = True
        return session

    async def _cmd_use_transcript_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq)
        values = self._form_values(iq)
        transcript_id = str(values.get("transcript_id") or "").strip()
        if not transcript_id:
            return self._complete_with_error(session, "Transcript selection is required.")
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text=f"transcript use #at{transcript_id}",
        )
        return self._complete_with_text(session, result)

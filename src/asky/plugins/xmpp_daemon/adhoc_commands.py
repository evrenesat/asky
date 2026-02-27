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
    (NODE_LIST_PROMPTS, "Run Prompt"),
    (NODE_LIST_PRESETS, "Run Preset"),
    (NODE_QUERY, "Run Query"),
    (NODE_NEW_SESSION, "New Session"),
    (NODE_SWITCH_SESSION, "Switch Session"),
    (NODE_CLEAR_SESSION, "Clear Session"),
    (NODE_USE_TRANSCRIPT, "Use Transcript as Query"),
]

_FORM_UNAVAILABLE_ERROR = "Data forms not available (xep_0004 missing)."
XDATA_NAMESPACE = "jabber:x:data"
QUERY_DISPATCH_UNAVAILABLE_ERROR = "Query dispatch is unavailable."


def _format_section(title: str, body: str) -> str:
    """Wrap body text with a titled header and divider."""
    divider = "-" * max(len(title), 20)
    return f"{title}\n{divider}\n{body}"


def _format_kv_pairs(pairs: list[tuple[str, str]]) -> str:
    """Format a list of (key, value) tuples with aligned columns."""
    if not pairs:
        return ""
    width = max(len(k) for k, _ in pairs)
    lines = [f"{k:<{width}}  {v}" for k, v in pairs]
    return "\n".join(lines)


class AdHocCommandHandler:
    """Registers and handles XEP-0050 ad-hoc commands for asky XMPP daemon."""

    def __init__(
        self,
        *,
        command_executor: "CommandExecutor",
        router: "DaemonRouter",
        voice_enabled: bool = False,
        image_enabled: bool = False,
        query_dispatch_callback: Optional[Callable[..., None]] = None,
    ):
        self.command_executor = command_executor
        self.router = router
        self.voice_enabled = voice_enabled
        self.image_enabled = image_enabled
        self._xep_0004 = None
        self._query_dispatch_callback = query_dispatch_callback

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

    @staticmethod
    def _get_stanza_interface_value(iq, interface_name: str):
        """Safely resolve stanza interface value without triggering noisy warnings."""
        try:
            interfaces = getattr(iq, "interfaces", None)
            if interfaces is not None and interface_name not in interfaces:
                return None
        except Exception:
            return None
        try:
            return iq[interface_name]
        except Exception:
            return None

    @staticmethod
    def _bare_jid(jid: str) -> str:
        normalized = str(jid or "").strip()
        if not normalized:
            return ""
        if "/" not in normalized:
            return normalized
        return normalized.split("/", 1)[0]

    def _sender_full_jid(self, iq) -> str:
        """Extract full sender JID from an IQ stanza with fallback methods."""
        from_field = self._get_stanza_interface_value(iq, "from")

        if from_field is not None:
            try:
                if hasattr(from_field, "full"):
                    full_jid = str(from_field.full or "").strip()
                    if full_jid and full_jid.lower() != "none":
                        return full_jid
            except Exception:
                pass
            try:
                from_str = str(from_field or "").strip()
                if from_str and from_str.lower() != "none":
                    return from_str
            except Exception:
                pass

        try:
            xml = getattr(iq, "xml", None)
            if xml is not None:
                from_attr = str(getattr(xml, "attrib", {}).get("from", "") or "").strip()
                if from_attr and from_attr.lower() != "none":
                    return from_attr
        except Exception:
            pass

        try:
            iq_str = str(iq)
            if 'from="' in iq_str:
                from_attr = iq_str.split('from="', 1)[1].split('"', 1)[0].strip()
                if from_attr and from_attr.lower() != "none":
                    return from_attr
        except Exception:
            pass

        logger.warning(
            "failed to resolve sender JID from ad-hoc IQ stanza; from_field_type=%s",
            type(from_field),
        )
        return ""

    def _sender_jid(self, iq, session: Optional[dict] = None) -> str:
        """Return sender bare JID; fall back to session-stored sender when needed."""
        bare_jid = self._bare_jid(self._sender_full_jid(iq))
        if bare_jid:
            return bare_jid
        if session is not None:
            stored_bare = self._bare_jid(str(session.get("_authorized_bare_jid") or ""))
            if stored_bare:
                return stored_bare
            stored_full = self._bare_jid(str(session.get("_authorized_full_jid") or ""))
            if stored_full:
                return stored_full
        return ""

    def _sender_candidates(self, iq, session: Optional[dict] = None) -> list[str]:
        candidates: list[str] = []
        full_jid = self._sender_full_jid(iq)
        bare_jid = self._bare_jid(full_jid)
        if full_jid:
            candidates.append(full_jid)
        if bare_jid and bare_jid != full_jid:
            candidates.append(bare_jid)
        if session is not None:
            stored_full = str(session.get("_authorized_full_jid") or "").strip()
            stored_bare = self._bare_jid(str(session.get("_authorized_bare_jid") or ""))
            if stored_full and stored_full not in candidates:
                candidates.append(stored_full)
            if stored_bare and stored_bare not in candidates:
                candidates.append(stored_bare)
        return candidates

    def _is_authorized(self, iq, session: Optional[dict] = None) -> bool:
        """Return True if IQ sender or stored sender for this session is allowlisted."""
        for sender in self._sender_candidates(iq, session=session):
            if not self.router.is_authorized(sender):
                continue
            if session is not None:
                session["_authorized_bare_jid"] = self._bare_jid(sender)
                if "/" in sender:
                    session["_authorized_full_jid"] = sender
                else:
                    full_jid = self._sender_full_jid(iq)
                    if full_jid:
                        session["_authorized_full_jid"] = full_jid
            return True
        return False

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

    def _enqueue_query_from_adhoc(
        self,
        *,
        sender: str,
        query_text: Optional[str] = None,
        command_text: Optional[str] = None,
    ) -> bool:
        callback = self._query_dispatch_callback
        if callback is None:
            return False
        callback(
            jid=sender,
            room_jid=None,
            query_text=query_text,
            command_text=command_text,
        )
        return True

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
    def _form_values_from_xml(iq) -> dict:
        """Extract submitted XEP-0004 form values from raw IQ XML payload."""
        xml = getattr(iq, "xml", None)
        if xml is None:
            return {}
        ns_prefix = f"{{{XDATA_NAMESPACE}}}"
        values: dict[str, str] = {}
        try:
            fields = xml.findall(f".//{ns_prefix}field")
            for field in fields:
                var_name = str(getattr(field, "attrib", {}).get("var", "") or "").strip()
                if not var_name or var_name == "FORM_TYPE":
                    continue
                value_nodes = field.findall(f"{ns_prefix}value")
                if not value_nodes:
                    values[var_name] = ""
                    continue
                raw_values = [
                    str(getattr(value_node, "text", "") or "").strip()
                    for value_node in value_nodes
                ]
                non_empty_values = [value for value in raw_values if value]
                values[var_name] = non_empty_values[0] if non_empty_values else ""
            return values
        except Exception:
            return {}

    def _form_values(self, iq) -> dict:
        """Extract submitted form values from an IQ stanza."""
        command_node = self._get_stanza_interface_value(iq, "command")
        if command_node is not None:
            try:
                return dict(command_node["form"].get_values() or {})
            except Exception:
                pass
        xml_values = self._form_values_from_xml(iq)
        if xml_values:
            return xml_values
        return {}

    # --- Single-step informational commands ---

    async def _cmd_status(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        pairs = [
            ("Connected JID", str(XMPP_JID)),
            ("Voice transcription", "enabled" if self.voice_enabled else "disabled"),
            ("Image transcription", "enabled" if self.image_enabled else "disabled"),
        ]
        return self._complete_with_text(session, _format_section("asky Status", _format_kv_pairs(pairs)))

    async def _cmd_list_sessions(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        result = await self._run_blocking(
            self.command_executor.execute_session_command,
            jid=sender,
            room_jid=None,
            command_text="/session",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_history(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text="--history 20",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_transcripts(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text="transcript list",
        )
        return self._complete_with_text(session, result)

    async def _cmd_list_tools(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)

        def _get_tools() -> str:
            from asky.core.tool_registry_factory import get_all_available_tool_names

            tools = get_all_available_tool_names()
            if not tools:
                return _format_section("Available LLM Tools", "No tools available.")
            body = "\n".join(f"  {t}" for t in sorted(tools))
            return _format_section(f"Available LLM Tools ({len(tools)})", body)

        result = await self._run_blocking(_get_tools)
        return self._complete_with_text(session, result)

    async def _cmd_list_memories(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)

        def _get_prompts() -> dict:
            from asky.config import USER_PROMPTS

            return dict(USER_PROMPTS or {})

        prompts = await self._run_blocking(_get_prompts)
        if not prompts:
            return self._complete_with_text(session, "No prompt aliases are configured.")

        options = []
        for alias in sorted(prompts.keys()):
            template = str(prompts[alias] or "").strip()
            preview = template[:60] + "..." if len(template) > 60 else template
            options.append({"value": alias, "label": f"/{alias}: {preview}"})

        form = self._make_form(
            title="Run Prompt",
            fields=[
                {
                    "var": "prompt",
                    "ftype": "list-single",
                    "label": "Select prompt",
                    "required": True,
                    "options": options,
                },
                {
                    "var": "query",
                    "ftype": "text-single",
                    "label": "Extra query text (optional)",
                },
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_list_prompts_submit
        session["has_next"] = True
        return session

    async def _cmd_list_prompts_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        values = self._form_values(iq)
        alias = str(values.get("prompt") or "").strip()
        if not alias:
            return self._complete_with_error(session, "Prompt selection is required.")
        query = str(values.get("query") or "").strip()
        query_text = f"/{alias} {query}".strip() if query else f"/{alias}"
        dispatched = self._enqueue_query_from_adhoc(
            sender=sender,
            query_text=query_text,
        )
        if not dispatched:
            return self._complete_with_error(session, QUERY_DISPATCH_UNAVAILABLE_ERROR)
        return self._complete_with_text(
            session, "Run Prompt started. Response will be sent to chat."
        )

    async def _cmd_list_presets(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)

        def _get_presets() -> dict:
            from asky.config import COMMAND_PRESETS

            return dict(COMMAND_PRESETS or {})

        presets = await self._run_blocking(_get_presets)
        if not presets:
            return self._complete_with_text(session, "No command presets are configured.")

        options = []
        for name in sorted(presets.keys()):
            template = str(presets[name] or "").strip()
            preview = template[:60] + "..." if len(template) > 60 else template
            options.append({"value": name, "label": f"\\{name}: {preview}"})

        form = self._make_form(
            title="Run Preset",
            fields=[
                {
                    "var": "preset",
                    "ftype": "list-single",
                    "label": "Select preset",
                    "required": True,
                    "options": options,
                },
                {
                    "var": "args",
                    "ftype": "text-single",
                    "label": "Arguments (optional)",
                },
            ],
        )
        if form is None:
            return self._complete_with_error(session, _FORM_UNAVAILABLE_ERROR)
        session["payload"] = form
        session["next"] = self._cmd_list_presets_submit
        session["has_next"] = True
        return session

    async def _cmd_list_presets_submit(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        values = self._form_values(iq)
        name = str(values.get("preset") or "").strip()
        if not name:
            return self._complete_with_error(session, "Preset selection is required.")
        args = str(values.get("args") or "").strip()
        raw_invocation = f"\\{name} {args}".strip() if args else f"\\{name}"

        def _expand() -> tuple[str, str]:
            from asky.cli.presets import expand_preset_invocation

            expansion = expand_preset_invocation(raw_invocation)
            if expansion.error:
                return "", f"Error: {expansion.error}"
            return expansion.command_text, ""

        expanded_command, expansion_error = await self._run_blocking(_expand)
        if expansion_error:
            return self._complete_with_text(session, expansion_error)
        executes_query = await self._run_blocking(
            self.command_executor.command_executes_lm_query,
            jid=sender,
            room_jid=None,
            command_text=expanded_command,
        )
        if executes_query:
            dispatched = self._enqueue_query_from_adhoc(
                sender=sender,
                command_text=expanded_command,
            )
            if not dispatched:
                return self._complete_with_error(
                    session, QUERY_DISPATCH_UNAVAILABLE_ERROR
                )
            return self._complete_with_text(
                session, "Run Preset started. Response will be sent to chat."
            )
        result = await self._run_blocking(
            self.command_executor.execute_command_text,
            jid=sender,
            command_text=expanded_command,
        )
        return self._complete_with_text(session, result)

    # --- Form-based interactive commands ---

    async def _cmd_query(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
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
        dispatched = self._enqueue_query_from_adhoc(
            sender=sender,
            command_text=command_text,
        )
        if not dispatched:
            return self._complete_with_error(session, QUERY_DISPATCH_UNAVAILABLE_ERROR)
        return self._complete_with_text(
            session, "Run Query started. Response will be sent to chat."
        )

    async def _cmd_new_session(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        result = await self._run_blocking(
            self.command_executor.execute_session_command,
            jid=sender,
            room_jid=None,
            command_text="/session new",
        )
        return self._complete_with_text(session, result)

    async def _cmd_switch_session(self, iq, session: dict) -> dict:
        if not self._is_authorized(iq, session):
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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
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
        if not self._is_authorized(iq, session):
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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)

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
        if not self._is_authorized(iq, session):
            return self._unauthorized_response(session)
        sender = self._sender_jid(iq, session)
        values = self._form_values(iq)
        transcript_id = str(values.get("transcript_id") or "").strip()
        if not transcript_id:
            return self._complete_with_error(session, "Transcript selection is required.")
        dispatched = self._enqueue_query_from_adhoc(
            sender=sender,
            command_text=f"transcript use #at{transcript_id}",
        )
        if not dispatched:
            return self._complete_with_error(session, QUERY_DISPATCH_UNAVAILABLE_ERROR)
        return self._complete_with_text(
            session,
            "Use Transcript as Query started. Response will be sent to chat.",
        )

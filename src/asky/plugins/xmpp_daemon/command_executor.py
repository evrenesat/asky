"""Command execution bridge for daemon mode."""

from __future__ import annotations

import argparse
import io
import os
import re
import threading
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Optional, TYPE_CHECKING
from urllib.parse import urlparse

import requests

from asky import summarization
from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.cli import history, sessions, utils
from asky.cli.main import (
    _manual_corpus_query_arg,
    _manual_section_query_arg,
    _resolve_research_corpus,
    parse_args,
    research_commands,
    section_commands,
)
from asky.cli.verbose_output import build_verbose_output_callback
from asky.config import DEFAULT_MODEL
from asky.plugins.xmpp_daemon.transcript_manager import TranscriptManager
from asky.storage import init_db

if TYPE_CHECKING:
    from asky.plugins.runtime import PluginRuntime

TRANSCRIPT_COMMAND = "transcript"
TRANSCRIPT_HELP = (
    "Transcript commands:\n"
    "  transcript list [limit]\n"
    "  transcript show <id|#atN>\n"
    "  transcript use <id|#atN>\n"
    "  transcript clear"
)
SESSION_COMMAND_TOKEN = "/session"
SESSION_LIST_LIMIT = 20
SESSION_HELP = (
    "Session commands:\n"
    "  /session                Show this help + latest sessions\n"
    "  /session new            Create and switch to a new session\n"
    "  /session child          Create and switch to a child session (inherit current overrides)\n"
    "  /session clear          Clear all conversation messages (keeps transcripts/media)\n"
    "  /session <id|name>      Switch to an existing session by id or exact name"
)
HELP_COMMAND_TOKENS = {"/h", "/help"}
MAX_TOML_DOWNLOAD_BYTES = 256 * 1024
TOML_DOWNLOAD_TIMEOUT_SECONDS = 30
REMOTE_BLOCKED_FLAGS_MESSAGE = "Remote policy blocked this command in daemon mode."
REMOTE_BLOCKED_FLAGS = (
    "--mail",
    "--open",
    "-tl",
    "--terminal-lines",
    "--delete-messages",
    "--delete-sessions",
    "--all",
    "--clean-session-research",
    "--add-model",
    "--edit-model",
    "--clear-memories",
    "--delete-memory",
    "--xmpp-daemon",
    "--xmpp-menubar-child",
    "--edit-daemon",
    "--completion-script",
)
INLINE_TOML_PATTERN = re.compile(
    r"(?is)(?P<filename>[a-zA-Z0-9_\-]+\.toml)\s*```toml\s*(?P<content>.{0,65536}?)```"
)
POINTER_PATTERN = re.compile(r"#(it|i|at|a)(\d+)\b", re.IGNORECASE)
_SUMMARIZATION_MODEL_OVERRIDE_LOCK = threading.Lock()

_HELP_TEXT = """\
asky XMPP Help

--- Session ---
/session                            Show session help + recent sessions
/session new                        Create and switch to a new session
/session child                      Create child session (inherit current overrides)
/session clear                      Clear conversation messages (keeps transcripts/media)
/session <id|name>                  Switch to existing session by id or name

--- Transcripts ---
transcript list [N]                 List recent audio/image transcripts (default 20)
transcript show <id|#atN>           Show full transcript text
transcript use <id|#atN>            Run transcript as a query
transcript clear                    Delete all transcripts for this conversation

--- Media Pointers (use in queries) ---
#aN                                 Audio file N as file path
#atN                                Audio transcript N as text
#iN                                 Image file N as file path
#itN                                Image transcript N as text

--- Asky Commands ---
-H [N], --history [N]               Show last N query summaries (default 10)
-pa ID, --print-answer ID           Print full answer for history ID(s)
-ps SEL, --print-session SEL        Print session content by ID or name
-sh [N], --session-history [N]      List recent sessions (default 10)
-ss NAME, --sticky-session NAME     Create and activate a named session
-rs NAME, --resume-session NAME     Resume existing session by ID or name
-r [CORPUS], --research [CORPUS]    Enable research mode (optional local corpus pointer)
-s, --summarize                     Enable summarize mode
-L, --lean                          Disable pre-LLM source shortlisting
-t N, --turns N                     Set max turn count for this session
-em, --elephant-mode                Enable automatic memory extraction
-sp TEXT, --system-prompt TEXT      Override system prompt for this run
-m ALIAS, --model ALIAS             Select model alias
-c [ID], --continue-chat [ID]       Continue from history ID (omit for last)
--shortlist auto|on|off             Control source shortlisting behavior
-off TOOL, --tool-off TOOL          Disable a specific LLM tool for this run
--list-tools                        List all available tools
--query-corpus QUERY                Query research corpus directly (no model)
--summarize-section [QUERY]         Summarize a corpus section (no model)
--list-memories                     List saved user memories

--- Prompt Aliases ---
/                                   List all configured prompt aliases
/name [query]                       Expand alias and run as query
/prefix                             List aliases matching that prefix

--- Command Presets ---
\\presets                           List configured command presets
\\name [args]                       Run named command preset with optional args

--- Config Override ---
Send a TOML block to apply session-scoped config overrides:
  general.toml
  ```toml
  [general]
  default_model = "gpt-4o"
  ```
Supported files: general.toml, user.toml\
"""


def build_help_text() -> str:
    """Return the full XMPP command help text."""
    return _HELP_TEXT


class CommandExecutor:
    """Execute parsed asky commands for one authorized sender or room."""

    def __init__(
        self,
        transcript_manager: TranscriptManager,
        double_verbose: bool = False,
        plugin_runtime: Optional["PluginRuntime"] = None,
    ):
        self.transcript_manager = transcript_manager
        self.session_profile_manager = transcript_manager.session_profile_manager
        self.double_verbose = double_verbose
        self.plugin_runtime = plugin_runtime
        self._pending_clear: dict[str, tuple[str, Optional[str]]] = {}

    def get_interface_command_reference(self) -> str:
        """Return command-surface guidance for interface planner prompting."""
        lines = [
            "Remote command surface (emit as command_text):",
            "- history: --history <count>, --print-answer <ids>",
            "- sessions: --print-session <selector>, --session-history [count]",
            "- daemon session switch: /session, /session new, /session child, /session <id|name>",
            "- research/manual corpus: --query-corpus <query> [--query-corpus-max-sources N] [--query-corpus-max-chunks N]",
            "- section summary: --summarize-section [SECTION_QUERY] [--section-source SOURCE] [--section-id ID] [--section-detail balanced|max|compact] [--section-max-chunks N]",
            "- research/profile toggles: -r [CORPUS_POINTER], --shortlist auto|on|off, -L",
            "- transcript namespace: transcript list [limit], transcript show <id>, transcript use <id>, transcript clear",
            "- pointer refs in queries: #iN image file, #itN image transcript, #aN audio file, #atN audio transcript",
            "- plain asky query text can be emitted as action_type=query",
            "Remote policy blocked flags/operations:",
            f"- {', '.join(REMOTE_BLOCKED_FLAGS)}",
        ]
        return "\n".join(lines)

    def execute_session_command(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        command_text: str,
        conversation_key: str = "",
    ) -> str:
        """Execute /session command surface scoped to current conversation."""
        tokens = _split_command_tokens(command_text)
        if not tokens or tokens[0] != SESSION_COMMAND_TOKEN:
            return "Error: invalid /session command."
        if len(tokens) == 1:
            return self._render_session_help()

        action = str(tokens[1] or "").strip().lower()
        if action == "new":
            session_id = self.session_profile_manager.create_new_conversation_session(
                room_jid=room_jid,
                jid=jid,
                inherit_current=False,
            )
            return f"Switched to new session {session_id}."
        if action == "child":
            session_id = self.session_profile_manager.create_new_conversation_session(
                room_jid=room_jid,
                jid=jid,
                inherit_current=True,
            )
            return f"Switched to child session {session_id} (inherited overrides)."
        if action == "clear":
            return self._request_session_clear(
                jid=jid, room_jid=room_jid, conversation_key=conversation_key
            )

        selector = " ".join(tokens[1:]).strip()
        session_id, error = self.session_profile_manager.switch_conversation_session(
            room_jid=room_jid,
            jid=jid,
            selector=selector,
        )
        if error:
            return f"Error: {error}"
        return f"Switched to session {session_id}."

    def execute_command_text(
        self,
        *,
        jid: str,
        command_text: str,
        room_jid: Optional[str] = None,
    ) -> str:
        """Execute one command text and return response string."""
        tokens = _split_command_tokens(command_text)
        if not tokens:
            return "Error: empty command."
        if tokens[0].lower() in HELP_COMMAND_TOKENS:
            return build_help_text()
        if tokens[0] == TRANSCRIPT_COMMAND:
            return self._handle_transcript_command(
                jid=jid,
                room_jid=room_jid,
                tokens=tokens[1:],
            )
        return self._execute_asky_tokens(
            jid=jid,
            room_jid=room_jid,
            tokens=tokens,
        )

    def execute_query_text(
        self,
        *,
        jid: str,
        query_text: str,
        room_jid: Optional[str] = None,
    ) -> str:
        """Execute a plain query in sender/room-scoped persistent session."""
        session_id = self._resolve_session_id(jid=jid, room_jid=room_jid)
        profile = self.session_profile_manager.get_effective_profile(
            session_id=session_id
        )
        prepared_query, immediate_response = self._prepare_query_text(
            raw_query=query_text,
            verbose=False,
            prompt_map=profile.user_prompts,
            conversation_id=str(room_jid or jid or "").strip(),
        )
        if immediate_response is not None:
            return immediate_response
        return self._run_query_with_args(
            jid=jid,
            room_jid=room_jid,
            args=argparse.Namespace(
                model=None,
                summarize=False,
                verbose=False,
                open=False,
                continue_ids=None,
                sticky_session=None,
                resume_session=None,
                lean=False,
                tool_off=[],
                elephant_mode=False,
                turns=None,
                research=False,
                research_flag_provided=False,
                research_source_mode=None,
                replace_research_corpus=False,
                local_corpus=None,
                shortlist="auto",
                system_prompt=None,
                terminal_lines=None,
            ),
            query_text=prepared_query or "",
            session_id=session_id,
            profile=profile,
        )

    def ensure_room_binding(self, room_jid: str) -> int:
        """Ensure room has a persisted bound session and return session id."""
        return self.transcript_manager.get_or_create_room_session_id(room_jid)

    def is_room_bound(self, room_jid: str) -> bool:
        """Return whether room has a persisted bound session."""
        return self.transcript_manager.is_room_bound(room_jid)

    def list_bound_room_jids(self) -> list[str]:
        """List persisted bound room JIDs."""
        return self.transcript_manager.list_bound_room_jids()

    def apply_toml_content(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        filename: str,
        content: str,
    ) -> str:
        """Apply inline/uploaded TOML override content for current conversation."""
        session_id = self._resolve_session_id(jid=jid, room_jid=room_jid)
        result = self.session_profile_manager.apply_override_file(
            session_id=session_id,
            filename=filename,
            content=content,
        )
        if result.error:
            return f"Error: {result.error}"

        lines = [
            f"Applied {result.filename} override to session {session_id}.",
        ]
        if result.applied_keys:
            lines.append("Applied keys: " + ", ".join(result.applied_keys))
        else:
            lines.append("Applied keys: (none)")
        if result.ignored_keys:
            lines.append("Ignored keys: " + ", ".join(result.ignored_keys))
        return "\n".join(lines)

    def apply_toml_url(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        url: str,
    ) -> str:
        """Download TOML from URL and apply as conversation-scoped override."""
        normalized_url = str(url or "").strip()
        if not normalized_url:
            return "Error: TOML URL is required."
        filename = _filename_from_url(normalized_url)
        if not filename:
            return "Error: Could not determine TOML filename from URL."
        if not filename.endswith(".toml"):
            return "Error: Uploaded URL does not reference a .toml file."
        try:
            content = _download_text_file(
                normalized_url,
                timeout_seconds=TOML_DOWNLOAD_TIMEOUT_SECONDS,
                max_bytes=MAX_TOML_DOWNLOAD_BYTES,
            )
        except Exception as exc:
            return f"Error: failed to download TOML file: {exc}"
        return self.apply_toml_content(
            jid=jid,
            room_jid=room_jid,
            filename=filename,
            content=content,
        )

    def apply_inline_toml_if_present(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        body: str,
    ) -> Optional[str]:
        """Detect inline TOML payload and apply it when present."""
        normalized = str(body or "").strip()
        if not normalized:
            return None
        match = INLINE_TOML_PATTERN.search(normalized)
        if not match:
            return None
        filename = str(match.group("filename") or "").strip()
        content = str(match.group("content") or "")
        if not filename:
            return "Error: Inline TOML filename is required."
        return self.apply_toml_content(
            jid=jid,
            room_jid=room_jid,
            filename=filename,
            content=content,
        )

    def _execute_asky_tokens(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        tokens: list[str],
    ) -> str:
        try:
            args = parse_args(tokens)
        except SystemExit:
            return "Error: invalid command syntax."

        policy_error = self._validate_remote_policy(args)
        if policy_error:
            return policy_error

        # Resolve research corpus token behavior from CLI semantics.
        try:
            research_arg = getattr(args, "research", False)
            (
                research_enabled,
                corpus_paths,
                leftover,
                source_mode,
                replace_corpus,
            ) = _resolve_research_corpus(research_arg)
            args.research = research_enabled
            args.local_corpus = corpus_paths
            args.research_flag_provided = (
                research_arg is not False and research_arg is not None
            )
            args.research_source_mode = source_mode
            args.replace_research_corpus = replace_corpus
            if leftover:
                args.query = [leftover] + (list(getattr(args, "query", []) or []))
        except ValueError as exc:
            return f"Error: {exc}"

        manual_corpus_query = _manual_corpus_query_arg(args)
        manual_section_query = _manual_section_query_arg(args)
        session_id = self._resolve_session_id(jid=jid, room_jid=room_jid)
        profile = self.session_profile_manager.get_effective_profile(
            session_id=session_id
        )

        init_db()

        if getattr(args, "prompts", False):
            return self._render_prompt_list(prompt_map=profile.user_prompts)
        if getattr(args, "history", None) is not None:
            return _capture_output(history.show_history, args.history)
        if getattr(args, "print_ids", None):
            return _capture_output(
                history.print_answers,
                args.print_ids,
                args.summarize,
                False,
                None,
                None,
            )
        if getattr(args, "print_session", None):
            return _capture_output(
                sessions.print_session_command,
                args.print_session,
                False,
                None,
                None,
            )
        if getattr(args, "session_history", None) is not None:
            return _capture_output(
                sessions.show_session_history_command, args.session_history
            )
        if manual_corpus_query:
            return _capture_output(
                research_commands.run_manual_corpus_query_command,
                query=manual_corpus_query,
                explicit_targets=getattr(args, "local_corpus", None),
                max_sources=int(getattr(args, "query_corpus_max_sources", 20)),
                max_chunks=int(getattr(args, "query_corpus_max_chunks", 3)),
            )
        if manual_section_query is not None:
            return _capture_output(
                section_commands.run_summarize_section_command,
                section_query=manual_section_query or None,
                section_source=getattr(args, "section_source", None),
                section_detail=str(getattr(args, "section_detail", "balanced")),
                section_max_chunks=getattr(args, "section_max_chunks", None),
                explicit_targets=getattr(args, "local_corpus", None),
            )

        query_tokens = list(getattr(args, "query", []) or [])
        if not query_tokens:
            return "Error: query is required."
        raw_query = " ".join(query_tokens).strip()
        query_text, immediate_response = self._prepare_query_text(
            raw_query=raw_query,
            verbose=bool(args.verbose),
            prompt_map=profile.user_prompts,
            conversation_id=str(room_jid or jid or "").strip(),
        )
        if immediate_response is not None:
            return immediate_response
        return self._run_query_with_args(
            jid=jid,
            room_jid=room_jid,
            args=args,
            query_text=query_text or "",
            session_id=session_id,
            profile=profile,
        )

    def _run_query_with_args(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        args: argparse.Namespace,
        query_text: str,
        session_id: int,
        profile,
    ) -> str:
        _ = room_jid  # explicit for readability in callsites; session_id already resolved.
        model_alias = (
            getattr(args, "model", None) or profile.default_model or DEFAULT_MODEL
        )
        double_verbose = self.double_verbose or bool(
            getattr(args, "double_verbose", False)
        )
        client = AskyClient(
            AskyConfig(
                model_alias=model_alias,
                summarize=bool(getattr(args, "summarize", False)),
                verbose=bool(getattr(args, "verbose", False)) or double_verbose,
                double_verbose=double_verbose,
                open_browser=False,
                research_mode=bool(getattr(args, "research", False)),
                disabled_tools=set(),
                system_prompt_override=getattr(args, "system_prompt", None),
            ),
            plugin_runtime=self.plugin_runtime,
        )
        request = AskyTurnRequest(
            query_text=query_text,
            continue_ids=getattr(args, "continue_ids", None),
            summarize_context=bool(getattr(args, "summarize", False)),
            resume_session_term=str(session_id),
            lean=bool(getattr(args, "lean", False)),
            local_corpus_paths=getattr(args, "local_corpus", None),
            save_history=True,
            elephant_mode=bool(getattr(args, "elephant_mode", False)),
            max_turns=getattr(args, "turns", None),
            research_flag_provided=bool(getattr(args, "research_flag_provided", False)),
            research_source_mode=getattr(args, "research_source_mode", None),
            replace_research_corpus=bool(
                getattr(args, "replace_research_corpus", False)
            ),
            shortlist_override=str(getattr(args, "shortlist", "auto")),
        )
        from rich.console import Console

        verbose_output_cb = (
            build_verbose_output_callback(Console(highlight=False))
            if double_verbose
            else None
        )
        with _summarization_model_override(profile.summarization_model):
            result = client.run_turn(request, verbose_output_callback=verbose_output_cb)
        if result.halted:
            reason = result.halt_reason or "unknown"
            notices = "\n".join(result.notices) if result.notices else ""
            if notices:
                return f"Halted: {reason}\n{notices}"
            return f"Halted: {reason}"
        return result.final_answer or "(no response)"

    def _prepare_query_text(
        self,
        *,
        raw_query: str,
        verbose: bool,
        prompt_map: dict[str, str],
        conversation_id: str,
    ) -> tuple[Optional[str], Optional[str]]:
        query = str(raw_query or "")
        try:
            query = self._resolve_query_pointers(
                query=query,
                conversation_id=conversation_id,
            )
        except ValueError as exc:
            return None, f"Error: {exc}"
        if "/" in query:
            utils.load_custom_prompts(prompt_map=prompt_map)
        expanded_query = utils.expand_query_text(
            query,
            verbose=bool(verbose),
            prompt_map=prompt_map,
        )
        if expanded_query.startswith("/"):
            first_part = expanded_query.split(maxsplit=1)[0]
            if first_part == "/":
                return None, self._render_prompt_list(prompt_map=prompt_map)
            prefix = first_part[1:]
            if prefix and prefix not in prompt_map:
                return None, self._render_prompt_list(
                    prompt_map=prompt_map,
                    filter_prefix=prefix,
                )
        return expanded_query, None

    def _resolve_query_pointers(self, *, query: str, conversation_id: str) -> str:
        normalized_conversation_id = str(conversation_id or "").strip()
        if not normalized_conversation_id:
            return query

        def _replace(match: re.Match[str]) -> str:
            pointer_type = str(match.group(1) or "").lower()
            pointer_id = int(match.group(2))
            if pointer_type == "it":
                record = self.transcript_manager.get_image_for_jid(
                    normalized_conversation_id,
                    pointer_id,
                )
                if record is None:
                    raise ValueError(f"image transcript #it{pointer_id} not found.")
                text = str(record.transcript_text or "").strip()
                if not text:
                    raise ValueError(f"image transcript #it{pointer_id} is empty.")
                self.transcript_manager.mark_image_used(
                    jid=normalized_conversation_id,
                    image_id=pointer_id,
                )
                return text
            if pointer_type == "i":
                record = self.transcript_manager.get_image_for_jid(
                    normalized_conversation_id,
                    pointer_id,
                )
                if record is None:
                    raise ValueError(f"image #i{pointer_id} not found.")
                image_path = str(record.image_path or "").strip()
                if not image_path:
                    raise ValueError(f"image #i{pointer_id} has no file path.")
                return image_path
            if pointer_type == "at":
                record = self.transcript_manager.get_for_jid(
                    normalized_conversation_id,
                    pointer_id,
                )
                if record is None:
                    raise ValueError(f"audio transcript #at{pointer_id} not found.")
                text = str(record.transcript_text or "").strip()
                if not text:
                    raise ValueError(f"audio transcript #at{pointer_id} is empty.")
                self.transcript_manager.mark_used(
                    jid=normalized_conversation_id,
                    transcript_id=pointer_id,
                )
                return text
            if pointer_type == "a":
                record = self.transcript_manager.get_for_jid(
                    normalized_conversation_id,
                    pointer_id,
                )
                if record is None:
                    raise ValueError(f"audio #a{pointer_id} not found.")
                audio_path = str(record.audio_path or "").strip()
                if not audio_path:
                    raise ValueError(f"audio #a{pointer_id} has no file path.")
                return audio_path
            return match.group(0)

        return POINTER_PATTERN.sub(_replace, query)

    def _render_prompt_list(
        self,
        *,
        prompt_map: dict[str, str],
        filter_prefix: Optional[str] = None,
    ) -> str:
        if not prompt_map:
            return "No prompt aliases configured."
        if filter_prefix:
            filtered = {
                key: value
                for key, value in prompt_map.items()
                if str(key).startswith(filter_prefix)
            }
            if not filtered:
                filtered = prompt_map
        else:
            filtered = prompt_map
        lines = ["Prompt Aliases:"]
        for key in sorted(filtered.keys()):
            value = str(filtered[key] or "").strip().replace("\n", " ")
            if len(value) > 90:
                value = value[:87] + "..."
            lines.append(f"  /{key}: {value}")
        return "\n".join(lines)

    def _validate_remote_policy(self, args: argparse.Namespace) -> Optional[str]:
        blocked = any(
            [
                bool(getattr(args, "open", False)),
                bool(getattr(args, "mail_recipients", None)),
                getattr(args, "terminal_lines", None) is not None,
                bool(getattr(args, "delete_messages", None)),
                bool(getattr(args, "delete_sessions", None)),
                bool(getattr(args, "all", False)),
                bool(getattr(args, "clean_session_research", None)),
                bool(getattr(args, "add_model", False)),
                getattr(args, "edit_model", None) is not None,
                bool(getattr(args, "clear_memories", False)),
                getattr(args, "delete_memory", None) is not None,
                bool(getattr(args, "xmpp_daemon", False)),
                bool(getattr(args, "xmpp_menubar_child", False)),
                bool(getattr(args, "edit_daemon", False)),
                bool(getattr(args, "completion_script", None)),
            ]
        )
        if blocked:
            return f"Error: {REMOTE_BLOCKED_FLAGS_MESSAGE}"
        return None

    def _handle_transcript_command(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        tokens: list[str],
    ) -> str:
        conversation_id = str(room_jid or jid or "").strip()
        if not conversation_id:
            return "Error: conversation identifier is missing."
        if not tokens:
            return TRANSCRIPT_HELP

        command = str(tokens[0]).lower()
        if command == "list":
            limit = 20
            if len(tokens) >= 2:
                try:
                    limit = max(1, int(tokens[1]))
                except ValueError:
                    return "Error: transcript list limit must be an integer."
            records = self.transcript_manager.list_for_jid(conversation_id, limit=limit)
            image_records = self.transcript_manager.list_images_for_jid(
                conversation_id, limit=limit
            )
            if not records and not image_records:
                return "No transcripts found."
            lines = ["Transcripts:"]
            for record in records:
                preview = (record.transcript_text or "").strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(
                    f"  #at{record.session_transcript_id} (audio #a{record.session_transcript_id}): "
                    f"{record.status} used={int(record.used)} {preview}"
                )
            for record in image_records:
                preview = (record.transcript_text or "").strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(
                    f"  #it{record.session_image_id} (image #i{record.session_image_id}): "
                    f"{record.status} used={int(record.used)} {preview}"
                )
            return "\n".join(lines)

        if command == "show":
            if len(tokens) < 2:
                return "Error: transcript show requires an id."
            try:
                transcript_id = _parse_prefixed_index(tokens[1], "at")
            except ValueError:
                return "Error: transcript id must be an integer or #atN."
            record = self.transcript_manager.get_for_jid(conversation_id, transcript_id)
            if not record:
                return f"Error: transcript {transcript_id} not found."
            return (
                f"Transcript #at{record.session_transcript_id} of audio #a{record.session_transcript_id} ({record.status})\n"
                f"{record.transcript_text or ''}"
            )

        if command == "use":
            if len(tokens) < 2:
                return "Error: transcript use requires an id."
            try:
                transcript_id = _parse_prefixed_index(tokens[1], "at")
            except ValueError:
                return "Error: transcript id must be an integer or #atN."
            record = self.transcript_manager.get_for_jid(conversation_id, transcript_id)
            if not record:
                return f"Error: transcript {transcript_id} not found."
            if record.status != "completed":
                return f"Error: transcript {transcript_id} is not completed."
            self.transcript_manager.mark_used(
                jid=conversation_id, transcript_id=transcript_id
            )
            if not record.transcript_text.strip():
                return f"Error: transcript {transcript_id} has no text."
            return self.execute_query_text(
                jid=jid,
                room_jid=room_jid,
                query_text=record.transcript_text,
            )

        if command == "clear":
            deleted = self.transcript_manager.clear_for_jid(conversation_id)
            return f"Deleted {len(deleted)} transcript(s)."

        return TRANSCRIPT_HELP

    def _resolve_session_id(self, *, jid: str, room_jid: Optional[str]) -> int:
        return self.session_profile_manager.resolve_conversation_session_id(
            room_jid=room_jid,
            jid=jid,
        )

    def _request_session_clear(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        conversation_key: str,
    ) -> str:
        session_id = self._resolve_session_id(jid=jid, room_jid=room_jid)
        count = self.session_profile_manager.count_session_messages(session_id)
        if count == 0:
            return f"Session {session_id} has no messages to clear."
        key = str(conversation_key or jid or "").strip()
        self._pending_clear[key] = (jid, room_jid)
        return (
            f"Session {session_id} has {count} message(s). "
            f"Reply 'yes' to clear all conversation messages.\n"
            f"Transcripts and media files are not affected."
        )

    def confirm_session_clear(self, *, jid: str, room_jid: Optional[str]) -> str:
        """Perform session message deletion after confirmation."""
        session_id = self._resolve_session_id(jid=jid, room_jid=room_jid)
        deleted = self.session_profile_manager.clear_conversation(session_id)
        return f"Cleared {deleted} message(s) from session {session_id}."

    def consume_pending_clear(
        self, conversation_key: str, *, consume: bool
    ) -> Optional[tuple[str, Optional[str]]]:
        """Return pending clear entry for conversation_key if one exists.

        If consume is True, remove it from the map.
        """
        key = str(conversation_key or "").strip()
        entry = self._pending_clear.get(key)
        if entry is not None and consume:
            self._pending_clear.pop(key, None)
        return entry

    def _render_session_help(self) -> str:
        listed = self.session_profile_manager.list_recent_sessions(
            limit=SESSION_LIST_LIMIT
        )
        lines = [SESSION_HELP, "", f"Latest {SESSION_LIST_LIMIT} Sessions:"]
        if not listed:
            lines.append("  (none)")
            return "\n".join(lines)
        for item in listed:
            lines.append(f"  {item.id}: {item.name or '(unnamed)'}")
        return "\n".join(lines)


def _split_command_tokens(command_text: str) -> list[str]:
    import shlex

    try:
        return shlex.split(command_text, posix=True)
    except ValueError:
        return []


def _parse_prefixed_index(raw: str, prefix: str) -> int:
    value = str(raw or "").strip().lower()
    normalized_prefix = str(prefix or "").strip().lower()
    if value.startswith("#"):
        expected = f"#{normalized_prefix}"
        if not value.startswith(expected):
            raise ValueError("invalid prefix")
        value = value[len(expected):]
    return int(value)


def _capture_output(fn, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        fn(*args, **kwargs)
    return buffer.getvalue().strip() or "(ok)"


def _filename_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = os.path.basename(parsed.path or "")
    return str(path or "").strip().lower()


def _download_text_file(url: str, *, timeout_seconds: int, max_bytes: int) -> str:
    with requests.get(url, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        deadline = time.monotonic() + timeout_seconds
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("Download exceeded time limit")
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(
                    f"file exceeds size limit ({total} > {max_bytes} bytes)"
                )
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


@contextmanager
def _summarization_model_override(alias: str):
    normalized = str(alias or "").strip()
    if not normalized:
        yield
        return
    with _SUMMARIZATION_MODEL_OVERRIDE_LOCK:
        original = summarization.SUMMARIZATION_MODEL
        summarization.SUMMARIZATION_MODEL = normalized
        try:
            yield
        finally:
            summarization.SUMMARIZATION_MODEL = original

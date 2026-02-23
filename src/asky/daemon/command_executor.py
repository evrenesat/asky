"""Command execution bridge for daemon mode."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Optional

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.cli import history, prompts, sessions, utils
from asky.cli.main import (
    _manual_corpus_query_arg,
    _manual_section_query_arg,
    _resolve_research_corpus,
    parse_args,
    research_commands,
    section_commands,
)
from asky.config import DEFAULT_MODEL
from asky.daemon.transcript_manager import TranscriptManager
from asky.storage import init_db

TRANSCRIPT_COMMAND = "transcript"
TRANSCRIPT_HELP = (
    "Transcript commands:\n"
    "  transcript list [limit]\n"
    "  transcript show <id>\n"
    "  transcript use <id>\n"
    "  transcript clear"
)
REMOTE_BLOCKED_FLAGS_MESSAGE = (
    "Remote policy blocked this command in daemon mode."
)
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
    "--completion-script",
)


class CommandExecutor:
    """Execute parsed asky commands for one authorized sender."""

    def __init__(self, transcript_manager: TranscriptManager):
        self.transcript_manager = transcript_manager

    def get_interface_command_reference(self) -> str:
        """Return command-surface guidance for interface planner prompting."""
        lines = [
            "Remote command surface (emit as command_text):",
            "- history: --history <count>, --print-answer <ids>",
            "- sessions: --print-session <selector>, --session-history [count]",
            "- research/manual corpus: --query-corpus <query> [--query-corpus-max-sources N] [--query-corpus-max-chunks N]",
            "- section summary: --summarize-section [SECTION_QUERY] [--section-source SOURCE] [--section-id ID] [--section-detail balanced|max|compact] [--section-max-chunks N]",
            "- research/profile toggles: -r [CORPUS_POINTER], --shortlist auto|on|off, -L",
            "- transcript namespace: transcript list [limit], transcript show <id>, transcript use <id>, transcript clear",
            "- plain asky query text can be emitted as action_type=query",
            "Remote policy blocked flags/operations:",
            f"- {', '.join(REMOTE_BLOCKED_FLAGS)}",
        ]
        return "\n".join(lines)

    def execute_command_text(self, *, jid: str, command_text: str) -> str:
        """Execute one command text and return response string."""
        tokens = _split_command_tokens(command_text)
        if not tokens:
            return "Error: empty command."
        if tokens[0] == TRANSCRIPT_COMMAND:
            return self._handle_transcript_command(jid=jid, tokens=tokens[1:])
        return self._execute_asky_tokens(jid=jid, tokens=tokens)

    def execute_query_text(self, *, jid: str, query_text: str) -> str:
        """Execute a plain query in sender-scoped persistent session."""
        return self._run_query_with_args(
            jid=jid,
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
            query_text=query_text,
        )

    def _execute_asky_tokens(self, *, jid: str, tokens: list[str]) -> str:
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

        init_db()

        if getattr(args, "prompts", False):
            utils.load_custom_prompts()
            return _capture_output(prompts.list_prompts)
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
            return _capture_output(sessions.show_session_history_command, args.session_history)
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
        if raw_query.startswith("/"):
            utils.load_custom_prompts()
        query_text = utils.expand_query_text(raw_query, verbose=bool(args.verbose))
        return self._run_query_with_args(jid=jid, args=args, query_text=query_text)

    def _run_query_with_args(
        self,
        *,
        jid: str,
        args: argparse.Namespace,
        query_text: str,
    ) -> str:
        session_id = self.transcript_manager.get_or_create_session_id(jid)
        model_alias = getattr(args, "model", None) or DEFAULT_MODEL
        client = AskyClient(
            AskyConfig(
                model_alias=model_alias,
                summarize=bool(getattr(args, "summarize", False)),
                verbose=bool(getattr(args, "verbose", False)),
                open_browser=False,
                research_mode=bool(getattr(args, "research", False)),
                disabled_tools=set(),
                system_prompt_override=getattr(args, "system_prompt", None),
            )
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
            research_flag_provided=bool(
                getattr(args, "research_flag_provided", False)
            ),
            research_source_mode=getattr(args, "research_source_mode", None),
            replace_research_corpus=bool(
                getattr(args, "replace_research_corpus", False)
            ),
            shortlist_override=str(getattr(args, "shortlist", "auto")),
        )
        result = client.run_turn(request)
        if result.halted:
            reason = result.halt_reason or "unknown"
            notices = "\n".join(result.notices) if result.notices else ""
            if notices:
                return f"Halted: {reason}\n{notices}"
            return f"Halted: {reason}"
        return result.final_answer or "(no response)"

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
                bool(getattr(args, "completion_script", None)),
            ]
        )
        if blocked:
            return f"Error: {REMOTE_BLOCKED_FLAGS_MESSAGE}"
        return None

    def _handle_transcript_command(self, *, jid: str, tokens: list[str]) -> str:
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
            records = self.transcript_manager.list_for_jid(jid, limit=limit)
            if not records:
                return "No transcripts found."
            lines = ["Transcripts:"]
            for record in records:
                preview = (record.transcript_text or "").strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(
                    f"  {record.session_transcript_id}: {record.status} used={int(record.used)} {preview}"
                )
            return "\n".join(lines)

        if command == "show":
            if len(tokens) < 2:
                return "Error: transcript show requires an id."
            try:
                transcript_id = int(tokens[1])
            except ValueError:
                return "Error: transcript id must be an integer."
            record = self.transcript_manager.get_for_jid(jid, transcript_id)
            if not record:
                return f"Error: transcript {transcript_id} not found."
            return (
                f"Transcript {record.session_transcript_id} ({record.status})\n"
                f"{record.transcript_text or ''}"
            )

        if command == "use":
            if len(tokens) < 2:
                return "Error: transcript use requires an id."
            try:
                transcript_id = int(tokens[1])
            except ValueError:
                return "Error: transcript id must be an integer."
            record = self.transcript_manager.get_for_jid(jid, transcript_id)
            if not record:
                return f"Error: transcript {transcript_id} not found."
            if record.status != "completed":
                return f"Error: transcript {transcript_id} is not completed."
            self.transcript_manager.mark_used(jid=jid, transcript_id=transcript_id)
            if not record.transcript_text.strip():
                return f"Error: transcript {transcript_id} has no text."
            return self.execute_query_text(jid=jid, query_text=record.transcript_text)

        if command == "clear":
            deleted = self.transcript_manager.clear_for_jid(jid)
            return f"Deleted {len(deleted)} transcript(s)."

        return TRANSCRIPT_HELP


def _split_command_tokens(command_text: str) -> list[str]:
    import shlex

    try:
        return shlex.split(command_text, posix=True)
    except ValueError:
        return []


def _capture_output(fn, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        fn(*args, **kwargs)
    return buffer.getvalue().strip() or "(ok)"

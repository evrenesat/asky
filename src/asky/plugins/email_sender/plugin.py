"""EmailSenderPlugin: sends the final answer via email on POST_TURN_RENDER."""

from __future__ import annotations

import logging
from typing import Optional

from asky.plugins.base import AskyPlugin, CapabilityCategory, CLIContribution, PluginContext
from asky.plugins.hook_types import POST_TURN_RENDER, PostTurnRenderContext

logger = logging.getLogger(__name__)


class EmailSenderPlugin(AskyPlugin):
    """Built-in plugin that emails the final answer when --sendmail is used."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

    @classmethod
    def get_cli_contributions(cls) -> list[CLIContribution]:
        return [
            CLIContribution(
                category=CapabilityCategory.OUTPUT_DELIVERY,
                flags=("--sendmail",),
                kwargs=dict(
                    metavar="RECIPIENTS",
                    help="Send the final answer via email to comma-separated addresses.",
                ),
            ),
            CLIContribution(
                category=CapabilityCategory.OUTPUT_DELIVERY,
                flags=("--subject",),
                kwargs=dict(
                    metavar="SUBJECT",
                    help="Subject line for --sendmail. Defaults to the answer title.",
                ),
            ),
        ]

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            POST_TURN_RENDER,
            self._on_post_turn_render,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._context = None

    def _on_post_turn_render(self, ctx: PostTurnRenderContext) -> None:
        cli_args = ctx.cli_args
        if cli_args is None:
            return
        recipients_raw = getattr(cli_args, "sendmail", None)
        if not ctx.final_answer or not recipients_raw:
            return

        from asky.plugins.email_sender.sender import send_email

        recipients = [x.strip() for x in recipients_raw.split(",") if x.strip()]
        query_text = ctx.request.query_text if ctx.request is not None else ""
        subject = getattr(cli_args, "subject", None) or ctx.answer_title or query_text[:80] or "asky Result"
        send_email(recipients, subject, ctx.final_answer)

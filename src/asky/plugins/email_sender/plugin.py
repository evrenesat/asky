"""EmailSenderPlugin: sends the final answer via email on POST_TURN_RENDER."""

from __future__ import annotations

import logging
from typing import Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import POST_TURN_RENDER, PostTurnRenderContext

logger = logging.getLogger(__name__)


class EmailSenderPlugin(AskyPlugin):
    """Built-in plugin that emails the final answer when --mail is used."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

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
        recipients_raw = getattr(cli_args, "mail_recipients", None)
        if not ctx.final_answer or not recipients_raw:
            return

        from asky.email_sender import send_email

        recipients = [x.strip() for x in recipients_raw.split(",")]
        query_text = ctx.request.query_text if ctx.request is not None else ""
        subject = getattr(cli_args, "subject", None) or f"asky Result: {query_text[:50]}"
        send_email(recipients, subject, ctx.final_answer)

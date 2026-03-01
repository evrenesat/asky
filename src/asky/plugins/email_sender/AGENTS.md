# Email Sender Plugin

This directory contains the `email_sender` built-in plugin, which handles outgoing email dispatch for the `--mail` CLI feature.

## Responsibilities
- Registers the `--mail` CLI argument hook.
- Handles the `POST_TURN_RENDER` hook to dispatch the final text response to the configured SMTP recipient.
- Loads SMTP credentials from configuration files and environment variables.
- Uses `smtplib` and `email.mime` for message construction and delivery.

## Interaction with Plugin Runtime
- Activated via `plugins.toml` when `plugin.email_sender.enabled = true`.
- Registers hooks via `@hook_registry.register`.
- Retrieves settings via `loader.get_settings()`.
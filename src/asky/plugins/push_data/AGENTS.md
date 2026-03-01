# Push Data Plugin

This directory contains the `push_data` built-in plugin, which handles forwarding LLM responses to external HTTP endpoints via the `--push-data` CLI feature.

## Responsibilities
- Registers the `--push-data` CLI argument hook.
- Handles the `POST_TURN_RENDER` hook to dispatch the final text response to the specified webhook or API URL.
- Manages HTTP requests (POST) using the `httpx` library.
- Formats payloads based on configuration (e.g., plain text vs JSON wrapper).

## Interaction with Plugin Runtime
- Activated via `plugins.toml` when `plugin.push_data.enabled = true`.
- Registers hooks via `@hook_registry.register`.
- Operates asynchronously (or blocks synchronously, depending on execution context) to deliver the payload after the primary turn finishes.
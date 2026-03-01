# Image Transcriber Plugin

Provides image captioning and transcription capabilities using multimodal LLMs.

## Key Components

- `ImageTranscriberService`: Core logic for downloading and captioning image files via `get_llm_msg`.
- `ImageTranscriberWorker`: Background thread pool for processing image transcription jobs asynchronously.
- `ImageTranscriberPlugin`: Hook-based integration for exposing capabilities, model tools, and corpus ingestion handlers.

## Hooks

- `PLUGIN_CAPABILITY_REGISTER`: Exposes `image_transcriber` capability (the service instance).
- `LOCAL_SOURCE_HANDLER_REGISTER`: Registers handlers for image file extensions.
- `TOOL_REGISTRY_BUILD`: Registers `transcribe_image_url` via `ToolRegistry.register(name, schema, executor)`. The executor accepts a single args dict and maps it to `url`/`prompt`.

## Tools

- `transcribe_image_url(url: str, prompt?: str)`: Describes or transcribes an image from a public HTTPS URL. Enforces HTTPS only.

## Configuration

Lives in `image_transcriber.toml`:
- `model_alias`: Multimodal model alias to use for captioning.
- `prompt_text`: Default prompt/question to ask the model (e.g. "Explain this image briefly.").
- `max_size_mb`: Max image file size (default: 20).
- `tools_enabled`: Whether to register LLM tools.
- `ingestion_enabled`: Whether to register local source handlers.

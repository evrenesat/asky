# Voice Transcriber Plugin

Provides audio transcription capabilities using platform-specific strategies (e.g. `mlx-whisper` on macOS).

## Key Components

- `VoiceTranscriberService`: Core logic for downloading and transcribing audio files.
- `VoiceTranscriberWorker`: Background thread pool for processing transcription jobs asynchronously.
- `VoiceTranscriberPlugin`: Hook-based integration for exposing capabilities, model tools, and corpus ingestion handlers.

## Hooks

- `PLUGIN_CAPABILITY_REGISTER`: Exposes `voice_transcriber` capability (the service instance).
- `LOCAL_SOURCE_HANDLER_REGISTER`: Registers handlers for audio file extensions.
- `TOOL_REGISTRY_BUILD`: Registers `transcribe_audio_url` tool.

## Tools

- `transcribe_audio_url(url: str, prompt?: str, language?: str)`: Transcribes an audio file from a public HTTPS URL. Enforces HTTPS only.

## Configuration

Lives in `voice_transcriber.toml`:
- `model`: Whisper model to use (default: `mlx-community/whisper-turbo-mlx`).
- `language`: Default language code.
- `max_size_mb`: Max audio file size (default: 500).
- `tools_enabled`: Whether to register LLM tools.
- `ingestion_enabled`: Whether to register local source handlers.

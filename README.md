<img src="https://github.com/evrenesat/asky/raw/main/assets/asky_icon.png" alt="asky icon" width="200" align="right">

<!-- <font size="6">**asky**</font> -->
<img src="https://github.com/evrenesat/asky/raw/main/assets/title.png" alt="asky title">

asky is an AI-powered web search CLI with LLM tool-calling capabilities and an optional XMPP remote-chat mode.

It (invoked as `asky` or `ask`) provides a command-line interface that brings AI-powered search and research capabilities directly to your terminal. It uses LLMs and tools to synthesize answers from the web (or from local files and CLI commands).

## The asky Mindset

**asky is a single-command application.** You provide a command, and you receive an output.

It intentionally avoids being a Terminal User Interface (TUI). While TUIs have their place, they can sometimes feel confusing and unintuitive for text-based conversational tasks. When using a terminal, the expectation is a straightforward, streamlined experience: input a command, read the output, and move on.

asky embraces this philosophy. It does not take over your screen. It feels like a native Unix tool that happens to be an AI agent, plugging seamlessly into your existing workflows.

## Key Features

- **Multi-Model Support**: Easily define and switch between various LLMs and providers that support OpenAI compatible APIs.
- **Deep Research Mode**: A specialized mode for an iterative, RAG-backed investigation across web sources and local data.
- **Tool-Calling Integration**: Models autonomously search the web, fetch URLs, and use the current date/time to provide accurate answers.
- **XMPP Remote Daemon (Optional)**: Run asky as a foreground XMPP client daemon (`asky --xmpp-daemon`) so authorized contacts can use asky from mobile/desktop XMPP apps.
- **Voice Transcription & Voice Commands (Optional)**: In XMPP daemon mode, voice attachments can be transcribed (`mlx-whisper`, macOS phase 1) and routed as transcript-driven commands/queries.
- **Custom Tools**: Expose any CLI command as a tool for the LLM.
- **User Memory (Elephant Mode)**: Cross-session persistent memory that allows the LLM to learn facts and preferences about you across different conversations.
- **Smart Context Management**: Automatically summarizes older conversation history to maximize context window usage.
- **File Prompts**: Load complex prompts directly from files using `file://` URIs.
- **Token Efficient**: It counts token usage and keeps the model informed about remaining context capacity.

## What XMPP Daemon Mode Means

When you run `asky --xmpp-daemon`, asky logs into an XMPP account and waits for direct chat messages.

- It behaves as an XMPP **client daemon** (not a full XMPP server).
- It only processes messages from configured allowlisted JIDs.
- It exposes asky command/query flows over chat, including presets.
- With voice enabled, audio attachments are transcribed and can be used as commands/queries.

## Documentation Index

The extensive details of asky's operation are documented in the following guides:

- [Configuration and Setup](./docs/configuration.md): Managing TOML config files, API keys, Model aliases, and Sessions.
- [XMPP Daemon Mode](./docs/xmpp_daemon.md): Remote daemon setup, allowlists, presets, voice transcription, and transcript commands.
- [Deep Research Mode (`-r`)](./docs/research_mode.md): Advanced web and local document research workflow.
- [User Memory & Elephant Mode (`-em`)](./docs/elephant_mode.md): Persistent cross-session global and session-scoped memory.
- [Custom Tools](./docs/custom_tools.md): Extending asky by allowing the LLM to run local CLI commands.
- [Library Usage Guide](./docs/library_usage.md): Programmatic usage (`asky.api`), including full configuration and request options.
- [Research Evaluation](./docs/research_eval.md): Guide for evaluating retrieval quality across models and parameters.

## Installation

```bash
pip install asky-cli
```

Or install from source:

```bash
pip install -e .
```

To enable the optional iTerm2 context integration:

```bash
pip install "asky-cli[iterm]"
# Or via uv
uv tool install "asky-cli[iterm]"
```

Optional daemon extras:

```bash
# XMPP daemon text mode
uv pip install "asky-cli[xmpp]"

# Voice transcription (mlx-whisper, macOS phase 1)
uv pip install "asky-cli[voice]"

# Combined daemon extras
uv pip install "asky-cli[daemon]"
```

## Basic Usage

```bash
# Basic query
asky what is the correct temperature for green tea

# Research Mode (Deep web & local search)
asky -r "Compare the latest iPhone vs Samsung flagship specs and reviews"

# Continue from a previous query
asky -c "~1" explain more

# Persistent Sessions
asky -ss "Project X" "Let's brainstorm architectures"

# Use a specific model
asky -m gf "Explain quantum entanglement"

# Run foreground XMPP daemon mode (optional)
asky --xmpp-daemon
```

```console
➜  ~ asky /wh delft
Dispatching tool call: web_search with args {'q': 'weather in Delft'}
Dispatching tool call: get_url_content with args {'urls': ...}

The weather in **Delft, South Holland, Netherlands** is currently **45°F and Cloudy with Showers in the Vicinity** (as of 4:20 pm CET).

Query completed in 3.88 seconds
```

Run `asky --help` for the full list of available commands and flags.

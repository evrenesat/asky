<img src="https://github.com/evrenesat/asky/raw/main/assets/asky_icon.png" alt="asky icon" width="200" align="right">

<!-- <font size="6">**asky**</font> -->
<img src="https://github.com/evrenesat/asky/raw/main/assets/title.png" alt="asky title">

asky is a command-line AI assistant with web search, local document Q&A, conversation history, and an optional XMPP remote-chat mode.

It runs as `asky` or `ask`. You give it a query, it gives you an answer.

## What you need to get started

- An API key for one LLM provider (Gemini, OpenAI, OpenRouter, or a local model via LM Studio)
- A search provider for web queries: [Serper](https://serper.dev) (2500 free requests) or a local [SearXNG](https://searxng.github.io/searxng/) instance

**New here?** Start with the [Quick Start guide](./docs/quickstart.md).

## Features

- **Multi-model support** - define model aliases for any OpenAI-compatible API endpoint and switch between them with `-m`.
- **Web search and tool calling** - the model can search the web, fetch URLs, and use the current date to answer questions. Tool calls are visible in the output.
- **Deep research mode** - iterative retrieval across web sources and local documents, with a vector-indexed local corpus for semantic search.
- **Document Q&A** - point asky at a PDF, EPUB, or folder of files and ask questions about the content. See [Document Q&A](./docs/document_qa.md).
- **Conversation history and sessions** - every query is saved locally. Resume any previous conversation with `-c`, or use named sticky sessions with `-ss`.
- **User memory** - save facts across sessions. asky injects relevant memories into future queries automatically.
- **Custom tools** - expose any local CLI command as a tool the model can call.
- **XMPP daemon mode** - run `asky --daemon` to log into an XMPP account and accept queries over chat from any XMPP client app (phone, desktop, etc.). Includes voice transcription on macOS.
- **macOS menu bar** - with `rumps` installed, daemon mode adds a menu bar icon for start/stop control and run-at-login.
- **Playwright browser plugin** - fetches pages using a real browser, useful for sites that block standard HTTP clients.
- **File prompts** - load a prompt from a file with `file://path/to/prompt.txt`.
- **Smart context management** - summarizes old conversation turns in the background to stay within model context limits.

## Installation

Recommended:

```bash
uv tool install asky-cli
```

With pip:

```bash
pip install asky-cli
```

From source:

```bash
uv pip install -e .
```

Optional extras:

```bash
# iTerm2 terminal context integration (macOS)
uv tool install "asky-cli[iterm2]"

# XMPP daemon (text only)
uv pip install "asky-cli[xmpp]"

# Voice transcription (macOS, mlx-whisper)
uv pip install "asky-cli[mlx-whisper]"

# macOS full bundle: iterm2 + mlx-whisper + rumps + slixmpp
uv pip install "asky-cli[mac]"

# Playwright browser plugin
uv pip install "asky-cli[playwright]"
```

## Basic Usage

```bash
# Basic query
asky what is the correct temperature for green tea

# Ask about a local document
asky -r path/to/report.pdf "What are the main conclusions?"

# Research mode - web sources
asky -r web "Compare the latest iPhone vs Samsung flagship specs"

# Continue from a previous query
asky -c "~1" explain more

# Persistent named session
asky -ss "Project X" "Let's plan the API structure"

# Use a specific model alias (defined in models.toml)
asky -m gf "Explain quantum entanglement"

# Run XMPP daemon (menu bar on macOS, foreground otherwise)
asky --daemon

# Edit daemon settings interactively
asky --config daemon edit

# Add or edit model aliases
asky --config model add
asky --config model edit gf

# History, sessions, memory
asky history list 20
asky session list
asky memory list
```

Example output for a query that uses web search:

```console
$ asky "What is the weather in Delft right now?"
Dispatching tool call: web_search with args {'q': 'weather Delft Netherlands'}
Dispatching tool call: get_url_content with args {'urls': [...]}

The weather in Delft, South Holland is currently 45°F, cloudy with showers.

Query completed in 3.88 seconds
```

Run `asky --help` for the full list of commands and flags.

## Documentation

### User guides

- [Quick Start](./docs/quickstart.md) - install, configure, first query
- [Configuration and Setup](./docs/configuration.md) - TOML config files, API keys, model aliases, sessions
- [Document Q&A](./docs/document_qa.md) - ask questions about local files
- [Deep Research Mode (`-r`)](./docs/research_mode.md) - multi-source web and local document research
- [User Memory & Elephant Mode (`-em`)](./docs/elephant_mode.md) - persistent cross-session memory
- [XMPP Daemon Mode](./docs/xmpp_daemon.md) - remote access via XMPP chat, voice transcription
- [Custom Tools](./docs/custom_tools.md) - expose local CLI commands to the model
- [Playwright Browser Plugin](./docs/playwright_browser.md) - browser-based page retrieval
- [Plugin Runtime and Built-in Plugins](./docs/plugins.md) - plugin system, persona tools, GUI server
- [Troubleshooting](./docs/troubleshooting.md) - common problems and fixes

### Developer / advanced

- [Library Usage Guide](./docs/library_usage.md) - programmatic usage via `asky.api`
- [Development Guide](./docs/development.md) - project setup, auto-reload, contributing
- [Research Evaluation](./docs/research_eval.md) - evaluating retrieval quality across models

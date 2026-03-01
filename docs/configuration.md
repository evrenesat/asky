# Configuration and Setup

On the first run, `asky` creates a default configuration directory at `~/.config/asky/`. This directory contains several TOML files to help organize your settings instead of stuffing everything into a single file. You can edit these files individually. If you have an older setup, the legacy `config.toml` is still supported for backward compatibility and will override the split files if present.

## 1. General Settings (`general.toml`)

This file controls the primary behavior of the CLI and its core limits.

### Core Settings

- `default_model`: The model used if `-m` is not provided (e.g., `"step35"`).
- `summarization_model`: The model used to compress conversation history (more on this below).
- `interface_model`: Optional planner model alias used by XMPP daemon routing for non-prefixed remote messages.
- `max_turns`: The maximum number of tool-call iterations the model can take before it is forced to yield a final answer (default `30`).
- `log_level`: Set to `"DEBUG"`, `"INFO"`, etc. (Logs go to `~/.config/asky/asky.log` by default).

### Limits & Timeouts

The `[limits]` block in `general.toml` defines boundaries to prevent the LLM from blowing out its context window or hanging indefinitely:

- `search_timeout` & `fetch_timeout`: How long (in seconds) the CLI waits for a web page or search query to respond before failing gracefully.
- `max_retries`, `initial_backoff`, `max_backoff`: Retry behavior for LLM API connection drops.
- `max_url_detail_links`: Caps the number of links extracted from a single URL to prevent context overflow.
- `search_snippet_max_chars`: Truncates individual search snippets.
- `query_expansion_max_depth`: Limits how deep recursive slash commands can go.
- `max_prompt_file_size`: Maximum bytes allowed when passing a `file://` prompt.

## 2. API Keys (`api.toml`)

You can set API keys in two ways:

1. **Environment Variables**: This is the recommended way. Set `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `SERPER_API_KEY`, etc., in your shell (`~/.bashrc` or `~/.zshrc`).
2. **Config File**: Setup keys and custom base URLs directly in `api.toml`:

```toml
[api.gemini]
api_key_env = "GOOGLE_API_KEY"
# Or explicitly:
# api_key = "AIzaSy..."

[api.lmstudio]
url = "http://localhost:1234/v1/chat/completions"
```

## 3. The Summarization Step Explained

If you have used asky thoroughly, you might have noticed that **after the final answer is printed, the CLI does not immediately return your terminal prompt.** It stays alive for a few extra seconds in a background thread.

**Why does asky do this?**
Every query and answer you make is saved into a local SQLite database, allowing you to seamlessly continue conversations later using the `-c` (continue) flag or Sticky Sessions (`-ss`). However, LLM replies and scraped web contexts can be massive. If asky re-injected the raw, full-length outputs from previous turns into your new prompt, it would quickly exhaust the model's token limit and rack up massive API costs.

To solve this, asky performs **Smart Context Management**:

1. After delivering your final answer, it routes the massive text to the cheaper `summarization_model` (defined in `general.toml`).
2. It uses a "hierarchical reduce" algorithm on very large texts, splitting them into chunks, summarizing each chunk, and merging them.
3. It saves _only the compressed summary_ to your local history database.

This guarantees that your subsequent conversational follow-ups are blazingly fast and token-efficient, at the small cost of a few seconds of background processing at the end of the current run.

## 4. Session Management & Compaction

The `[session]` block in `general.toml` controls how asky behaves during long-running named sessions (e.g., `asky -ss "My Project"`).

- `compaction_threshold` (default `80`): When the accumulated history in your session reaches 80% of the model's total context window size, asky triggers a compaction event.
- `compaction_strategy`:
  - `"summary_concat"`: Concatenates the already-generated summaries from previous turns.
  - `"llm_summary"`: Feeds the entire session log to the summarizer model to create a unified meta-summary.

## 5. Web Search Providers

asky works best when it can search the web. It currently supports two main providers, configurable in `general.toml`:

### Serper API

Set `search_provider = "serper"`. Serper is a paid service but offers 2500 requests for free. It requires an API key in your environment (`SERPER_API_KEY`) or in `api.toml`.

### SearXNG

Set `search_provider = "searxng"`. SearXNG is free and open-source. It's easy to set up locally with Docker and doesn't require an API key.

```bash
docker pull docker.io/searxng/searxng:latest
mkdir -p ./searxng/config/ ./searxng/data/
docker run --name searxng -d \
    -p 8888:8080 \
    -v "./config/:/etc/searxng/" \
    -v "./data/:/var/cache/searxng/" \
    docker.io/searxng/searxng:latest
```

_Note: You must ensure `-json` is added to the formats section of your SearXNG `settings.yml` file._

```toml
[general]
search_provider = "searxng"
searxng_url = "http://localhost:8888"
```

## 5a. Query Classification (Research Mode)

Asky can detect one-shot summarization requests and provide direct answers for small document sets without asking clarifying questions.

### Settings (`research.toml`)

```toml
[query_classification]
# Enable intelligent query classification for one-shot summarization
enabled = true

# Document count threshold for one-shot mode (default: 10)
# Queries with ≤ this many documents may trigger one-shot mode
one_shot_document_threshold = 10

# Aggressive mode: increase threshold to 20 documents
aggressive_mode = false
aggressive_document_threshold = 20

# Force research mode: always ask clarifying questions (disables one-shot)
force_research_mode = false
```

### Behavior

- **One-Shot Mode**: When you request a summary of ≤10 documents with clear summarization keywords (e.g., "summarize", "overview", "key points"), asky provides a direct answer.
- **Research Mode**: For larger corpora (>10 documents) or vague queries, asky asks clarifying questions to focus the research.

See [Research Mode Documentation](research_mode.md#one-shot-document-summarization) for examples.

## 6. Model Management (`models.toml`)

Easily manage your model configurations directly from the CLI without having to manually edit `models.toml`:

```bash
# Interactively search OpenRouter and add a new model definition
asky --config model add

# Interactively edit an existing model definition's parameters (temperature, max tokens)
asky --config model edit my-alias
```

## 7. Command Presets (`user.toml`)

You can define reusable CLI command templates under `[command_presets]`:

```toml
[command_presets]
daily = "--shortlist on Give me a concise daily briefing about $*"
research_local = "-r $1 Summarize the local corpus and answer: $*"
```

Invocation format:

- Local CLI: `asky \\daily ai regulation`
- XMPP daemon: `\\daily ai regulation`
- List presets: `\\presets`

Expansion behavior:

- Preset invocation is first-token only.
- `$1..$9` map positional arguments.
- `$*` expands to all trailing arguments.
- Unreferenced extra args are appended automatically.

## 8. XMPP Daemon Settings (`xmpp.toml`)

Daemon mode is configured through `xmpp.toml` and started with `asky --daemon`.
Use `asky --config daemon edit` for an interactive cross-platform editor for daemon settings.

Key options:

- `enabled`: master switch for daemon startup.
- `jid`, `password_env`/`password`, `host`, `port`, `resource`: transport credentials/connection.
- `allowed_jids`: sender allowlist supporting both:
  - bare JID (`user@domain`) to allow any resource
  - full JID (`user@domain/resource`) for strict resource pinning
- `command_prefix`: command marker when `general.interface_model` is configured (default `/asky`).
- `interface_planner_include_command_reference`: when `true`, asky appends a generated command/policy reference to the planner system prompt.
- `response_chunk_chars`: max outbound chunk length.
- `transcript_max_per_session`: transcript retention cap per sender session.

Voice and image transcription are now managed by dedicated plugins:
- See `~/.config/asky/voice_transcriber.toml` for voice transcription settings (model, tokens, auto-yes behavior).
- See `~/.config/asky/image_transcriber.toml` for image transcription capabilities.

Install extras as needed:

```bash
uv pip install "asky-cli[xmpp]"
uv pip install "asky-cli[mlx-whisper]"
uv pip install "asky-cli[mac]"  # includes iterm2 + mlx-whisper + rumps + slixmpp
```

Startup-at-login behavior managed by `--config daemon edit`:

- macOS: LaunchAgent (`~/Library/LaunchAgents/com.evren.asky.menubar.plist`)
- Linux: user `systemd` service (`~/.config/systemd/user/asky-xmpp-daemon.service`)
- Windows: Startup folder launcher script (`asky-xmpp-daemon.cmd`)

## 9. Output Actions (`push_data.toml`)

Automate your workflow by pushing results directly from `asky` to external services.

- **Email**: Configure SMTP settings in `push_data.toml` (or `email.toml` depending on your setup), then use:
  ```bash
  asky --mail me@work.com "Send me a daily briefing on AI news"
  ```
- **Webhooks (Push Data)**: Post the LLM's response to an HTTP endpoint configured in `push_data.toml`.
  ```bash
  asky --push-data https://my-webhook.com/endpoint "Analyze this log output"
  ```

## 10. Terminal Context Integration

If you are an **iTerm2** user on macOS, you can include the last N lines of your terminal screen as auto-appended context for your query. Very useful for "why am I getting this error?" moments.

- **Installation**: Requires the `iterm2` optional dependency package (`pip install "asky-cli[iterm2]"`).
- **Usage**: Use the `-tl` or `--terminal-lines` flag.
  ```bash
  asky -tl 15 "Why am I getting this error?"
  ```
- **Configuration**: Set `terminal_context_lines = 10` in `general.toml` to change the default `-tl` capture depth.
- **Prerequisite**: Ensure you have the iTerm2 Python API enabled in your iTerm2 settings.

## 11. Environment Variable Overrides

Several configuration values can be set via environment variables. Environment variables take precedence over the equivalent TOML config file values.

| Environment Variable    | Config file equivalent           | Description                                        |
| ----------------------- | -------------------------------- | -------------------------------------------------- |
| `ASKY_DB_PATH`          | `general.db_path`                | Override the SQLite database path.                 |
| `ASKY_SMTP_USER`        | `email.smtp_user`                | SMTP username for `--mail` output.                 |
| `ASKY_SMTP_PASSWORD`    | `email.smtp_password`            | SMTP password (prefer env over config file).       |
| `ASKY_XMPP_PASSWORD`    | `xmpp.password`                  | XMPP account password (prefer env over config).    |
| `HF_TOKEN`              | `plugin.voice_transcriber.hf_token` | Hugging Face token for voice model downloads.      |
| `GOOGLE_API_KEY`        | `api.gemini.api_key`             | Google / Gemini API key.                           |
| `OPENAI_API_KEY`        | `api.<alias>.api_key`            | OpenAI-compatible API key.                         |
| `SERPER_API_KEY`        | `api.serper.api_key`             | Serper web search API key.                         |

Notes:

- The env var name for `ASKY_DB_PATH` is configurable: set `db_path_env_var` in `general.toml` to use a different variable name.
- The env var names for `ASKY_SMTP_USER` and `ASKY_SMTP_PASSWORD` are configurable via `smtp_user_env` and `smtp_password_env` in `push_data.toml` / `email.toml`.
- The env var name for `ASKY_XMPP_PASSWORD` is configurable via `xmpp.password_env` in `xmpp.toml`.
- The env var name for the Hugging Face token is configurable via `hf_token_env` in `voice_transcriber.toml` (default `HF_TOKEN`).

## 12. Shell Auto-Completion

Enable tab completion for flags and dynamic values (like model aliases, history IDs, and session names):

```bash
# Bash
asky --completion-script bash >> ~/.bashrc
source ~/.bashrc

# Zsh
asky --completion-script zsh >> ~/.zshrc
source ~/.zshrc
```

## 13. Grouped CLI Surface

Asky now supports grouped command nouns for discoverability while preserving plain query usage.

```bash
# still valid plain query
asky explain why sky is blue

# grouped command examples
asky history list 20
asky history show 42
asky session list
asky session show S12
asky memory list
asky corpus query "what did I index about MoE scaling?"
asky corpus summarize "Section heading text"

# query behavior defaults persisted to session
asky --shortlist off
asky --tools off web_search,get_url_content
```

Notes:

- `--shortlist` supports `on|off|reset`.
- `--tools` supports: list (`--tools`), disable (`--tools off`), and clear session override (`--tools reset`).
- Query-behavior flags without a query auto-create/bind a session, persist defaults, and exit.
- `--session <query...>` creates a new session named from query text and runs the query.

## 14. Prompt and Tool Text Overrides

You can override built-in prompt text without forking the project.

- Global/research prompts live under `[prompts]` in `prompts.toml`.
- Interface planner prompt text is configurable via:
  - `prompts.interface_planner_system`
- Retrieval-only research guidance is configurable via:
  - `prompts.research_retrieval_only_guidance`
- Built-in tool descriptions/guidelines can be overridden via:
  - `prompts.tool_overrides.<tool_name>.description`
  - `prompts.tool_overrides.<tool_name>.system_prompt_guideline`

Example:

```toml
[prompts]
research_retrieval_only_guidance = """Use preloaded corpus first. Query memory, then retrieve evidence."""
interface_planner_system = """Return strict JSON action plan for remote routing."""

[prompts.tool_overrides.web_search]
description = "Search the web only when local/retrieval corpus is insufficient."
system_prompt_guideline = "Avoid web search unless preloaded evidence is insufficient."
```

The default `user.toml` includes commented examples for these knobs so new installs can discover and copy them quickly.

## 15. Plugin Runtime (`plugins.toml`)

Asky v1 plugins are local-only and loaded from:

- `~/.config/asky/plugins.toml`

If missing, asky creates a commented template on first plugin-runtime initialization.
The generated default enables built-in plugins (`manual_persona_creator`,
`persona_manager`, `gui_server`) so GUI settings editing works out of the box.

Manifest schema (per plugin entry):

```toml
[plugin.manual_persona_creator]
enabled = true
module = "asky.plugins.manual_persona_creator.plugin"
class = "ManualPersonaCreatorPlugin"
dependencies = []
capabilities = ["tool_registry", "preload", "prompt"]
config_file = "plugins/manual_persona_creator.toml"
```

Rules:

- Required keys: `enabled`, `module`, `class`
- Optional keys: `dependencies`, `capabilities`, `config_file`
- Unknown keys are ignored with warning
- Import/activation failures are isolated per plugin and do not crash startup

### Built-in Hook Names (v1)

- `TOOL_REGISTRY_BUILD`
- `SESSION_RESOLVED`
- `PRE_PRELOAD`
- `POST_PRELOAD`
- `SYSTEM_PROMPT_EXTEND` (chain-return)
- `PRE_LLM_CALL`
- `POST_LLM_RESPONSE`
- `PRE_TOOL_EXECUTE`
- `POST_TOOL_EXECUTE`
- `TURN_COMPLETED`
- `DAEMON_SERVER_REGISTER`

Deferred in v1: `CONFIG_LOADED`, `POST_TURN_RENDER`, `SESSION_END`.

### Built-in Plugins in This Repo

- `asky.plugins.manual_persona_creator`: manual persona creation/export tools
- `asky.plugins.persona_manager`: persona import + per-session binding + prompt/preload injection
- `asky.plugins.gui_server`: NiceGUI sidecar server (daemon integration) with general settings editor

For concrete entry points and current limitations (including persona workflow
visibility and GUI URLs), see [`docs/plugins.md`](./plugins.md).

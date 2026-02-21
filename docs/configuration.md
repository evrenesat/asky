# Configuration and Setup

On the first run, `asky` creates a default configuration directory at `~/.config/asky/`. This directory contains several TOML files to help organize your settings instead of stuffing everything into a single file. You can edit these files individually. If you have an older setup, the legacy `config.toml` is still supported for backward compatibility and will override the split files if present.

## 1. General Settings (`general.toml`)

This file controls the primary behavior of the CLI and its core limits.

### Core Settings

- `default_model`: The model used if `-m` is not provided (e.g., `"step35"`).
- `summarization_model`: The model used to compress conversation history (more on this below).
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

## 6. Model Management (`models.toml`)

Easily manage your model configurations directly from the CLI without having to manually edit `models.toml`:

```bash
# Interactively search OpenRouter and add a new model definition
asky --add-model

# Interactively edit an existing model definition's parameters (temperature, max tokens)
asky --edit-model my-alias
```

## 7. Output Actions (`push_data.toml`)

Automate your workflow by pushing results directly from `asky` to external services.

- **Email**: Configure SMTP settings in `push_data.toml` (or `email.toml` depending on your setup), then use:
  ```bash
  asky --mail me@work.com "Send me a daily briefing on AI news"
  ```
- **Webhooks (Push Data)**: Post the LLM's response to an HTTP endpoint configured in `push_data.toml`.
  ```bash
  asky --push-data https://my-webhook.com/endpoint "Analyze this log output"
  ```

## 8. Terminal Context Integration

If you are an **iTerm2** user on macOS, you can include the last N lines of your terminal screen as auto-appended context for your query. Very useful for "why am I getting this error?" moments.

- **Installation**: Requires the `iterm` optional dependency package (`pip install "asky-cli[iterm]"`).
- **Usage**: Use the `-tl` or `--terminal-lines` flag.
  ```bash
  asky -tl 15 "Why am I getting this error?"
  ```
- **Configuration**: Set `terminal_context_lines = 10` in `general.toml` to change the default `-tl` capture depth.
- **Prerequisite**: Ensure you have the iTerm2 Python API enabled in your iTerm2 settings.

## 9. Shell Auto-Completion

Enable tab completion for flags and dynamic values (like model aliases, history IDs, and session names):

```bash
# Bash
asky --completion-script bash >> ~/.bashrc
source ~/.bashrc

# Zsh
asky --completion-script zsh >> ~/.zshrc
source ~/.zshrc
```

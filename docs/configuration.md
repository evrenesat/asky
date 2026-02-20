# Configuration and Setup

On the first run, `asky` creates a default configuration directory at `~/.config/asky/`. This directory contains several TOML files to help organize your settings instead of stuffing everything into a single file.

- `general.toml`: Basic settings (logging, search provider, timeouts, CLI behavior)
- `api.toml`: API endpoint definitions and keys
- `models.toml`: Model configurations, aliases, and specific parameters
- `prompts.toml`: System prompts and custom user text shortcuts
- `user.toml`: User shortcuts and custom local tools
- `push_data.toml`: Settings for Email (`--mail`) and HTTP webhooks (`--push-data`)
- `research.toml`: Deep Research settings (corpus roots, RAG parameters, evidence extraction)
- `memory.toml`: Configuration for the User Memory system

You can edit these files individually. If you have an older setup, the legacy `config.toml` is still supported for backward compatibility and will override the split files if present.

## API Keys

You can set API keys in two ways:

1. **Environment Variables**: This is the recommended way. Set `GOOGLE_API_KEY`, `OPENAI_API_KEY`, etc. in your shell (`~/.bashrc` or `~/.zshrc`).
2. **Config File**: Add keys directly to `api.toml`:

```toml
[api.gemini]
api_key_env = "GOOGLE_API_KEY"
# Or explicitly:
# api_key = "AIzaSy..."

[api.lmstudio]
url = "http://localhost:1234/v1/chat/completions"
```

## Model Management

Easily manage your model configurations directly from the CLI without having to manually edit `models.toml`:

```bash
# Interactively search OpenRouter and add a new model definition
asky --add-model

# Interactively edit an existing model definition's parameters (temperature, max tokens)
asky --edit-model my-alias
```

## Web Search Providers

asky works best when it can search the web. It currently supports two main providers: Serper API and SearXNG.

### Serper API

Serper is a paid service but offers 2500 requests for free. It requires an API key in `api.toml` and setting `search_provider = "serper"` in `general.toml`.

### SearXNG

SearXNG is free and open-source. It's easy to set up locally with Docker and doesn't require an API key.

Following command taken from [SearXNG docs](https://docs.searxng.org/admin/installation-docker.html#instancing).

```bash
docker pull docker.io/searxng/searxng:latest

# Create directories for configuration and persistent data
$ mkdir -p ./searxng/config/ ./searxng/data/
$ cd ./searxng/

# Run the container
$ docker run --name searxng -d \
    -p 8888:8080 \
    -v "./config/:/etc/searxng/" \
    -v "./data/:/var/cache/searxng/" \
    docker.io/searxng/searxng:latest
```

You must ensure that `-json` is added to the formats section of your SearXNG `settings.yml` file:

```yaml
search:
  formats:
    - html
    - json
```

Then configure `asky` to use it in `general.toml`:

```toml
[general]
search_provider = "searxng"
searxng_url = "http://localhost:8888"
```

## Advanced Features

### File Prompts

You can store complex, multi-line prompts in a file and feed them directly to `asky` using the `file://` URI scheme. This is highly useful for repetitive tasks like Code Review, Release Notes generation, or static analysis parsing.

```bash
asky file://my_complex_prompt.txt
```

### Session Management

Organize related work into named sessions. All conversation history is isolated to that session.

```bash
# Start a new session for a specific project
asky -ss "Project Alpha" "What is our current architecture?"

# Later, resume it from anywhere in your terminal
asky -rs "Project Alpha" "Let's update the architecture we discussed."

# Convert a previous generic history item into a dedicated session
asky -sfm 42 "Let's branch this out into a permanent chat"
```

### Output Actions

Automate your workflow by pushing results directly from `asky` to external services.

- **Email**: Send the final answer to an email address.
  ```bash
  asky --mail me@work.com "Send me a daily briefing on AI news"
  ```
- **Webhooks (Push Data)**: Post the LLM's response to an HTTP endpoint.
  ```bash
  asky --push-data https://my-webhook.com/endpoint "Analyze this log output"
  ```

### Terminal Context Integration

If you are an **iTerm2** user on macOS, you can include the last N lines of your terminal screen as auto-appended context for your query. Very useful for "why am I getting this error?" moments.

- **Installation**: Requires the `iterm` optional dependency package (`pip install "asky-cli[iterm]"`).
- **Usage**: Use the `-tl` or `--terminal-lines` flag.
  ```bash
  asky -tl 15 "Why am I getting this error?"
  ```
- **Prerequisite**: Ensure you have the iTerm2 Python API enabled in your iTerm2 settings.

### Shell Auto-Completion

Enable tab completion for flags and dynamic values (like model aliases, history IDs, and session names):

```bash
# Bash
asky --completion-script bash >> ~/.bashrc
source ~/.bashrc

# Zsh
asky --completion-script zsh >> ~/.zshrc
source ~/.zshrc
```

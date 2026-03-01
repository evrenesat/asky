# Quick Start

This guide walks you from a fresh install to a working query. It covers one path only - the simplest one. Once things work, see [Configuration and Setup](./configuration.md) for full options.

## What you need before starting

- Python 3.10+ or [uv](https://docs.astral.sh/uv/) installed
- An API key for one LLM provider (see options below)
- A search provider (optional, but web search won't work without one)

### LLM provider options

asky talks to any OpenAI-compatible API. Pick one to start:

| Provider | Free tier | Env variable |
|----------|-----------|--------------|
| [Google Gemini](https://aistudio.google.com/apikey) | Yes - generous free quota | `GOOGLE_API_KEY` |
| [OpenAI](https://platform.openai.com/api-keys) | No | `OPENAI_API_KEY` |
| [OpenRouter](https://openrouter.ai/) | Yes - some models free | `OPENROUTER_API_KEY` |
| Local via [LM Studio](https://lmstudio.ai/) | N/A - runs locally | Not required |

Gemini is the easiest starting point: free tier, no billing setup required.

### Search provider options

Web search requires one of these:

- **Serper** - paid service with 2500 free requests. Get a key at [serper.dev](https://serper.dev). Set `SERPER_API_KEY` in your environment.
- **SearXNG** - free, self-hosted. Run it locally with Docker (see [Configuration](./configuration.md#5-web-search-providers)).

You can skip search for now. Basic queries still work - the model just won't be able to look things up on the web.

---

## Step 1 - Install

```bash
uv tool install asky-cli
```

If you don't have uv, you can use pip as a fallback:

```bash
pip install asky-cli
```

---

## Step 2 - First run

Run any query:

```bash
asky "hello"
```

On first run, asky creates its config directory and copies default config files into it:

<!-- CAPTURE: run `asky "hello"` on a fresh install (no ~/.config/asky directory) and paste the terminal output here, including all "Created default configuration..." lines -->

After that, you will see an error because no model is configured yet:

<!-- CAPTURE: run `asky "hello"` when default_model is empty in general.toml and paste the error message here -->

That's expected. Continue to Step 3.

---

## Step 3 - Set your API key

Set the environment variable for your chosen provider. For Gemini:

```bash
export GOOGLE_API_KEY="your-key-here"
```

Add this line to your `~/.zshrc` or `~/.bashrc` so it persists across terminal sessions.

---

## Step 4 - Configure a model

asky uses named model aliases. The bundled config includes several ready-made aliases. To see them:

```bash
cat ~/.config/asky/models.toml
```

The bundled aliases include:

- `gf` - Gemini Flash (uses `GOOGLE_API_KEY`)
- `q34`, `q8`, `q30` - Qwen models via LM Studio (local, no API key needed)

Set your default model in `~/.config/asky/general.toml`:

```toml
[general]
default_model = "gf"
```

Or add a new model interactively:

```bash
asky --config model add
```

<!-- CAPTURE: run `asky --config model add` and paste the interactive session output here (the prompts and what you typed) -->

---

## Step 5 - First successful query

```bash
asky "What is the capital of France?"
```

Expected output:

<!-- CAPTURE: run `asky "What is the capital of France?"` after configuring a model and paste the full terminal output here -->

The timing line at the end (`Query completed in X.XX seconds`) is always shown. The tool-dispatch lines only appear when the model makes tool calls (web search, URL fetch, etc.).

---

## Step 6 - Enable web search (optional)

If you have a Serper key:

```bash
export SERPER_API_KEY="your-key-here"
```

Then update `~/.config/asky/general.toml`:

```toml
[general]
search_provider = "serper"
```

Now try a query that needs web access:

```bash
asky "What is the weather in London right now?"
```

You should see `Dispatching tool call: web_search` appear before the answer.

<!-- CAPTURE: run `asky "What is the weather in London right now?"` with a working Serper key and paste the output here -->

If you prefer SearXNG, see [Configuration - Web Search Providers](./configuration.md#5-web-search-providers).

---

## What's next

- **Full configuration** - models, session settings, limits: [Configuration and Setup](./configuration.md)
- **Ask questions about your documents** - PDF, EPUB, Markdown: [Document Q&A](./document_qa.md)
- **Use asky from your phone via chat** - XMPP daemon mode: [XMPP Daemon Mode](./xmpp_daemon.md)
- **Deep web and local research** - multi-source retrieval: [Deep Research Mode](./research_mode.md)

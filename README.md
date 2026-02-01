# asearch

AI-powered web search CLI with LLM tool-calling capabilities.

## Installation

```bash
pip install asearch
```

Or install from source:

```bash
pip install -e .
```

## Usage

```bash
➜  ~ ask -h
usage: ask [-h] [-m {q34t,q34,lfm,q8,q30,gf}] [-d [DEEP_RESEARCH]] [-dd] [-H [HISTORY]] [-c CONTINUE_IDS] [-f] [-s] [-fs] [--cleanup-db [CLEANUP_DB]] [--all] [-p PRINT_IDS] [-v] [query ...]

Tool-calling CLI with model selection.

positional arguments:
  query                 The query string

options:
  -h, --help            show this help message and exit
  -m, --model {q34t,q34,lfm,q8,q30,gf}
                        Select the model alias
  -d, --deep-research [DEEP_RESEARCH]
                        Enable deep research mode (optional: specify min number of queries, default 5)
  -dd, --deep-dive      Enable deep dive mode (extracts links and encourages recursive research)
  -H, --history [HISTORY]
                        Show last N queries (default 10) and exit.
  -c, --continue-chat CONTINUE_IDS
                        Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').
  -f, --full            Use full content of previous answers for context instead of summaries.
  -s, --summarize       Enable summarize mode (summarizes the content of the URL)
  -fs, --force-search   Force the model to use web search (default: False).
  --cleanup-db [CLEANUP_DB]
                        Delete history records. usage: --cleanup-db [ID|ID-ID|ID,ID] or --cleanup-db --all
  --all                 Used with --cleanup-db to delete ALL history.
  -p, --print-answer PRINT_IDS
                        Print the answer(s) for specific history IDs (comma-separated).
  -v, --verbose         Enable verbose output (prints config and LLM inputs).


  
# Basic query
ask what is the weather in Berlin

# Show history
ask -H
Last 6 Queries:
------------------------------------------------------------
10   | what is the weather in Berlin                      | The weather in Kreuzberg, Berlin is currently c...
9    | what is this about                                 | This analysis explores dad jokes humor, combin...
8    | summarize please                                   | The humor in dad jokes comes from blending scie...
7    | explain more                                       | The humor comes from blending scientific terms ...
2    | is that funny                                      | This science pun cleverly blends scientific ter...
1    | tell me a joke                                     | Scientists often joke that atoms don’t trust th...
------------------------------------------------------------

# Continue from previous query (by ID)
ask -c 1 tell me more about that

# Continue from last query (relative ID)
ask -c~1 explain more
# OR
ask -c "~2" what about the one before that?

> [!NOTE]
> **Zsh Users**: When using `~` for relative IDs, you must either quote the value (e.g., `ask -c "~1"`) or place it immediately after the flag without a space (e.g., `ask -c~1`). If you use a space without quotes (e.g., `ask -c ~1`), zsh will attempt to expand it as a directory stack entry.

# Deep research mode (multiple searches)
ask -d 5 comprehensive analysis of topic

# Deep dive mode (follow links recursively)
ask -dd https://example.com

# Use a specific model
ask -m gf what is quantum computing

# Force web search
ask -fs latest news on topic

# Clean up history
ask --cleanup-db 1-5
ask --cleanup-db --all
```

## Available Models

- `gf` - Google Gemini Flash (default)
- `lfm` - Liquid LFM 2.5
- `q8` - Qwen3 8B
- `q30` - Qwen3 30B
- `q34` - Qwen3 4B
- `q34t` - Qwen3 4B Thinking

## Configuration

On first run, a default configuration file is created at `~/.config/asearch/config.toml`. You can edit this file to configure models, API keys, and other settings.

### API Keys
You can set API keys in two ways:
1. **Environment Variables**: Set `GOOGLE_API_KEY` (or other configured env vars) in your shell.
2. **Config File**: Add keys directly to `[api.name]` sections in `config.toml`.

Example `config.toml`:
```toml
[general]
default_model = "gf"

[api.gemini]
api_key_env = "GOOGLE_API_KEY"

[api.lmstudio]
url = "http://localhost:1234/v1/chat/completions"
```

### Verification
Run with `-v` to see the loaded configuration:
```bash
ask -v
```

## Requirements

- Python 3.10+
- Running SearXNG instance (default: http://localhost:8888)
- LM Studio (for local models) or API keys for remote models

## License

MIT


<img src="https://github.com/evrenesat/asky/raw/main/assets/asky_icon.png" alt="asky icon" width="200" align="right">

<!-- <font size="6">**asky**</font> -->
<img src="https://github.com/evrenesat/asky/raw/main/assets/title.png" alt="asky title">


asky is an AI-powered web search CLI with LLM tool-calling capabilities.

It (can be invoked as `asky` or `ask`) provides a powerful command-line interface that brings AI-powered search and research capabilities directly to your terminal. It uses LLMs and tools to synthesize answers from the web (or from files and cli commands you expose as tools).
## Key Features

- **Multi-Model Support**: Easily define and switch between various LLMs and providers that supports OpenAI compatible API.
- **Tool-Calling Integration**: Models can autonomously perform web searches (via SearXNG or Serper API), fetch URL content, and get current date/time to provide accurate, up-to-date answers.
- **Custom Tools**: Expose any CLI command as a tool for the LLM. Define your own commands and parameters in `config.toml`.
- **Intelligent Content Fetching**: Automatically strips HTML noise (scripts, styles) to provide clean text context to the models. It can also summarize the content of the URLs and use the summaries for chat context. 
- **Conversation History**: Maintains a local SQLite database of your queries and answers (with their summaries), allowing for context-aware follow-up questions.
- **Deep Research Mode**: Automatically performs multiple searches to provide comprehensive analysis of complex topics.
- **Deep Dive Mode**: Allows models to recursively explore the links found on web pages for in-depth information gathering.
- **Predefined Prompts**: Users can define and quickly invoke common prompt patterns using simple slashes (e.g., `/gn` for get latest news from The Guardian).
- **Clipboard Integration**: Use `/cp` to expand the query with clipboard content.
- **Token Efficient**: It counts token usage and keep the model informed about remaining context capacity to encourage it to finish the task before hitting the limit. Together with summaries, this makes asky very token efficient.

## How it Works

1. **User Query**: You provide a query to the `asky` command.
2. **Model Selection**: asky initializes the selected LLM based on your configuration.
3. **Tool Loop**: The LLM analyzes your query. If it needs real-world data, it calls integrated tools (like `web_search`).
4. **Context Synthesis**: asky fetches the data, cleans it, and feeds it back to the LLM. This process can repeat for up to 15 turns for complex research.
5. **Final Answer**: The LLM synthesizes all gathered information into a concise, formatted response.
6. **Persistence**: The interaction is saved to your local history for future reference.


## Installation

```bash
pip install asky-cli
```

Or install from source:

```bash
pip install -e .
```

## Usage

```

# Basic query
asky what is the weather in Berlin

# Continue from previous query (by ID)
asky -c 1 tell me more about that

# Continue from last query (relative ID)
asky -c~1 explain more
# OR
asky -c "~2" what about the one before that?

> [!NOTE]
> **Zsh Users**: When using `~` for relative IDs, you must either quote the value (e.g., `asky -c "~1"`) or place it immediately after the flag without a space (e.g., `asky -c~1`). If you use a space without quotes (e.g., `asky -c ~1`), zsh will attempt to expand it as a directory stack entry.


➜  ~ asky -p

=== USER PROMPTS ===
  /gn         : Give me latest news from The Guardian, use https://www.theguardian.com/europe
  /wh         : how is weather in
====================

➜  ~ asky /wh delft
Dispatching tool call: web_search with args {'q': 'weather in Delft'}
Dispatching tool call: get_url_content with args {'urls': ...}

The weather in **Delft, South Holland, Netherlands** is currently **45°F and Cloudy with Showers in the Vicinity** (as of 4:20 pm CET).

Here is the forecast for today and the next couple of days:

...

Query completed in 3.88 seconds

--------------------------------------------------------------------------------
➜  ~ asky --help
usage: asky [-h] [-m {gf,glmair,glmflash,q34t,q34,lfm,q8,q30,onano,omini}] [-d [DEEP_RESEARCH]] [-dd] [-c CONTINUE_IDS] [-s] [-fs] [--cleanup-db [CLEANUP_DB]] [--all]
           [-H [HISTORY]] [-pa PRINT_IDS] [-p] [-v]
           [query ...]

Tool-calling CLI with model selection.

positional arguments:
  query                 The query string

options:
  -h, --help            show this help message and exit
  -m, --model {gf,glmair,glmflash,q34t,q34,lfm,q8,q30,onano,omini}
                        Select the model alias
  -d, --deep-research [DEEP_RESEARCH]
                        Enable deep research mode (optional: specify min number of queries, default 5)
  -dd, --deep-dive      Enable deep dive mode (extracts links and encourages reading more pages from same domain)
  -c, --continue-chat CONTINUE_IDS
                        Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').
  -s, --summarize       Enable summarize mode (summarizes URL content and uses summaries for chat context)
  -fs, --force-search   Force the model to use web search (default: False).
                        Helpful for avoiding hallucinations with small models
  --delete-messages [ID|ID-ID|ID,ID]
                        Delete specific history records
  --delete-messages --all
                        Clear **entire** message history (interactive confirm)
  --delete-sessions [ID|ID-ID]
                        Delete specific sessions
  -H, --history [HISTORY]
                        Show last N queries and answer summaries (default 10).
                        Use with --print-answer to print the full answer(s).
  -pa, --print-answer PRINT_IDS
                        Print the answer(s) for specific history IDs (comma-separated).
  -p, --prompts         List all configured user prompts.
  -v, --verbose         Enable verbose output (prints config and LLM inputs).
```

**Deep research mode** (encourages model to perform multiple searches)

asky -d 5 comprehensive analysis of topic

**Deep dive mode** (encourages model to read multiple pages from same domain)

asky -dd https://example.com

**Use a specific model**

asky -m gf what is quantum computing

**Force web search**

asky -fs latest news on topic


**Pre-configured model definitions**

Followin model definitions ship with default config.toml, but you can add any number of models that are served with an OpenAI compatible API.

- `gf` - Google Gemini Flash (default)
- `lfm` - Liquid LFM 2.5
- `q8` - Qwen3 8B
- `q30` - Qwen3 30B
- `q34` - Qwen3 4B
- `q34t` - Qwen3 4B Thinking

## Custom Tools

You can define your own tools in `config.toml` that the LLM can use to interact with your local system. Each tool runs a CLI command and returns the output to the LLM.

Example configuration for a `list_dir` tool:

```toml
[tool.list_dir]
command = "ls"
description = "List the contents of a directory."

[tool.list_dir.parameters]
type = "object"
required = ["path"]

[tool.list_dir.parameters.properties.path]
type = "string"
default = "."
```

Example configuration for a `grep_search` tool:

```toml
[tool.grep_search]
command = "grep -r {pattern} {path}"
description = "Search for a pattern in files recursively."

[tool.grep_search.parameters]
type = "object"
required = ["pattern"]

[tool.grep_search.parameters.properties.pattern]
type = "string"
description = "The regex pattern to search for."

[tool.grep_search.parameters.properties.path]
type = "string"
description = "The directory path to search in."
default = "."
```

> [!CAUTION]
> **Security Risk**: Custom tools execute commands using your system shell. While asky attempts to quote arguments safely, exposing powerful CLI tools to an LLM can be risky. Use this feature with caution.

### How it works:
- **Placeholders**: Use `{param_name}` in the `command` string to inject arguments. If no placeholders are found, arguments are appended to the command.
- **Quoting**: All arguments are automatically cleaned (inner double-quotes removed) and wrapped in double-quotes for safety.
- **Execution**: Commands are executed via terminal shell, allowing for advanced piping and redirection.

> [!TIP]
> **Performance Tip**: When using recursive tools like `grep`, consider excluding large directories like `.venv` or `node_modules` to avoid timeouts:
> `command = "grep -r --exclude-dir={.venv,node_modules} {pattern} {path}"`

> [!NOTE]
> **Optional Parameters**: If you define a parameter with a `default` value in `config.toml`, it will be automatically injected into your `command` if the LLM omits it.

## Configuration options
[See default configuration](./src/asky/config.toml)


On first run, a default configuration file is created at `~/.config/asky/config.toml`. You can edit this file to configure models, API keys, and other settings.

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
asky -v
```


## Web Search

asky works best with a web search tool. You can use SearXNG or Serper API. 

### Serper API
Serper is a paid service, but gives 2500 requests for free. 

### Install & configure SearXNG
SearXNG is free and open source, it's easy to set up with a single docker command.

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
You need to add "-json" to the formats section of the default searxng config.yaml file.
```yaml
  # remove format to deny access, use lower case.
  # formats: [html, csv, json, rss]
  formats:
    - html
    - json
```
Then restart the container.
```bash
docker restart searxng
```



## Requirements

- Python 3.10+
- Running SearXNG instance or Serper API key.
- LM Studio (for local models) or API keys for remote models

## License

MIT

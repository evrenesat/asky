
<img src="https://github.com/evrenesat/asky/raw/main/assets/asky_icon.png" alt="asky icon" width="200" align="right">

<!-- <font size="6">**asky**</font> -->
<img src="https://github.com/evrenesat/asky/raw/main/assets/title.png" alt="asky title">


asky is an AI-powered web search CLI with LLM tool-calling capabilities.

It (can be invoked as `asky` or `ask`) provides a powerful command-line interface that brings AI-powered search and research capabilities directly to your terminal. It uses LLMs and tools to synthesize answers from the web (or from files and cli commands you expose as tools).

## Library Usage

For programmatic usage (`asky.api`), including full configuration and request options, see:

- [Library Usage Guide](./docs/library_usage.md)

## Key Features

- **Multi-Model Support**: Easily define and switch between various LLMs and providers that supports OpenAI compatible API.
- **Deep Research Mode**: A specialized mode where the agent iteratively searches, extracts links, and reads content using RAG (Retrieval Augmented Generation) to answer complex queries.
- **Tool-Calling Integration**: Models can autonomously perform web searches (via SearXNG or Serper API), fetch URL content, and get current date/time to provide accurate, up-to-date answers.
- **Custom Tools**: Expose any CLI command as a tool for the LLM. Define your own commands and parameters in `config.toml`.
- **File Prompts**: Load complex prompts directly from files using `file://` URIs (e.g., `asky file://my_prompt.txt`).
- **Smart Context Management**: Automatically summarizes web content and older conversation history to maximize the LLM's context window usage.
- **Conversation History**: Maintains a local SQLite database of your queries and answers (with their summaries), allowing for context-aware follow-up questions.
- **Predefined Prompts**: Users can define and quickly invoke common prompt patterns using simple slashes (e.g., `/gn` for get latest news from The Guardian).
- **Clipboard Integration**: Use `/cp` to expand the query with clipboard content.
- **Actionable Outputs**: Send results via email (`--mail`) or push them to an external endpoint (`--push-data`) directly from the CLI.
- **Model Management**: Interactive CLI commands (`--add-model`, `--edit-model`) to easily add and configure new models (including OpenRouter integration).
- **Token Efficient**: It counts token usage and keep the model informed about remaining context capacity to encourage it to finish the task before hitting the limit.

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

To enable optional feature iTerm2 context integration:

```bash
pip install "asky-cli[iterm]"
```

Or if you are using `uv`:

```bash
uv tool install "asky-cli[iterm]"
# or from source
uv tool install -e ".[iterm]"
```


## Usage

> [!NOTE]
> **asky is powerful**: These examples show just a fraction of what you can do.

```

# Basic query
asky what is the correct temperature for green tea

# Research Mode (Iterative deep search)
asky -r "Compare the latest iPhone vs Samsung flagship specs and reviews"

# Use a specific model
asky -m gf "Explain quantum entanglement"

# File Prompt (Great for code reviews or complex analysis)
asky file://code_review_checklist.txt

# Continue from previous query (by ID)
asky -c 1 tell me more about that

# Continue from last query (relative ID)
asky -c~1 explain more
# OR
asky -c "~2" what about the one before that?

# Send result to email
asky --mail user@example.com --subject "Meeting Summary" "Summarize the last 3 emails about Project X"

```

> [!NOTE]
> **Zsh Users**: When using `~` for relative IDs, you must either quote the value (e.g., `asky -c "~1"`) or place it immediately after the flag without a space (e.g., `asky -c~1`). If you use a space without quotes (e.g., `asky -c ~1`), zsh will attempt to expand it as a directory stack entry.



```console
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

Tool-calling CLI with model selection.

positional arguments:
  query                 The query string

options:
  -h, --help            show this help message and exit
  -m, --model {gf,glmair,glmflash,q34t,q34,lfm,q8,q30,onano,omini,qwenmax,qwenflash,qnext,nna3b,p4mini,On3b,Ogpt20,Ol370,Ogfl,gfl}
                        Select the model alias
  -c, --continue-chat CONTINUE_IDS
                        Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').
  -s, --summarize       Enable summarize mode (summarizes URL content and uses summaries for chat context)
  --delete-messages [ID|ID-ID|ID,ID]
                        Delete message history records. usage: --delete-messages [ID|ID-ID|ID,ID] or --delete-messages --all
  --delete-sessions [ID|ID-ID|ID,ID]
                        Delete session records and their messages. usage: --delete-sessions [ID|ID-ID|ID,ID] or --delete-sessions --all
  --all                 Used with --delete-messages or --delete-sessions to delete ALL records.
  -H, --history [N]
                        Show last N queries and answer summaries (default 10).
  -pa, --print-answer PRINT_IDS
                        Print the answer(s) for specific history IDs (comma-separated).
  -ps, --print-session PRINT_SESSION
                        Print session content by session ID or name.
  -p, --prompts         List all configured user prompts.
  -v, --verbose         Enable verbose output (prints config and LLM inputs).
  -o, --open            Open the final answer in a browser using a markdown template.
  --mail MAIL_RECIPIENTS
                        Send the final answer via email to comma-separated addresses.
  --subject SUBJECT     Subject line for the email (used with --mail).
  --push-data PUSH_DATA_ENDPOINT
                        Push query result to a configured endpoint after query completes.
  --push-param KEY VALUE
                        Dynamic parameter for --push-data. Can be repeated.
  -ss, --sticky-session STICKY_SESSION [STICKY_SESSION ...]
                        Create and activate a new named session (then exits).
  -rs, --resume-session RESUME_SESSION [RESUME_SESSION ...]
                        Resume an existing session by ID or name.
  -sfm, --session-from-message SESSION_FROM_MESSAGE
                        Convert a specific history message ID into a session and resume it.
  -se, --session-end    End the current active session
  -sh, --session-history [SESSION_HISTORY]
                        Show last N sessions (default 10).
  -r, --research        Enable deep research mode with link extraction and RAG-based content retrieval.
  -tl, --terminal-lines [TERMINAL_LINES]
                        Include the last N lines of terminal context in the query.
  --completion-script {bash,zsh}
                        Print shell setup snippet for argcomplete and exit.
```

## Features in Depth

### Deep Research Mode (`-r`)
For complex topics, use the `--research` flag. This enables a specialized system prompt and toolset:
- **extract_links**: Scans pages to find relevant citations without loading full content.
- **get_link_summaries**: Rapidly summarizes multiple pages to decide which ones to read.
- **get_relevant_content**: Uses vector embeddings (via RAG) to pull only the specific paragrahps you need from a long document.

### File Prompts
You can store complex prompts in a file and feed them to `asky`:
```bash
asky file://my_complex_prompt.txt
```
This is useful for repetitive tasks like "Code Review", "Summarize Release Notes", etc.
File prompts are validated for size limits (configurable in `config.toml`).

### Session Management
Organize your work into named sessions:
```bash
# Start a new session for a specific project
asky -ss "Project Alpha"

# Later, resume it
asky -rs "Project Alpha" what were we discussing?

# Convert a history item into a session and continue
asky -sfm 42 continue this thread
```

### Shell Auto-Completion
Enable tab completion for flags and dynamic values (models, history IDs, session IDs/names):

```bash
# Bash
asky --completion-script bash >> ~/.bashrc
source ~/.bashrc

# Zsh
asky --completion-script zsh >> ~/.zshrc
source ~/.zshrc
```

The generated snippet is self-contained and does not require `register-python-argcomplete` on your PATH.
History and session value suggestions include short previews (query/session name + timestamp) so numeric IDs are easier to pick.
For `-pa/--print-answer` and `-sfm/--session-from-message`, completion also includes word-based selector tokens that decode back to the original answer ID automatically.
Session completion (`-ps`, `-rs`) now returns one selector per session (name-derived token + hidden session ID), avoiding duplicate ID/name rows.
Continue-chat completion (`-c`) uses the same selector style for history items, and selector tokens resolve back to numeric IDs automatically.

### Output Actions
Automate your workflow by pushing results to other services:
- **Email**: `asky --mail me@work.com "Send me the daily briefing"`
- **Push Data**: `asky --push-data https://my-webhook.com/endpoint "Analyze this log"`

### Model Management
Easily manage your model configurations directly from the CLI:
```bash
# Interactively add a new model (searches OpenRouter)
asky --add-model

# Edit an existing model configuration
asky --edit-model my-alias
```

### Terminal Context Integration
This feature allows you to include the last N lines of your terminal screen as context for your query. Useful when you want to ask "why am I getting this error?".

- **Installation**: Requires `iterm` optional dependency.
- **Usage**: Add `-tl` or `--terminal-lines` flag. The default value is 10.
  ```bash
  asky -tl 5 why am I getting this error
  ```
- **Configuration**: You can modify `terminal_context_lines` in `config.toml` to set a different default value.
> [!NOTE]
> This feature requires iTerm2 Python API, you can enable it from iTerm2 settings.

<img src="https://github.com/evrenesat/asky/raw/main/assets/iterm_config.png" alt="iterm config" width="400">


## Custom Tools

You can define your own tools in `config.toml` that the LLM can use to interact with your local system. Each tool runs a CLI command and returns the output to the LLM.

Example configuration for a `list_dir` tool:

```toml
[tool.list_dir]
command = "ls"
description = "List the contents of a directory."
enabled = true

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
enabled = false # Disabled by default for safety

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
- **Placeholders**: Use `{param_name}` in the `command` string to inject arguments. If no placeholders are found, argument is appended to command.
- **Quoting**: All arguments are automatically cleaned (inner double-quotes removed) and wrapped in double-quotes for safety.
- **Execution**: Commands are executed via terminal shell, allowing for advanced piping and redirection.

> [!TIP]
> **Performance Tip**: When using recursive tools like `grep`, consider excluding large directories like `.venv` or `node_modules` to avoid timeouts:
> `command = "grep -r --exclude-dir={.venv,node_modules} {pattern} {path}"`

> [!NOTE]
> **Optional Parameters**: If you define a parameter with a `default` value in `config.toml`, it will be automatically injected into your `command` if the LLM omits it.

## Configuration options
[See default configuration](./src/asky/data/config/general.toml)


On first run, a default configuration directory is created at `~/.config/asky/` containing several TOML files to help organize your settings:

- `general.toml`: Basic settings (logging, search provider, timeouts)
- `api.toml`: API endpoint definitions
- `models.toml`: Model configurations
- `prompts.toml`: System prompts
- `user.toml`: User shortcuts and custom tools
- `push_data.toml`: Email and Push Data settings
- `research.toml`: Deep Research settings

You can edit these files individually to configure models, API keys, and other settings. The legacy `config.toml` is still supported for backward compatibility and overrides split files if present.

### API Keys
You can set API keys in two ways:
1. **Environment Variables**: Set `GOOGLE_API_KEY` (or other configured env vars) in your shell.
2. **Config File**: Add keys directly to `api.toml`.

Example `general.toml`:
```toml
[general]
default_model = "gf"
compact_banner = true
terminal_context_lines = 10
```

Example `api.toml`:
```toml
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

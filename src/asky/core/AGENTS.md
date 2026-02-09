# Core Package (`asky/core/`)

Central orchestration layer for multi-turn LLM conversations with tool execution.

## Module Overview

| Module | Purpose |
|--------|---------|
| `engine.py` | `ConversationEngine`, compaction, summary generation |
| `tool_registry_factory.py` | Default/research tool registry construction |
| `registry.py` | `ToolRegistry` for dynamic tool management |
| `api_client.py` | LLM API calls, retry logic, `UsageTracker` |
| `session_manager.py` | Session lifecycle, compaction |
| `prompts.py` | System prompt construction, tool call parsing |
| `utils.py` | Shared utilities |

## ConversationEngine (`engine.py`)

Central orchestrator for multi-turn conversations:

```python
class ConversationEngine:
    def __init__(self, model_config, tool_registry, summarize, ...):
        # Initialize with model, tools, session manager
        
    def run(self, messages) -> str:
        # Multi-turn loop: LLM call → parse tools → dispatch → repeat
        # Returns final answer after all tool calls complete
```

### Key Features

- **Multi-turn Loop**: Up to `MAX_TURNS` iterations
- **Tool Dispatch**: Via `ToolRegistry.dispatch()`
- **Context Compaction**: Via `check_and_compact()` when threshold exceeded
- **Graceful Exit**: `_execute_graceful_exit()` handles max-turns without answer
- **Error Handling**: Interactive 400 error recovery, general error display

### Lazy Loading

- Research cache instantiated only when compaction needs cached summaries
- Tool executors imported on first use via factory/wrapper helpers
- Research tool schemas/executors imported only for research mode

## Registry Factory (`tool_registry_factory.py`)

Builds `ToolRegistry` instances used by chat flow:
- `create_default_tool_registry()`: standard web/content/detail/custom/push-data tools
- `create_research_tool_registry()`: research-mode schemas/executors + custom tools

The module accepts optional executor callables so `engine.py` can preserve test patch
compatibility while keeping factory logic out of the conversation loop module.

## ToolRegistry (`registry.py`)

Dynamic tool management for LLM function calling:

```python
class ToolRegistry:
    def register(name, schema, executor): ...
    def get_schemas() -> List[Dict]: ...  # For LLM payload
    def dispatch(call, summarize, usage_tracker, ...): ...
```

### Tool Types

| Type | Examples |
|------|----------|
| Built-in | `web_search`, `get_url_content`, `get_url_details` |
| Custom | User-defined in config.toml under `[tool.name]` |
| Push Data | `push_data_{endpoint}` when endpoints enabled |
| Research | `extract_links`, `get_relevant_content`, etc. |

## API Client (`api_client.py`)

### Functions

- `get_llm_msg()`: Send messages with retry logic
- `count_tokens()`: Naive approximation (chars / 4)

### Request Behavior

- LLM requests are explicitly sent with `stream=false` in `api_client.py` because
  CLI/chat flows consume non-streamed JSON responses.

### UsageTracker

Tracks token usage per model alias for banner display.

### Retry Logic

- Exponential backoff with jitter
- Respects `Retry-After` header
- Configurable `MAX_RETRIES`, `INITIAL_BACKOFF`, `MAX_BACKOFF`

## SessionManager (`session_manager.py`)

### Key Concepts

- **Sessions are Persistent**: Conversation threads resumable anytime
- **Shell-Sticky**: Lock files in `/tmp/asky_session_{PID}` tie to terminal
- **Auto-Naming**: Names generated from query keywords (stopword filtering)

### Compaction Strategies

| Strategy | Description |
|----------|-------------|
| `summary_concat` | Concatenate existing summaries (fast) |
| `llm_summary` | LLM-generated session summary (comprehensive) |

Triggered when context reaches `SESSION_COMPACTION_THRESHOLD` (default 80%).

## Prompts (`prompts.py`)

- `build_system_prompt()`: Construct system message with current date
- `extract_calls()`: Parse tool calls from LLM response (JSON or XML format)
- `is_markdown()`: Detect markdown formatting in output

## Dependencies

```
engine.py
├── api_client.py → LLM API
├── registry.py → tool dispatch
├── prompts.py → prompt construction
├── session_manager.py → session persistence
├── tool_registry_factory.py → registry assembly
└── (lazy) research/ → research tools
```

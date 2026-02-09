# Config Package (`asky/config/`)

Configuration loading and constant exports from TOML files.

## Module Overview

| Module | Purpose |
|--------|---------|
| `__init__.py` | Load config, export all constants |
| `loader.py` | TOML loading, merging, model hydration |

## Configuration Files

Located in `data/config/`:

| File | Contents |
|------|----------|
| `general.toml` | Default model, timeouts, paths, UI settings |
| `api.toml` | API endpoint definitions (URL, key env var) |
| `models.toml` | Model definitions referencing APIs |
| `prompts.toml` | System prompts, summarization templates |
| `research.toml` | Research mode settings, embeddings, shortlist |
| `user.toml` | User-defined prompt shortcuts |
| `push_data.toml` | HTTP endpoint definitions for data push |

## Loading Flow (`loader.py`)

1. Load bundled config files from `data/config/`
2. Create user config at `~/.config/asky/` if missing
3. Deep-merge user config over defaults
4. Hydrate model definitions with API details

### Function: `load_config()`

Returns merged config dict with all sections.

### Function: `save_model_config()`

Persist model changes using `tomlkit` to preserve formatting.

## Constant Exports (`__init__.py`)

### General Settings

| Constant | Source |
|----------|--------|
| `DEFAULT_MODEL` | `general.default_model` |
| `MAX_TURNS` | `general.max_turns` |
| `REQUEST_TIMEOUT` | `general.request_timeout` |
| `DB_PATH` | `general.db_path` or env var |
| `LOG_LEVEL`, `LOG_FILE` | Logging config |

### Model Configuration

| Constant | Description |
|----------|-------------|
| `MODELS` | Dict of all model definitions |
| `SUMMARIZATION_MODEL` | Model for summarization tasks |

### Prompts

| Constant | Source |
|----------|--------|
| `SYSTEM_PROMPT` | `prompts.system_prefix` |
| `SEARCH_SUFFIX` | `prompts.search_suffix` |
| `RESEARCH_SYSTEM_PROMPT` | `prompts.research_system` |

### Research Settings

| Constant | Description |
|----------|-------------|
| `RESEARCH_CACHE_TTL_HOURS` | Cache expiry |
| `RESEARCH_CHUNK_SIZE` | Token chunk size |
| `RESEARCH_EMBEDDING_MODEL` | Embedding model name |
| `SOURCE_SHORTLIST_*` | Shortlist pipeline settings |

Current bundled shortlist defaults in `research.toml` set a wider pre-LLM budget
(`search_result_count=40`, `max_candidates=40`, `max_fetch_urls=20`) for richer
candidate pools while keeping fetch cost bounded.

### Custom Extensions

| Constant | Description |
|----------|-------------|
| `CUSTOM_TOOLS` | User-defined tool configs |
| `USER_PROMPTS` | Prompt shortcuts |
| `PUSH_DATA_ENDPOINTS` | Push data endpoints |
| `RESEARCH_SOURCE_ADAPTERS` | Non-HTTP source adapters |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ASKY_DB_PATH` | Override database path |
| `SERPER_API_KEY` | Serper search API key |
| `ASKY_SMTP_USER` | SMTP username |
| `ASKY_SMTP_PASSWORD` | SMTP password |

## Adding New Configuration

1. Add default value to appropriate `data/config/*.toml` file
2. Export constant in `config/__init__.py`
3. Update user config file if needed

## Dependencies

```
config/
├── __init__.py → loader.py
└── loader.py → (reads data/config/*.toml files)
```

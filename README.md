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
# Basic query
ask what is the weather in Berlin

# Show history
ask -H

# Continue from previous query
ask -c 1 tell me more about that

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

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_api_key_here
SEARXNG_HISTORY_DB_PATH=/custom/path/to/history.db
```

## Requirements

- Python 3.10+
- Running SearXNG instance (default: http://localhost:8888)
- LM Studio (for local models) or API keys for remote models

## License

MIT

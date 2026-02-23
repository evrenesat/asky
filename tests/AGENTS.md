# Tests Directory (`tests/`)

Pytest-based test suite organized by component.

## Running Tests

```bash
# Full test suite
uv run pytest

# Verbose with output
uv run pytest -v

# Specific test file
uv run pytest tests/test_cli.py

# Specific test function
uv run pytest tests/test_cli.py::test_function_name
```

## Test Organization

### CLI Tests

| File                 | Coverage                                                                           |
| -------------------- | ---------------------------------------------------------------------------------- |
| `test_cli.py`        | Argument parsing, command handlers                                                 |
| `test_presets.py`    | Command preset parsing/substitution/listing behavior                               |
| `test_completion.py` | Shell completion logic                                                             |
| `test_models_cli.py` | Model add/edit commands and role assignment actions (main/summarization/interface) |

### Core Tests

| File                            | Coverage                         |
| ------------------------------- | -------------------------------- |
| `test_llm.py`                   | LLM API calls, conversation loop |
| `test_tools.py`                 | Tool execution, web search       |
| `test_custom_tools.py`          | Custom tool dispatch             |
| `test_context_overflow.py`      | Context compaction               |
| `test_max_turns_duplication.py` | Multi-turn deduplication         |
| `test_xml_tool_parsing.py`      | XML tool call parsing            |

### API Tests

| File                      | Coverage                                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `test_api_client_bugs.py` | Regression tests for API client orchestration, research mode resolution, and Unicode-safe memory trigger removal |

### Storage Tests

| File               | Coverage                                                                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------- |
| `test_storage.py`  | Database operations, CRUD, transcript records, room/session bindings, session override file persistence |
| `test_sessions.py` | Session lifecycle, compaction                                                                           |

### Research Tests

| File                            | Coverage                     |
| ------------------------------- | ---------------------------- |
| `test_research_tools.py`        | Research tool executors      |
| `test_research_cache.py`        | Cache operations, TTL        |
| `test_research_vector_store.py` | Vector search, BM25          |
| `test_research_embeddings.py`   | Embedding client             |
| `test_research_chunker.py`      | Text chunking                |
| `test_research_adapters.py`     | Source adapters              |
| `test_research_prompts.py`      | Research prompt construction |
| `test_source_shortlist.py`      | Shortlist pipeline           |
| `test_startup_cleanup.py`       | Cache cleanup on startup     |

### Other Tests

| File                                   | Coverage                                                                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `test_config.py`                       | Configuration loading                                                                                                           |
| `test_xmpp_daemon.py`                  | XMPP daemon lifecycle, per-JID queueing, chunking                                                                               |
| `test_xmpp_router.py`                  | Allowlist and hybrid router behavior                                                                                            |
| `test_xmpp_commands.py`                | Remote command policy, transcript command surface, preset routing, and CLI-equivalent XMPP query alias/slash expansion behavior |
| `test_xmpp_group_sessions.py`          | Room/session binding persistence and session-scoped TOML override semantics (last-write-wins)                                   |
| `test_xmpp_client.py`                  | slixmpp runtime API compatibility (`process` vs loop fallback)                                                                  |
| `test_interface_planner.py`            | Interface model prompt contract, command-reference injection, JSON fallback behavior                                            |
| `test_voice_transcription.py`          | Background voice job pipeline and platform gating                                                                               |
| `test_image_transcription.py`          | Background image job pipeline and multimodal payload formatting                                                                  |
| `test_api_model_parameter_override.py` | API config parameter override merge behavior                                                                                    |
| `test_email.py`                        | Email sending                                                                                                                   |
| `test_html.py`                         | HTML stripping                                                                                                                  |
| `test_expansion.py`                    | Query expansion                                                                                                                 |
| `test_push_data.py`                    | Push data endpoints                                                                                                             |
| `test_summarization.py`                | Content summarization                                                                                                           |
| `test_integration.py`                  | End-to-end flows                                                                                                                |
| `test_research_eval_*.py`              | Evaluation harness dataset/assertion/matrix/source-provider contracts                                                           |
| `test_banner_*.py`                     | Banner rendering                                                                                                                |
| `test_logger.py`                       | Logging setup                                                                                                                   |

## Fixtures (`conftest.py`)

### Database Fixtures

- `temp_db`: Temporary SQLite database
- Session-scoped fixtures for expensive setup

### Mock Fixtures

- API response mocks
- Embedding client mocks
- Chroma client mocks

## Test Patterns

### Mocking LLM Responses

```python
@patch("asky.core.api_client.get_llm_msg")
def test_example(mock_llm):
    mock_llm.return_value = {"content": "Test response"}
    # Test code
```

### Testing with Temp Database

```python
def test_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("asky.config.DB_PATH", db_path)
    # Test code
```

### Testing CLI Commands

```python
def test_cli_command(capsys):
    with patch("sys.argv", ["asky", "--history", "5"]):
        main()
    captured = capsys.readouterr()
    assert "expected output" in captured.out
```

## Coverage Notes

- Core engine, storage, research modules have strong coverage
- CLI command handlers covered for main paths
- Integration tests validate end-to-end flows
- Performance tests check startup time regressions

# Storage Package (`asky/storage/`)

Data persistence layer using SQLite for message history and sessions.

## Module Overview

| Module | Purpose |
|--------|---------|
| `interface.py` | `HistoryRepository` ABC, `Interaction` and `Session` dataclasses |
| `sqlite.py` | `SQLiteHistoryRepository` implementation |

## Data Model (`interface.py`)

```python
@dataclass
class Interaction:
    id: Optional[int]
    timestamp: str
    session_id: Optional[int]  # NULL for history, set for sessions
    role: Optional[str]        # 'user' or 'assistant'
    content: str
    query: str                 # For history (user message)
    answer: str                # For history (assistant message)
    summary: Optional[str]
    model: str
    token_count: Optional[int]

@dataclass
class Session:
    id: int
    name: str
    model: str
    created_at: str
    compacted_summary: Optional[str]
    memory_auto_extract: bool
    max_turns: Optional[int]
    last_used_at: Optional[str]
    research_mode: bool
    research_source_mode: Optional[str]
    research_local_corpus_paths: List[str]
```

## Database Schema

### Tables

**`messages`** - Unified table for all messages:
- `id`: Primary key
- `timestamp`: ISO format
- `session_id`: NULL for history entries, set for session messages
- `role`: 'user' or 'assistant'
- `content`: Message text
- `summary`: Optional summary
- `model`: Model alias used
- `token_count`: Approximate tokens

**`sessions`** - Session metadata:
- `id`: Primary key
- `name`: Human-readable name
- `model`: Default model for session
- `created_at`: Creation timestamp
- `compacted_summary`: Concatenated history after compaction
- `memory_auto_extract`: Elephant-mode flag
- `max_turns`: Optional per-session max-turn override
- `last_used_at`: Last activity timestamp
- `research_mode`: Session-owned research-mode flag
- `research_source_mode`: `web_only|local_only|mixed`
- `research_local_corpus_paths`: JSON list of persisted corpus pointers

## SQLiteHistoryRepository (`sqlite.py`)

### History Methods

| Method | Purpose |
|--------|---------|
| `save_interaction()` | Save query/answer as User + Assistant row pair |
| `get_history()` | Fetch recent interactions |
| `get_interaction_context()` | Build context string from IDs |
| `delete_messages()` | Delete by ID, range, or all |
| `get_db_record_count()` | Count non-session records |

### Session Methods

| Method | Purpose |
|--------|---------|
| `create_session()` | Create new session, return ID |
| `get_session_by_id/name()` | Lookup session |
| `get_sessions_by_name()` | Find all matching sessions |
| `save_message()` | Add message to session |
| `get_session_messages()` | Retrieve session history |
| `compact_session()` | Replace history with summary |
| `list_sessions()` | Recent sessions listing |
| `delete_sessions()` | Delete sessions and messages |
| `update_session_research_profile()` | Persist session research profile metadata |
| `convert_history_to_session()` | Convert interaction to session (session names strip terminal-context wrapper prefixes) |

## Design Decisions

### Unified Messages Table

Both history and session messages share the `messages` table:
- **History entries**: `session_id IS NULL`, stored as paired rows
- **Session messages**: `session_id IS NOT NULL`, individual rows

This consolidation simplifies storage while maintaining clear separation.

### Interaction ID Semantics

For history, the "interaction ID" refers to the **assistant message row ID**, as history is stored as user/assistant pairs with the assistant ID being the higher value.

## Usage

```python
from asky.storage import get_history, save_interaction, get_total_session_count

# Save a Q&A exchange
save_interaction(query="Hello", answer="Hi there!", model="gpt-4")

# Get recent history
interactions = get_history(limit=10)

# Get global session count (used by banner totals)
total_sessions = get_total_session_count()
```

## Dependencies

```
storage/
├── interface.py (pure Python, no dependencies)
└── sqlite.py → config/ (for DB_PATH)
```

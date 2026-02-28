# Storage Package (`asky/storage/`)

Data persistence layer using SQLite for message history and sessions.

## Module Overview

| Module | Purpose |
|--------|---------|
| `interface.py` | `HistoryRepository` ABC, `Interaction` / `Session` / `TranscriptRecord` / room-binding / session-override dataclasses |
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
    shortlist_override: Optional[str]
    query_defaults: Dict[str, Any]

@dataclass
class TranscriptRecord:
    id: int
    session_id: int
    session_transcript_id: int
    jid: str
    created_at: str
    status: str
    audio_url: str
    audio_path: str
    transcript_text: str
    error: str
    duration_seconds: Optional[float]
    used: bool

@dataclass
class ImageTranscriptRecord:
    id: int
    session_id: int
    session_image_id: int
    jid: str
    created_at: str
    status: str
    image_url: str
    image_path: str
    transcript_text: str
    error: str
    duration_seconds: Optional[float]
    used: bool

@dataclass
class RoomSessionBinding:
    room_jid: str
    session_id: int
    updated_at: str

@dataclass
class SessionOverrideFile:
    session_id: int
    filename: str
    content: str
    updated_at: str

@dataclass
class UploadedDocument:
    id: int
    content_hash: str
    file_path: str
    original_filename: str
    file_extension: str
    mime_type: str
    file_size: int
    created_at: str
    updated_at: str
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
- `shortlist_override`: Per-session shortlist override (`on|off|NULL`)
- `query_defaults`: JSON object storing query-behavior defaults (model/tools/system prompt/etc.)

**`transcripts`** - Daemon voice transcript records:
- `id`: Primary key
- `session_id`: Owning session
- `session_transcript_id`: Numeric ID scoped to session
- `jid`: Sender full JID
- `status`: `pending|completed|failed`
- `audio_url`, `audio_path`: Source/media artifact metadata
- `transcript_text`: Completed transcript text
- `error`: Failure details
- `duration_seconds`: Transcription runtime
- `used`: Whether transcript has been consumed via `transcript use`

**`image_transcripts`** - Daemon image transcript records:
- `id`: Primary key
- `session_id`: Owning session
- `session_image_id`: Numeric image/transcript ID scoped to session
- `jid`: Sender full JID
- `status`: `pending|completed|failed`
- `image_url`, `image_path`: Source/media artifact metadata
- `transcript_text`: Completed image explanation text
- `error`: Failure details
- `duration_seconds`: Image-model runtime
- `used`: Whether image transcript has been consumed via pointer usage

**`room_session_bindings`** - Persistent daemon room/session mapping:
- `room_jid`: Lowercased room bare JID (primary key)
- `session_id`: Active bound session for that room
- `updated_at`: Last bind/switch timestamp

**`session_override_files`** - Session-scoped override TOML snapshots:
- `session_id`: Owning session
- `filename`: Supported filename key (`general.toml`, `user.toml`)
- `content`: Sanitized TOML content persisted with replace semantics
- `updated_at`: Last write timestamp

**`uploaded_documents`** - Global deduplicated uploaded document artifacts:
- `content_hash`: SHA-256 hash (unique)
- `file_path`: Persisted local path under configured research corpus root
- `original_filename`, `file_extension`, `mime_type`, `file_size`
- `created_at`, `updated_at`: ingestion metadata

**`uploaded_document_urls`** - URL to uploaded-document mapping cache:
- `url`: Canonical source URL (primary key)
- `document_id`: Referenced document row
- `created_at`, `updated_at`

**`session_uploaded_documents`** - Session/document link table:
- `(session_id, document_id)`: Composite primary key
- `linked_at`: association timestamp

## SQLiteHistoryRepository (`sqlite.py`)

### History Methods

| Method | Purpose |
|--------|---------|
| `save_interaction()` | Save query/answer as User + Assistant row pair |
| `get_history()` | Fetch recent interactions across all messages (session-bound and non-session) |
| `get_interaction_context()` | Build context string from IDs with same-scope partner expansion |
| `delete_messages()` | Delete by ID, range, or all across all messages (same-scope smart expansion) |
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
| `update_session_shortlist_override()` | Persist/clear session shortlist override |
| `update_session_query_defaults()` | Persist JSON query-behavior defaults |
| `update_session_name()` | Rename session with uniqueness guarantees |
| `convert_history_to_session()` | Convert interaction to session (session names strip terminal-context wrapper prefixes) |
| `create_transcript()` | Insert transcript row with session-scoped incrementing ID |
| `update_transcript()` | Update status/text/error/usage fields |
| `list_transcripts()` | List newest transcript rows for one session |
| `get_transcript()` | Lookup transcript by `(session_id, session_transcript_id)` |
| `prune_transcripts()` | Delete oldest transcripts beyond retention cap |
| `create_image_transcript()` | Insert image transcript row with session-scoped incrementing ID |
| `update_image_transcript()` | Update image transcript status/text/error/usage fields |
| `list_image_transcripts()` | List newest image transcripts for one session |
| `get_image_transcript()` | Lookup image transcript by `(session_id, session_image_id)` |
| `prune_image_transcripts()` | Delete oldest image transcripts beyond retention cap |
| `set_room_session_binding()` | Upsert room -> session binding |
| `get_room_session_binding()` | Lookup bound session for one room |
| `list_room_session_bindings()` | List all bound rooms |
| `save_session_override_file()` | Upsert one session override TOML snapshot |
| `get_session_override_file()` | Lookup one override file by session + filename |
| `list_session_override_files()` | List override file snapshots for one session |
| `copy_session_override_files()` | Copy override file snapshots across sessions |
| `upsert_uploaded_document()` | Upsert global uploaded document by content hash |
| `get_uploaded_document_by_hash()` | Lookup uploaded document by content hash |
| `get_uploaded_document_by_url()` | Lookup uploaded document by URL mapping |
| `save_uploaded_document_url()` | Upsert URL->document mapping |
| `link_session_uploaded_document()` | Link one uploaded document to a session |
| `list_session_uploaded_documents()` | List uploaded documents linked to a session |
| `clear_session_uploaded_documents()` | Clear all uploaded-document links for a session |

## Design Decisions

### Unified Messages Table

Both history and session messages share the `messages` table:
- **History entries**: `session_id IS NULL`, stored as paired rows
- **Session messages**: `session_id IS NOT NULL`, individual rows

This consolidation simplifies storage while maintaining clear separation.

### Shell-Sticky Lock File Mechanism

Sessions are tied to the current terminal via a lock file: `/tmp/asky_session_{PID}`.

- Written atomically (write to `.tmp` then `os.replace`) when a shell session is activated.
- Cleaned up via `atexit` handler on normal exit.
- On startup, if the lock file's PID is dead (no live process), the stale file is ignored.
- To manually clear a stuck session: `asky --end-session` or delete `/tmp/asky_session_<PID>`.
- PID reuse is an inherent risk: if a new process reuses the PID of a previously crashed asky, it could inherit the wrong session. The atexit handler mitigates this for clean exits.

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

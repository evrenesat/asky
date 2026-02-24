# Daemon Package (`asky/daemon/`)

Optional XMPP client daemon runtime. When `asky --xmpp-daemon` is run, this package handles XMPP transport, message routing, session management, and optional voice/image transcription pipelines.

## Module Overview

| Module                      | Purpose                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| `service.py`                | `XMPPDaemonService` — top-level coordinator, per-JID queue management       |
| `xmpp_client.py`            | Slixmpp transport wrapper — connects, sends, and receives XMPP stanzas      |
| `router.py`                 | `MessageRouter` — ingress policy (allowlist, room binding, confirmation)    |
| `command_executor.py`       | Command/query bridge — policy gate, transcript namespace, `AskyClient` call |
| `session_profile_manager.py`| Room/session bindings + session override file management                    |
| `interface_planner.py`      | LLM-based intent classification for non-prefixed messages                   |
| `voice_transcriber.py`      | Background audio transcription via `mlx-whisper`                            |
| `image_transcriber.py`      | Background image description via image-capable LLM                         |
| `transcript_manager.py`     | `TranscriptManager` — transcript lifecycle, pending confirmation tracking   |
| `chunking.py`               | Outbound response chunking                                                  |
| `menubar.py`                | macOS `rumps` menubar app controlling daemon lifecycle                      |
| `app_bundle_macos.py`       | macOS `.app` bundle creation/update for Spotlight integration               |
| `startup.py`                | Cross-platform startup-at-login dispatcher                                  |
| `startup_macos.py`          | LaunchAgent plist management                                                |
| `startup_linux.py`          | systemd user service management                                             |
| `startup_windows.py`        | Windows Startup folder launcher script                                      |
| `errors.py`                 | Daemon-specific exception types                                             |

---

## Per-JID Queue and Worker Lifecycle

`service.py` serializes all processing for each conversation through a per-key queue:

- **Queue key**: resolved from the incoming XMPP payload — room JID for groupchat messages, sender bare JID for direct messages.
- **Queue**: a `queue.Queue` of callables created on first message from that key.
- **Worker thread**: a single daemon thread per queue key, started on first message (or restarted if the previous thread has exited). Thread restart is guarded by `_jid_workers_lock` to prevent double-spawn under concurrent delivery.
- **Ordering guarantee**: messages from the same conversation are always processed in arrival order. Messages from different conversations are fully concurrent.
- **Shutdown**: worker threads are daemon threads and exit automatically when the main process exits; no graceful drain is guaranteed on abrupt termination.

---

## Authorization Model

### Direct messages (`chat` stanzas)

- Sender's full JID is checked against `allowlist` (configured in `xmpp.toml`).
- Allowlist entries support:
  - bare JID (`user@domain`) — allows any resource.
  - full JID (`user@domain/resource`) — pins one exact resource.
- Unauthorized senders are silently ignored (no response).

### Group chat (`groupchat` stanzas)

- The room's bare JID must be pre-bound in `room_session_bindings` (via a trusted-room invite or explicit bind command).
- Individual sender identity is not checked for authorization — any occupant of a bound room can send commands.
- See "Known Limitations" below for the implication of this design.

---

## Command Routing Order

For each incoming message the router applies these stages in order:

1. **Authorization / room guard** — drop if not authorized.
2. **Inline TOML upload** — if message contains a fenced TOML block (or OOB TOML URL), validate and persist as session override.
3. **`/session` command surface** — `/session`, `/session new`, `/session child`, `/session <id|name>`, `/session clear`.
4. **Transcript confirmation shortcuts** — `yes` / `no` if a transcript is pending for this conversation key.
5. **Interface planner** (when `general.interface_model` is configured and message is not prefixed with `command_prefix`):
   - LLM classifies input as `command` or `query` action.
   - Unresolvable (malformed JSON, unknown action type, empty command) fall through to query behavior.
6. **Command prefix gate** — messages starting with `command_prefix` (default `/asky`) are treated as direct commands.
7. **Command vs. query heuristic** — remaining text is checked for command-like patterns; otherwise routed as query text.
8. **Remote policy gate** — blocked flags are rejected after planning/expansion so they cannot be bypassed via presets or planner.
9. **`AskyClient.run_turn()`** — final command or query execution.

---

## Interface Planner Fallback Behavior

When the interface planner is active and the LLM returns output that cannot be resolved:

- **Malformed JSON**: planner output cannot be parsed → falls back to treating the original message as a plain query.
- **Unknown `action_type`**: value is neither `command` nor `query` → falls back to plain query.
- **Empty `command_text`** for a `command` action: treated as a query.
- **Empty `query_text`** for a `query` action: treated as a query (no-op query with empty text).

The fallback path means messages that confuse the planner are silently routed as queries rather than dropped.

---

## Voice Transcription Pipeline

Requires `mlx-whisper` and macOS.

1. Incoming XMPP message with OOB audio URL is detected by `router.py`.
2. Audio file is streamed to `voice_storage_dir` (background thread via `VoiceTranscriber`).
3. `mlx-whisper` transcription runs in a worker pool (`voice_workers` threads).
4. On completion, transcript is persisted to `transcripts` table with `status=completed`.
5. Sender is notified with a text preview and confirmation prompt.
6. **Confirmation**: `yes` runs the transcript as a query; `no` stores without executing.
7. With `voice_auto_yes_without_interface_model=true` and no interface model, transcripts are auto-run without `yes`.

**Status states**: `pending` → `completed` | `failed`.

Non-macOS platforms: transcription requests fail immediately with an error message.

---

## Transcript Confirmation Scope

Transcript confirmation (`yes`/`no`) is keyed by **conversation** (room JID for groupchat, sender JID for direct), not by individual user.

In a group chat:
- Any occupant of the room can confirm or reject any pending transcript in that conversation.
- There is at most one pending transcript per conversation key at a time.
- A second audio message arriving before confirmation replaces the pending state.

---

## Session Override File Contract

Users can upload TOML config overrides over XMPP. The contract:

- **Supported files**: `general.toml`, `user.toml` (defined in `ALLOWED_OVERRIDE_FILENAMES`).
- **Delivery**: inline fenced TOML block (`filename.toml ``` toml … ````) or OOB TOML URL.
- **Semantics**: last-write-wins per file per session. Uploading a new `general.toml` replaces the stored one for that session entirely (no merge).
- **Allowed keys**:
  - `general.toml`: only `[general]` section; only `default_model` and `summarization_model` keys; values must be valid known model aliases.
  - `user.toml`: only `[user_prompts]` section; arbitrary string keys/values.
- **Unsupported keys**: silently ignored with a warning included in the response.
- **Applied at**: session start / session switch. Override files are loaded into the runtime config for the lifetime of that session.
- **Cross-session inheritance**: when creating a child session (`/session child`), override files are copied from the parent session.

---

## Known Limitations

- **Single pending transcript per conversation**: only the most recent audio/image upload awaits confirmation. Sending a second file before confirming the first silently replaces the pending confirmation.
- **No replay protection**: the system does not validate that a received message is unique or recent. A replayed XMPP stanza would be processed again.
- **Group chat authorization is room-level**: any occupant of a bound room can send commands — individual sender identity is not re-checked inside a bound room.
- **JID worker threads are daemon threads**: they are killed without drain on process exit. In-flight tasks may be lost if the daemon is killed uncleanly.

---

## Dependencies

```
daemon/
├── service.py → xmpp_client.py, router.py, chunking.py
├── router.py → command_executor.py, session_profile_manager.py,
│               voice_transcriber.py, image_transcriber.py, transcript_manager.py
├── command_executor.py → api/client.py, session_profile_manager.py
├── session_profile_manager.py → storage/sqlite.py
└── menubar.py → service.py (subprocess/lifecycle control)
```

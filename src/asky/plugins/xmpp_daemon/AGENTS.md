# XMPP Daemon Plugin (`asky/plugins/xmpp_daemon/`)

Built-in plugin providing the XMPP transport for asky. This package handles natural-language remote command/query routing, voice/image transcription, and ad-hoc command registration.

## Module Overview

| Module                       | Purpose                                                                    |
| ---------------------------- | -------------------------------------------------------------------------- |
| `plugin.py`                  | `XMPPDaemonPlugin` — registers transport and contributes tray menu entries |
| `xmpp_service.py`            | `XMPPService` — wires router, background workers, and XMPP client          |
| `xmpp_client.py`             | `AskyXMPPClient` — clean wrapper around `slixmpp`                          |
| `router.py`                  | `DaemonRouter` — ingress routing, authorization, and policy enforcement    |
| `command_executor.py`        | `CommandExecutor` — translates remote text to local AskyClient turns       |
| `interface_planner.py`       | `InterfacePlanner` — interface-model planner for natural-language routing  |
| `session_profile_manager.py` | `SessionProfileManager` — persists room/session bindings and overrides     |
| `transcript_manager.py`      | `TranscriptManager` — lifecycle of audio/image transcriptions              |
| `voice_transcriber.py`       | `VoiceTranscriber` — local (SFSpeech) or remote (HF) voice jobs            |
| `image_transcriber.py`       | `ImageTranscriber` — multimodal LLM transcription jobs                     |
| `document_ingestion.py`      | `DocumentIngestionService` — auto-ingestion of uploaded document URLs      |
| `adhoc_commands.py`          | `AdHocCommandHandler` — XEP-0050 ad-hoc command registration and dispatch  |
| `xmpp_formatting.py`         | Markdown-to-XHTML and ASCII table rendering for outgoing messages          |
| `chunking.py`                | Outbound message splitting for XMPP server length limits                   |
| `query_progress.py`          | Background status updates (XEP-0308) for in-flight queries                 |

---

## Authorization Model

Authorization is handled by `router.py`.

### Direct messages (`chat` stanzas)

- Sender's full JID is checked against the allowlist (configured in `xmpp.toml`).
- Allowlist entries support:
  - bare JID (`user@domain`) — allows any resource.
  - full JID (`user@domain/resource`) — pins one exact resource.
- Unauthorized senders are silently ignored.

### Group chat (`groupchat` stanzas)

- The room's bare JID must be pre-bound in `room_session_bindings` (via trusted-room invite or `/session bind`).
- Individual sender identity is not checked for authorization — any occupant of a bound room can interact.

---

## Command Routing Order

For each incoming message in `router.py`:

1. **Authorization / room guard** — drop if not authorized.
2. **Inline TOML upload** — validate and persist as session override.
3. **`/session` command surface** — `/session`, `/session new`, `/session child`, `/session <id|name>`, `/session clear`.
4. **Transcript confirmation shortcuts** — `yes` / `no` if a transcript is pending.
5. **Interface planner** — when configured and message is not command-prefixed.
6. **Command prefix gate** — messages starting with `command_prefix` (default `/asky`).
7. **Command vs. query heuristic** — remaining text.
8. **Remote policy gate** — blocked flags (config mutations, bootstrap flags) are rejected.
9. **`AskyClient.run_turn()`** — final execution.

---

## Per-JID Queue and Worker Lifecycle

`xmpp_service.py` serializes processing per conversation:

- **Queue key**: room JID for groupchat, sender bare JID for direct messages.
- **Worker thread**: daemon thread per key, started on first message. Restarts are guarded by `_jid_workers_lock`.
- **Ordering**: messages from the same conversation are processed in arrival order.

---

## Ad-Hoc Commands (XEP-0050)

Implements structured commands like `asky#status`, `asky#query`, `asky#list-sessions`, etc. Registered at session start if `slixmpp` ad-hoc plugins are available.

- Form-based multi-step commands check identity against the router's allowlist.
- Model results are delivered as regular messages through the per-conversation queue.
- Progress updates are emitted approximately every 2 seconds during execution.

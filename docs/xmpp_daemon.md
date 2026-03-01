# XMPP Daemon Mode

## What this does

`asky --daemon` starts asky as a background process that logs into an XMPP account and waits for messages. You can then send it queries from any XMPP client app - on your phone, tablet, or another computer - and get answers back in the chat.

XMPP (also called Jabber) is an open messaging protocol. It works like email: addresses look like `user@server.com`, and many different clients and servers can talk to each other. You need two XMPP accounts: one for the bot (that asky logs into), and one for yourself (to send messages from).

**Free XMPP account options:**
- [jabber.at](https://jabber.at) - free, no signup friction
- [conversations.im](https://account.conversations.im/register/) - free, optimized for mobile clients

**Recommended XMPP client apps:**
- Android: [Conversations](https://conversations.im/) or [Cheogram](https://cheogram.com/)
- iOS: [Monal](https://monal-im.org/) or [Siskin IM](https://siskin.im/)
- Desktop: [Gajim](https://gajim.org/) (Windows, Linux, macOS), [Beagle IM](https://beagle.im/) (macOS)

For file attachments (sending documents to asky for analysis), your client app needs to support XEP-0363 HTTP file upload. Conversations, Cheogram, Monal, and Gajim all support this.

**macOS:** With `rumps` installed, daemon mode adds a menu bar icon for controlling start/stop and voice on/off. On other platforms, the daemon runs in the foreground.

<!-- SCREENSHOT: macOS menu bar showing the asky icon and its dropdown menu with Start XMPP / Stop XMPP / Enable Voice / Enable Run at Login options -->

## What it looks like in practice

Once the daemon is running, you send messages to the bot account from your XMPP client:

```
You:   What is the capital of Japan?
asky:  Tokyo.

You:   \research Give me a summary of recent fusion energy news
asky:  [researches web, sends back multi-paragraph summary]

You:   [sends a voice message]
asky:  Transcript ready: "what are the key points in the document I sent earlier"
       Reply "yes" to run this as a query, or "no" to skip.

You:   yes
asky:  [runs the query against indexed document and responds]
```

Only contacts listed in `allowed_jids` get responses. All others are silently ignored.

## Install Optional Dependencies

Use one of these extras:

```bash
# XMPP text-only daemon
uv pip install "asky-cli[xmpp]"

# Voice transcription dependency
uv pip install "asky-cli[mlx-whisper]"

# macOS bundle (iterm2 + mlx-whisper + rumps + slixmpp)
uv pip install "asky-cli[mac]"
```

## Configure `xmpp.toml`

Before configuring, have these ready:

1. A bot XMPP account for asky to log into (e.g., `mybot@jabber.at`)
2. Your own XMPP account to send messages from (e.g., `me@jabber.at`)
3. The bot account's password stored in an environment variable

Main settings live in `~/.config/asky/xmpp.toml`:

```toml
[xmpp]
enabled = true

# JID = Jabber ID, the XMPP address of the bot account asky logs into
jid = "mybot@jabber.at"

# Name of the environment variable that holds the bot account's password
password_env = "ASKY_XMPP_PASSWORD"

# An arbitrary label for this connection (visible in some XMPP clients)
resource = "asky"

# JIDs allowed to send queries. All others are silently ignored.
# Bare JID (user@server) allows any device/client for that user.
# Full JID (user@server/resource) pins one specific client session.
allowed_jids = ["me@jabber.at"]

command_prefix = "/asky"
interface_planner_include_command_reference = true
response_chunk_chars = 3000
```

*Note: Voice and image transcription configuration has been moved to separate plugins. See `~/.config/asky/voice_transcriber.toml` and `~/.config/asky/image_transcriber.toml`.*

Set the password in your environment (do not put it directly in the file):

```bash
export ASKY_XMPP_PASSWORD="your-bot-account-password"
```

Other constraints:

- Unauthorized senders are ignored with no response.
- Only direct `chat` messages are processed. Group chat is not supported.
- Use `asky --config daemon edit` for an interactive editor instead of editing the file manually.

## Run Daemon

```bash
asky --daemon
```

- macOS + `rumps`: launches menubar app.
- non-macOS, or macOS without `rumps`: uses foreground daemon mode.
- `asky --config daemon edit` works on all platforms and edits `xmpp.toml` + startup registration.
- macOS menubar runtime is single-instance. If already running, `asky --daemon` prints `Error: asky menubar daemon is already running.` and exits with status `1`.
- Menubar does not edit XMPP credentials/allowlist. Configure those only via `asky --config daemon edit`.

Runtime behavior:

- one serialized processing queue per sender JID
- ordered outbound chunking for long responses (`response_chunk_chars`)
- sender-scoped persistent sessions named `xmpp:<jid>`

Menubar action labels are state-aware:

- `Start XMPP` / `Stop XMPP`
- `Enable Voice` / `Disable Voice`
- `Enable Run at Login` / `Disable Run at Login`

## Routing Behavior

### When `general.interface_model` is configured

- messages starting with `command_prefix` (default `/asky`) are treated as direct commands
- other messages are planned by the interface model into either:
  - a command action
  - a normal query action

### When `general.interface_model` is empty

- command-like inputs are treated as commands
- regular text is treated as query text

## Interface Planner Prompt Contract

When `general.interface_model` is configured and message is not prefixed with `/asky`:

- planner receives one `system` message and one `user` message
- tools are disabled for planner call (`use_tools=false`)
- `user` content is the raw incoming XMPP message text
- `system` prompt source:
  - `prompts.interface_planner_system` from `prompts.toml`
  - plus generated command/policy reference when `xmpp.interface_planner_include_command_reference=true`

Planner output contract (strict JSON):

```json
{
  "action_type": "command|query|chat",
  "command_text": "",
  "query_text": ""
}
```

Planner call shape (current implementation):

```json
[
  {
    "role": "system",
    "content": "<prompts.interface_planner_system [+ optional command reference block]>"
  },
  {
    "role": "user",
    "content": "<raw incoming XMPP message body>"
  }
]
```

Planner guidance/invariants:

- `command_text` must contain raw command tokens only (no `/asky` prefix)
- for `action_type=command`, `query_text` must be empty
- for `action_type=query` and `action_type=chat`, `command_text` must be empty
- if planner output is invalid JSON or invalid action, router falls back to query behavior

### Planner Fallback Behavior

When the planner cannot resolve a valid action, the original message is routed as a plain query. This covers:

- **Malformed JSON**: LLM output cannot be parsed.
- **Unknown `action_type`**: value is neither `command`, `query`, nor `chat`.
- **Empty `command_text`** for a `command` action.
- `action_type=chat` is treated as a non-command user query path and executed via
  the same turn pipeline with chat-oriented handling.

The fallback means messages that confuse the planner are silently processed as queries rather than dropped. If you observe unexpected query behavior for commands, verify the planner's output against the JSON contract above.

Generated command reference includes:

- supported remote command categories (`history`, `session`, `transcript`, corpus/section commands, research flags)
- explicit remote blocked flags/policy (`--mail`, `--open`, `-tl`, delete/model-mutation/bootstrap flags)

## Command Presets Over XMPP

Presets are defined in `user.toml` under `[command_presets]` and can be invoked from XMPP:

- list: `\presets`
- invoke: `\name arg1 "arg 2"`

Rules:

- first-token only (`\name` must be the first token)
- placeholders: `$1..$9`, `$*`
- extra unreferenced args are appended
- no recursive preset expansion

## Voice Messages (Phase 1: macOS)

When the `voice_transcriber` plugin is enabled and `mlx-whisper` is installed:

- audio URLs from XMPP OOB payloads are streamed to disk
- transcription runs in background workers
- text message handling continues without waiting
- completed transcripts are stored in SQLite and announced with preview
- confirmation shortcuts:
  - `yes`: run the latest pending transcript as a query now
  - `no`: keep transcript stored without running it
- when an audio OOB URL is present, URL-only message bodies are ignored to avoid accidental model calls on the attachment link
- with `auto_yes_without_interface_model=true` (in `voice_transcriber.toml`) and no interface model configured, completed transcripts are auto-run as queries without waiting for `yes`

Non-macOS transcription requests fail with an explicit error.

Hugging Face token handling (recommended for faster/less rate-limited model downloads):

- set `hf_token_env` in `voice_transcriber.toml` to the environment variable name that contains your token
- optionally set `hf_token` directly in `voice_transcriber.toml` (less secure)
- daemon exports token to both `HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN` before transcription calls

## Transcript Commands

Daemon command namespace:

```text
transcript list [limit]
transcript show <id>
transcript use <id>
transcript clear
```

IDs are numeric and session-scoped per sender session.

### Confirmation Scope in Group Chats

Transcript confirmation (`yes` / `no`) is keyed by **conversation**, not by the individual user who sent the audio:

- In a **direct chat**, confirmation is scoped to the sender JID — only that contact can confirm.
- In a **group chat**, confirmation is scoped to the room JID — any occupant can confirm any pending transcript in the room.

There is at most one pending transcript per conversation at a time. A new audio message arriving before confirmation replaces the pending state.

## Remote Safety Policy

After planning and preset expansion, daemon command execution still enforces policy.

Blocked remotely (authoritative list from `command_executor.REMOTE_BLOCKED_FLAGS`):

- `--mail`
- `--open`
- `-tl` / `--terminal-lines`
- `--delete-messages`
- `--delete-sessions`
- `--all`
- `--clean-session-research`
- `--config`
- `--add-model`
- `--edit-model`
- `--clear-memories`
- `--delete-memory`
- `--daemon` / `--xmpp-daemon`
- `--xmpp-menubar-child`
- `--config daemon edit` / `--edit-daemon`
- `--completion-script`

Allowed remotely:

- normal query turns
- retrieval/research commands
- `--push-data`

## Session Commands and XEP-0050 Ad-Hoc Commands

You can manage your conversation state remotely. 

### Slash Commands

The following session management slash commands are natively routed and available even when `interface_model` is unconfigured:

- `/session clear`: Clears all conversation messages from the current active session without touching transcripts or media attachments. It requires a `yes/no` confirmation from the sender (or from anyone in a group chat) before executing.
- `/session child`: Create a child session inheriting current overrides.
- `/session <id|name>`: Switch to an existing session by ID or exact name.

### XEP-0050 Ad-Hoc Commands

The daemon exposes standard XEP-0050 Ad-Hoc commands (e.g. reachable via `Execute Command` in Gajim or similar menus in other clients) giving a structured form-based UI for:

- **Switch Session**: Allows switching the active profile to another existing session.
- **Clear Session**: Prompts a boolean checkbox form to delete messages in the active session while retaining media/transcripts.
- **Use Transcript**: Allows selecting a previously transcribed audio message to execute as a new text query.

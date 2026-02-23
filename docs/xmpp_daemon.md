# XMPP Daemon Mode

`asky` can run as a foreground XMPP client so authorized users can use chat messages as a remote interface.

## Install Optional Dependencies

Use one of these extras:

```bash
# XMPP text-only daemon
uv pip install "asky-cli[xmpp]"

# Voice transcription only
uv pip install "asky-cli[voice]"

# Full daemon stack (XMPP + voice)
uv pip install "asky-cli[daemon]"
```

## Configure `xmpp.toml`

Main settings live in `~/.config/asky/xmpp.toml`:

```toml
[xmpp]
enabled = true
jid = "bot@example.com"
password_env = "ASKY_XMPP_PASSWORD"
resource = "asky"
allowed_jids = ["alice@example.com/phone"]
command_prefix = "/asky"
interface_planner_include_command_reference = true
response_chunk_chars = 3000

voice_enabled = true
voice_workers = 1
voice_max_size_mb = 500
voice_model = "mlx-community/whisper-tiny"
voice_hf_token_env = "HF_TOKEN"
voice_auto_yes_without_interface_model = true
```

Important constraints:

- `allowed_jids` accepts both:
  - bare JID (`alice@example.com`) to allow any resource.
  - full JID (`alice@example.com/phone`) to pin one exact resource.
- Unauthorized senders are ignored with no response.
- Only direct `chat` stanzas are processed.
- Keep `password` out of files in production and use `password_env`.

## Run Foreground Daemon

```bash
asky --xmpp-daemon
```

Runtime behavior:

- one serialized processing queue per sender JID
- ordered outbound chunking for long responses (`response_chunk_chars`)
- sender-scoped persistent sessions named `xmpp:<jid>`

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
  "action_type": "command|query",
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
- for `action_type=query`, `command_text` must be empty
- if planner output is invalid JSON or invalid action, router falls back to query behavior

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

When `voice_enabled=true` and `mlx-whisper` is installed:

- audio URLs from XMPP OOB payloads are streamed to disk
- transcription runs in background workers
- text message handling continues without waiting
- completed transcripts are stored in SQLite and announced with preview
- confirmation shortcuts:
  - `yes`: run the latest pending transcript as a query now
  - `no`: keep transcript stored without running it
- when an audio OOB URL is present, URL-only message bodies are ignored to avoid accidental model calls on the attachment link
- with `voice_auto_yes_without_interface_model=true` and no interface model configured, completed transcripts are auto-run as queries without waiting for `yes`

Non-macOS transcription requests fail with an explicit error.

Hugging Face token handling (recommended for faster/less rate-limited model downloads):

- set `voice_hf_token_env` to the environment variable name that contains your token
- optionally set `voice_hf_token` directly in `xmpp.toml` (less secure)
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

## Remote Safety Policy

After planning and preset expansion, daemon command execution still enforces policy.

Blocked remotely:

- `--mail`
- `--open`
- `-tl` / `--terminal-lines`
- destructive/history/session deletion and model mutation commands
- daemon bootstrap flags (`--xmpp-daemon`, completion script output)

Allowed remotely:

- normal query turns
- retrieval/research commands
- `--push-data`

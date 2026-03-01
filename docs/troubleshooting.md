# Troubleshooting

Common problems and how to fix them. If something is not covered here, check the log file at `~/.config/asky/logs/asky.log` (set `log_level = "DEBUG"` in `general.toml` for more detail).

---

## Setup

### "Error: Unknown model alias: "

You haven't set a default model. Edit `~/.config/asky/general.toml` and set:

```toml
[general]
default_model = "gf"  # or any alias defined in models.toml
```

To see available aliases: `cat ~/.config/asky/models.toml`

To add a new alias interactively: `asky --config model add`

---

### "Warning: GOOGLE_API_KEY not found in environment variables"

The model you are using expects an API key that isn't set. Check which env variable the model needs:

```bash
cat ~/.config/asky/api.toml
```

Find the `[api.<name>]` section that your model references (via the `api = "..."` field in `models.toml`) and set the corresponding `api_key_env` variable in your shell.

---

### HTTP 401 or authentication errors from the LLM

Your API key is set but invalid, or the wrong key is set for the provider. Verify:

1. The key is for the correct provider (Gemini key vs OpenAI key, etc.)
2. The env variable name matches `api_key_env` in `api.toml`
3. The key has not expired or been revoked

---

### asky starts but web search returns nothing or fails

The default search provider is SearXNG at `http://localhost:8888`. If you don't have SearXNG running locally, all web search tool calls will fail silently or with a connection error.

Fix option 1 - use Serper instead:

```bash
export SERPER_API_KEY="your-key"
```

```toml
# ~/.config/asky/general.toml
[general]
search_provider = "serper"
```

Fix option 2 - run SearXNG locally with Docker:

```bash
docker run --name searxng -d -p 8888:8080 docker.io/searxng/searxng:latest
```

Then verify it's reachable: `curl http://localhost:8888`

Also make sure SearXNG has JSON format enabled in its `settings.yml` (the `formats` list must include `json`).

---

### TOML parse error on startup

```
Error: Invalid configuration file at /path/to/file.toml
```

One of your config files has a syntax error. The error message includes which file and the line number. Open it in a text editor, fix the syntax, and re-run.

---

## Research Mode

### "Zero local documents ingested"

asky couldn't find or read your files. Check:

1. The file path exists and is spelled correctly
2. The file type is supported: `.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`, `.pdf`, `.epub`
3. If using a relative path, it resolves under one of the roots configured in `research.local_document_roots` in `general.toml`

To use an absolute path directly:

```bash
asky -r /full/path/to/document.pdf "What does this say?"
```

Absolute paths are accepted when they fall inside a configured root.

---

### Research mode is slow on first run

On first use with a document, asky chunks and embeds the full content. This is a one-time cost per document. Subsequent queries against the same document reuse the cached index. Large files (EPUBs, long PDFs) can take 30-60 seconds to index.

---

### Research produces answers that ignore the document

Run a manual corpus query to verify your document was indexed and retrieval is working:

```bash
asky --query-corpus "phrase from your document"
```

If this returns nothing relevant, try rephrasing. Retrieval is semantic, not exact-match. If retrieval fails consistently, the embedding model may be misconfigured - check `research.toml`.

---

## Memory

### How do I check what asky has remembered?

```bash
asky memory list
```

This lists all saved memories with their IDs and scopes (global vs session).

---

### Memory from one session appears in unrelated queries

Global memories are injected into every conversation. If a memory is too broad, delete it:

```bash
asky memory list       # get the ID
asky --delete-memory 5  # delete by ID
```

Session-scoped memories only appear when that specific session is active. They don't leak into other sessions.

---

### Memory recall is not working

In verbose mode (`-v`), you can see whether memory was found and injected. If you see no `## User Memory` section in the verbose output, either:
- No memories have been saved yet
- Saved memories didn't pass the similarity threshold for your current query (threshold is 0.7 by default)

Try an explicit save first:

```bash
asky "remember globally: I prefer Python over JavaScript"
asky -v "which language should I use?"
```

The second command should show the memory being injected.

---

## XMPP Daemon

### "Error: asky menubar daemon is already running"

Another instance is already running. On macOS, look for the asky icon in the menu bar and use it to stop the daemon before starting a new one.

If the menu bar icon is missing but the process is running, find and kill it:

```bash
pgrep -fl "asky"
kill <pid>
```

Then run `asky --daemon` again.

---

### Messages to the bot get no response

Check in order:

1. **Allowed JIDs** - is your JID listed in `allowed_jids` in `~/.config/asky/xmpp.toml`? Unauthorized senders are silently ignored.
2. **JID format** - bare JID (`user@domain`) allows any resource; full JID (`user@domain/resource`) requires an exact match including the resource string from your client.
3. **Connection** - is the daemon actually connected? Check the XMPP log at `~/.config/asky/logs/xmpp.log`.
4. **Message type** - only direct `chat` messages are processed. Group chat (MUC) is not supported.

---

### Voice messages are not transcribed

- Voice transcription is macOS-only (mlx-whisper dependency).
- Check that `voice_enabled = true` in `xmpp.toml`.
- Check that `mlx-whisper` is installed: `uv pip install "asky-cli[mlx-whisper]"` or `"asky-cli[mac]"`.
- The audio must arrive as an OOB (out-of-band) file attachment in the XMPP message, not as inline text. Use an XMPP client that supports file attachments (XEP-0363).

---

### Daemon won't connect to XMPP

Check the XMPP log for connection errors:

```bash
tail -f ~/.config/asky/logs/xmpp.log
```

Common causes:
- Wrong `jid`, `password`, `host`, or `port` in `xmpp.toml`
- The XMPP server blocks connections on the default port (5222) - try port 443 or 5223
- The bot account doesn't exist on the server - register it first using an XMPP client

---

## General

### Where are logs?

- Main log: `~/.config/asky/logs/asky.log`
- XMPP log: `~/.config/asky/logs/xmpp.log`
- Daemon startup log (macOS): `~/.config/asky/logs/asky-menubar-bootstrap.log`

To get more detail, set `log_level = "DEBUG"` in `general.toml`.

---

### How do I reset to defaults?

Delete individual config files and asky will recreate them from bundled defaults on next run:

```bash
rm ~/.config/asky/general.toml    # resets general settings
rm ~/.config/asky/models.toml     # resets model definitions
rm ~/.config/asky/api.toml        # resets API key config
```

To reset everything including history and memory:

```bash
rm -rf ~/.config/asky/
```

This deletes all history, sessions, memories, and config. There is no undo.

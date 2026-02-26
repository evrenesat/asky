# Plan: XEP-0050 Ad-Hoc Commands

## Overview

Expose asky's full XMPP daemon command surface via the XEP-0050 Ad-Hoc Commands protocol.
This lets any standards-compliant XMPP client (Conversations, Gajim, Monal, etc.) discover and
execute asky commands through native GUI dialogs — without users needing to know command syntax.

Currently the entire command surface is text-based (free-form chat messages). After this work,
all major operations will also be available as discoverable, form-driven ad-hoc commands under
the `http://jabber.org/protocol/commands` service-discovery node.

**End state observable behavior:**
- An authorized XMPP client can do `Service Discovery → asky JID → Ad-Hoc Commands` and see a list of commands.
- Each command can be executed from the client's built-in ad-hoc command GUI.
- Simple commands (list sessions, list history) return plain text immediately.
- Form commands (run query, switch session) present a form, collect input, execute, and return results.
- Only JIDs authorized in the existing allowlist can execute commands.

---

## Existing Command Surface (for mapping to Ad-Hoc nodes)

All of the following exist in `command_executor.py` and `router.py`:

| Category       | Text commands                                                   |
|----------------|-----------------------------------------------------------------|
| Status         | (no equivalent; new)                                            |
| Sessions       | `/session`, `/session new`, `/session child`, `/session clear`, `/session <id>` |
| History        | `-H [N]`, `-pa ID`, `-ps SEL`, `-sh [N]`                       |
| Transcripts    | `transcript list`, `transcript show`, `transcript use`, `transcript clear` |
| Queries        | free-text, `-r`, `-m`, `-s`, `-L`, `-t`, `-sp`, `-off`, `--shortlist` |
| Corpus         | `--query-corpus`, `--summarize-section`                         |
| Memories       | `--list-memories`                                               |
| Tools          | `--list-tools`                                                  |
| Prompts        | `/`, `/prefix`                                                  |
| Presets        | `\presets`, `\name`                                             |

---

## Protocol Summary (XEP-0050)

- Each command is identified by a **node** string (e.g. `asky#status`).
- Commands are discovered via `disco#items` on node `http://jabber.org/protocol/commands`.
- Execution is a sequence of IQ `set` stanzas; each step may carry a `<x>` data form (XEP-0004).
- `status` attribute on `<command>`: `executing` (more steps) → `completed` or `canceled`.
- `<actions>` element advertises available actions: `execute`, `next`, `prev`, `complete`, `cancel`.
- Multi-step: server tracks a `sessionid`; client sends it back on every subsequent step.
- slixmpp exposes this via plugin `xep_0050`; handlers are async coroutines receiving `(iq, session)`.

---

## Phases

### Phase 1: Infrastructure

**Objective:** Register XEP-0050 + XEP-0004 with the XMPP client and create the handler class skeleton.

#### 1.1 Register slixmpp plugins

File: `src/asky/plugins/xmpp_daemon/xmpp_client.py`

Current state: only `xep_0045` (MUC) is registered.

After: also register `xep_0050` and `xep_0004` in `AskyXMPPClient.__init__`, right after the `xep_0045` block:

```python
for plugin_name in ("xep_0045", "xep_0050", "xep_0004"):
    try:
        register_plugin(plugin_name)
    except Exception:
        logger.debug("failed to register %s plugin", plugin_name, exc_info=True)
```

Constraint: keep the existing `try/except` isolation so a missing plugin doesn't crash startup.

#### 1.2 Expose plugin accessor

Add a method to `AskyXMPPClient`:

```python
def get_plugin(self, name: str):
    """Return a registered slixmpp plugin by name, or None."""
    plugins = getattr(self._client, "plugin", None)
    if plugins is None:
        return None
    try:
        return plugins[name]
    except (KeyError, TypeError):
        return None
```

Also expose the underlying asyncio loop:

```python
@property
def loop(self):
    return getattr(self._client, "loop", None)
```

#### 1.3 Create `adhoc_commands.py`

New file: `src/asky/plugins/xmpp_daemon/adhoc_commands.py`

Contains class `AdHocCommandHandler` with:
- Constructor: `(command_executor, router, loop)` where `loop` is the asyncio event loop.
- Method `register_all(xep_0050_plugin)` — registers all commands by calling `xep_0050_plugin.add_command(node, name, handler)` for each command.
- Private `_is_authorized(iq)` — extracts sender JID from IQ, delegates to `router.is_authorized()`.
- Private `_unauthorized_response(iq, session)` — sets error note and marks session done.
- Private `_run_blocking(fn, *args, **kwargs)` — uses `asyncio.run_coroutine_threadsafe` / `loop.run_in_executor` to run blocking functions from the coroutine context:

```python
async def _run_blocking(self, fn, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
```

#### 1.4 Wire up in `XMPPService`

File: `src/asky/plugins/xmpp_daemon/xmpp_service.py`

In `XMPPService.__init__`, after the client is created:

```python
from asky.plugins.xmpp_daemon.adhoc_commands import AdHocCommandHandler
self._adhoc_handler = AdHocCommandHandler(
    command_executor=self.command_executor,
    router=self.router,
)
```

In `_on_xmpp_session_start()`, after joining rooms, register all commands:

```python
xep_0050 = self._client.get_plugin("xep_0050")
if xep_0050 is not None:
    self._adhoc_handler.register_all(xep_0050)
```

**Expected outcome of Phase 1:** Client starts without errors. `disco#items` query on the asky JID returns an empty or partial command node list (no commands yet, but the registration infrastructure exists). No regressions in existing message-based routing.

---

### Phase 2: Status and Listing Commands

**Objective:** Implement all single-step informational commands that return plain text, no form input required.

Each handler follows this skeleton:
```python
async def _cmd_NAME(self, iq, session):
    if not self._is_authorized(iq):
        return self._unauthorized_response(iq, session)
    result = await self._run_blocking(self._executor_fn, jid=..., room_jid=None)
    session['payload'] = None
    session['notes'] = [('info', result)]
    session['has_next'] = False
    session['next'] = None
    return session
```

#### Commands to implement:

| Node                    | Name                   | Executor call                                  |
|-------------------------|------------------------|------------------------------------------------|
| `asky#status`           | Status                 | custom: session ID, JID, voice/image enabled    |
| `asky#list-sessions`    | List Sessions          | `execute_command_text("--session-history 20")` |
| `asky#list-history`     | List History           | `execute_command_text("--history 20")`          |
| `asky#list-transcripts` | List Transcripts       | `execute_command_text("transcript list")`       |
| `asky#list-tools`       | List Tools             | `execute_command_text("--list-tools")`          |
| `asky#list-memories`    | List Memories          | `execute_command_text("--list-memories")`       |
| `asky#list-prompts`     | List Prompts           | `execute_command_text("/")`                     |
| `asky#list-presets`     | List Presets           | `execute_command_text("\\presets")`             |

For `asky#status`, build the result string directly from:
- `self.command_executor.session_profile_manager.resolve_conversation_session_id(room_jid=None, jid=sender_jid)` for current session
- `XMPP_JID` config value for connected JID
- `self.command_executor.transcript_manager` for voice/image status (pass-through from router attributes)

The `execute_command_text` / `execute_query_text` calls use the authenticated sender JID extracted from the IQ stanza (`iq["from"].bare`).

**Constraint:** Every handler must check authorization first; unauthorized requests are silently dropped or return a permission-denied error note (XEP-0050 error condition `<forbidden/>`).

**Expected outcome of Phase 2:** An XMPP client sees 8 commands under the asky JID's ad-hoc command list. Each executes and returns text results in a single step with no form.

---

### Phase 3: Interactive Commands with Data Forms

**Objective:** Implement commands that require user input via XEP-0004 data forms.

#### 3.1 `asky#query` — Run a Query

Two-step flow:
1. Step 1: Return a form with fields:
   - `query` (text-single, required): Query text
   - `research` (boolean, default false): Enable research mode
   - `model` (list-single, optional): Model alias choices from config `MODELS` keys
   - `turns` (text-single, optional): Max turns (integer)
   - `lean` (boolean, default false): Lean mode (no shortlisting)
   - `system_prompt` (text-multi, optional): System prompt override
2. Step 2: Extract form values → build command tokens → call `execute_command_text` → return result as note.

Form construction uses `xep_0004_plugin.make_form(ftype='form', title='Run Query')`.

#### 3.2 `asky#new-session` — New Session

Single step with optional name form:
- Form field: `name` (text-single, optional): Session name
- On submit: call `command_executor.execute_session_command(command_text="/session new", ...)`
- Result: session ID returned as note.

#### 3.3 `asky#switch-session` — Switch Session

Two-step:
1. Step 1: Return form with one field:
   - `selector` (text-single, required): Session ID or name
2. Step 2: Call `execute_session_command(command_text=f"/session {selector}", ...)` → return result as note.

#### 3.4 `asky#clear-session` — Clear Session

Two-step with confirmation:
1. Step 1: Return form with one field:
   - `confirm` (boolean, required): "Clear all conversation messages?"
2. Step 2: If `confirm == True`, call `session_profile_manager.clear_conversation(session_id)` directly; return count. If false, cancel.

#### 3.5 `asky#use-transcript` — Use Transcript as Query

Two-step:
1. Step 1: Run `transcript list` to get available transcripts; build a `list-single` form field with each transcript as an option (label = preview, value = `#atN`). If no transcripts, return `notes=[('info', 'No transcripts available.')]` and set `has_next=False`.
2. Step 2: Selected transcript ID → call `execute_command_text(f"transcript use {selector}", ...)` → return result as note.

**Data form helper:** Add a private `_make_form(xep_0004, title, fields)` in `AdHocCommandHandler` to reduce boilerplate. `fields` is a list of dicts with keys `var`, `ftype`, `label`, `required`, `options`, `value`.

**Expected outcome of Phase 3:** All 5 interactive commands work end-to-end. An XMPP client can run a full asky query through a GUI dialog, switch sessions, and manage transcripts without typing any command syntax.

---

### Phase 4: Tests

**Objective:** Unit tests for the ad-hoc command handlers.

New file: `tests/test_xmpp_adhoc.py`

Test approach: mock slixmpp `iq` objects, mock `CommandExecutor`, mock asyncio loop. Use `asyncio.run()` to drive async handlers in tests.

Test cases per command:
- **Unauthorized JID**: handler returns permission-denied note.
- **Authorized JID**: command executes and returns expected notes/payload.
- For multi-step commands: test both step 1 (form returned) and step 2 (result returned).
- **Empty results**: e.g. no sessions, no transcripts — returns appropriate message.
- **Executor error**: executor raises exception — handler returns error note without crashing.

Test structure:
```python
class MockIQ:
    def __init__(self, from_jid: str):
        self._from = MockJID(from_jid)
    def __getitem__(self, key):
        if key == "from": return self._from
        ...

async def test_cmd_status_authorized():
    executor = Mock(...)
    router = Mock(is_authorized=Mock(return_value=True))
    handler = AdHocCommandHandler(executor, router)
    iq = MockIQ("user@domain")
    session = {}
    result = await handler._cmd_status(iq, session)
    assert result['has_next'] is False
    assert result['notes'][0][0] == 'info'
```

Target: all new tests pass in < 0.5s total (no network, no disk I/O; all executor calls mocked).

---

## File Manifest

| File                                                 | Action          |
|------------------------------------------------------|-----------------|
| `src/asky/plugins/xmpp_daemon/xmpp_client.py`        | Modify          |
| `src/asky/plugins/xmpp_daemon/adhoc_commands.py`     | Create (new)    |
| `src/asky/plugins/xmpp_daemon/xmpp_service.py`       | Modify          |
| `src/asky/daemon/AGENTS.md`                          | Update          |
| `tests/test_xmpp_adhoc.py`                           | Create (new)    |

No other files need changes. The existing `command_executor.py` and `router.py` are called as-is.

---

## Constraints

- No new packages: slixmpp's built-in `xep_0050` and `xep_0004` are used; no `pip install` needed.
- All blocking calls (`run_turn`, DB reads) go through `loop.run_in_executor(None, fn)` — never block the asyncio loop directly.
- Authorization check is always the first operation in every handler.
- Remote policy (REMOTE_BLOCKED_FLAGS) is enforced: ad-hoc commands that map to blocked flags must reject.
- No multi-session ad-hoc state leakage: each IQ handler resolves the session from the sender JID independently (same as text commands).
- `xep_0050` plugin absence (slixmpp version without it): gracefully log and skip registration; text command surface continues to work normally.
- Command node naming convention: all nodes are `asky#<kebab-name>`.

---

## Notes

- slixmpp's `xep_0050` plugin version may vary; the `add_command` API has been stable since 1.x. If the plugin uses a different method name, check at runtime via `getattr`.
- The `asky#query` command is the most complex. The model list should be built from `asky.config.MODELS.keys()` to stay in sync with configured models.
- For multi-step commands, slixmpp manages `sessionid` automatically; the handler just uses the `session` dict to pass state between steps via `session['next'] = next_handler_fn`.
- The `asky#status` command requires passing the voice/image enabled state. This can come from `xmpp_service.voice_transcriber.enabled` and `xmpp_service.image_transcriber.enabled`. Pass these as constructor args to `AdHocCommandHandler`.

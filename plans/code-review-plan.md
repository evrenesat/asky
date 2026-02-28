# asky Code Review Plan — Feature-by-Feature Audit

## Purpose

This plan defines a structured, multi-phase **business logic code review** for the asky codebase. Each phase focuses on one feature set. The review process per phase is:

1. **Analyze** — trace the feature from entry points through all code paths; compare what the code does with what docs/AGENTS.md/CLI claims it does.
2. **Report** — produce a findings list (gaps, inconsistencies, silent failures, undocumented behavior).
3. **Address** — fix or acknowledge findings before moving on.
4. **Proceed** — move to the next phase.

The goal is not a style review. It is a **feature completeness and correctness audit**: are we delivering what we advertise?

---

## How to Use This Plan

Each phase is self-contained. When starting a phase:

- Start from the advertised entry points (CLI flags, docs, AGENTS.md).
- Follow every code path to its terminus.
- Compare observed behavior against the documented contract.
- Produce a prioritized findings list.
- Address findings, then check off the phase.

---

## Phase Overview

| # | Feature Set | Primary Files | Advertised In |
|---|------------|---------------|---------------|
| 1 | Core Query Execution & Tool Loop | `cli/main.py`, `api/client.py`, `core/engine.py`, `core/registry.py` | `README`, `configuration.md`, ARCHITECTURE.md §Standard Query Flow |
| 2 | Research Mode (web + local RAG) | `research/`, `api/preload.py`, `cli/shortlist_flow.py`, `cli/local_ingestion_flow.py` | `research_mode.md`, ARCHITECTURE.md §Research Retrieval Flow |
| 3 | Sessions & Persistence | `storage/sqlite.py`, `api/session.py`, `cli/sessions.py`, `core/session_manager.py` | `configuration.md §Sessions`, ARCHITECTURE.md §Session Flow |
| 4 | User Memory & Elephant Mode | `memory/`, `cli/main.py --elephant-mode` | `elephant_mode.md`, ARCHITECTURE.md §User Memory Flow |
| 5 | XMPP Daemon & Routing | `plugins/xmpp_daemon/`, `daemon/service.py` | `xmpp_daemon.md`, ARCHITECTURE.md §XMPP Daemon Flow |
| 6 | Persona System | `plugins/manual_persona_creator/`, `plugins/persona_manager/` | `plugins.md §Personas`, AGENTS.md files |
| 7 | Plugin Runtime & Hook System | `plugins/runtime.py`, `plugins/manager.py`, `plugins/hooks.py`, `plugins/hook_types.py` | `plugins.md`, ARCHITECTURE.md §Plugin Runtime |
| 8 | GUI Server Plugin | `plugins/gui_server/` | `plugins.md §GUI Server`, `gui_server/AGENTS.md` |
| 9 | Playwright Browser Plugin | `plugins/playwright_browser/` | `playwright_browser.md`, ARCHITECTURE.md Decision 22 |
| 10 | CLI Surface & Command Routing | `cli/main.py` (full argparse surface), `cli/history.py`, `cli/sessions.py`, `cli/prompts.py` | `configuration.md §Grouped CLI surface` |
| 11 | Library API (AskyClient) | `api/client.py`, `api/types.py`, `api/context.py` | `library_usage.md` |
| 12 | macOS Menubar / Tray | `daemon/menubar.py`, `daemon/tray_macos.py`, `daemon/tray_controller.py` | ARCHITECTURE.md §macOS Menubar, `daemon/AGENTS.md` |
| 13 | Output Delivery (email, browser, push-data) | `email_sender.py`, `rendering.py`, `push_data.py`, `plugins/email_sender/`, `plugins/push_data/` | `configuration.md §Output actions` |
| 14 | Interface Planner (XMPP + pending unification) | `daemon/interface_planner.py`, `plugins/xmpp_daemon/interface_planner.py` (if still exists), `router.py` | `xmpp_daemon.md §Interface planner`, `plans/interface_model_upgrade_v1.md` |

---

## Phase 1 — Core Query Execution & Tool Loop

### What Is Claimed

- Multi-model support (configurable OpenAI-compatible APIs)
- Multi-turn tool-calling loop
- `PRE_LLM_CALL` / `POST_LLM_RESPONSE` hooks fire correctly around each LLM turn
- `PRE_TOOL_EXECUTE` / `POST_TOOL_EXECUTE` fire around each tool dispatch
- `TURN_COMPLETED` fires once per turn regardless of tool count
- `POST_TURN_RENDER` fires with `answer_title`, `cli_args`, `final_answer`
- `-L` / `--lean` disables tools, shortlist, memory; uses single-pass LLM call
- Max-turns respected; graceful exit (not crash) on limit
- `CONTEXT_OVERFLOW` raises `ContextOverflowError`, caller handles retry
- Token counting uses chars/4 approximation
- `-vv` prints full payload traces (request + response) in boxed console output
- Verbose tracing includes enabled-tool schemas in outbound request box
- Preload stage emits `Preloaded Context Sent To Main Model` panel before first model call
- Seed URL content preloaded from prompt URLs; direct-answer mode disables retrieval tools when seed is full+within budget

### Entry Points to Trace

1. `cli/main.py` → `chat.py` → `api/client.py.run_turn()` → `core/engine.py.run()`
2. `core/engine.py` → `core/registry.py.dispatch()` → `tools.py`
3. `--lean` flag path through `cli/main.py` and `api/client.py`
4. `POST_TURN_RENDER` hook: where is it fired? What args does it receive?
5. `ContextOverflowError`: where raised, where caught

### Key Questions

- Does `POST_TURN_RENDER` actually pass `answer_title`? (DEVLOG notes a recent fix for `filename_hint` crash in lean mode — verify this is fully closed)
- Does `--lean` truly bypass shortlist AND memory recall?
- Is `TURN_COMPLETED` fired exactly once per `run_turn()` call (not once per tool call)?
- Does max-turns produce a clear exit message rather than raising an exception to the user?
- Does `-vv` double-verbose mode actually suppress tool/summarization body payloads while showing main-model payloads?

---

## Phase 2 — Research Mode (Web + Local RAG)

### What Is Claimed

- `-r` without argument: web research mode
- `-r <path>` or `-r <corpus://...>`: local corpus mode
- `-r <path> -r <url>`: mixed mode (corpus + web)
- Session-owned research profile persists mode, source-mode, corpus paths
- Shortlist override (`--shortlist on/off/reset`) respected in research mode
- Local corpus uses configured `research.local_document_roots` as root guard
- Supported file types: PDF, EPUB, txt, html, md, json, csv (via PyMuPDF)
- Directory discovery yields local file links
- Fail-fast on missing local corpus (not silent fallback to web)
- Hybrid search: ChromaDB dense + SQLite BM25
- Query expansion: deterministic YAKE + optional LLM
- Evidence extraction: optional post-retrieval LLM (max 10 chunks)
- Source shortlisting: pre-LLM ranking, corpus-aware in local/mixed modes
- `corpus query` (no LLM): `cli/research_commands.py`
- `corpus summarize`: `cli/section_commands.py`
- `--section-*` flags expose canonical section references
- Research cache background summarization drains before banner teardown
- Acquisition tools excluded from registry when corpus is pre-built
- Local targets in prompt trigger path-redaction + KB hint in system prompt

### Entry Points to Trace

1. `cli/main.py` `-r` parsing → `api/preload.py`
2. `api/preload.py` → `cli/local_ingestion_flow.py` → `research/vector_store.py`
3. `api/preload.py` → `cli/shortlist_flow.py` → `research/source_shortlist.py`
4. `research/source_shortlist.py` → `shortlist_collect.py` → `shortlist_score.py`
5. `core/tool_registry_factory.py` — acquisition tool exclusion logic
6. `cli/research_commands.py` — `corpus query`
7. `cli/section_commands.py` — `corpus summarize` / `--summarize-section`

### Key Questions

- Does fail-fast work for missing local corpus, or does it silently degrade?
- Is the root guard enforced before or after the symlink is resolved?
- Does EPUB ingestion work? (PyMuPDF supports EPUB but it's worth verifying the code path)
- When corpus is pre-built, are acquisition tools truly excluded — or only when a specific flag is set?
- Does `corpus query` work without an active session? Without a model?
- Are `-r` corpus pointer changes on an existing research session properly overwriting (not appending) stored paths?

---

## Phase 3 — Sessions & Persistence

### What Is Claimed

- `session create <name>`, `session use`, `session end`, `session delete`
- `session from-message <id|last>` — creates session from history item
- `session clean-research` — removes findings + clears uploaded doc associations + corpus path pointers
- Shell-sticky sessions via `/tmp/asky_session_{PID}` lock files
- Session query defaults (model, tools, system prompt) persisted in `sessions.query_defaults` JSON
- Shortlist override first-class in `sessions.shortlist_override`
- Max-turns persisted per session; CLI `-t` overwrites
- Auto-naming from query keywords for defaults-only sessions (deferred rename)
- Compaction strategies: summary concat or LLM
- `-c <selector>` continues from history ID (context resolution)
- Session selectors accept partial name or ID

### Entry Points to Trace

1. `cli/sessions.py` → each subcommand → `storage/sqlite.py`
2. `api/session.py.resolve_session_for_turn()` — full decision tree
3. `core/session_manager.py.check_and_compact()` — compaction trigger and strategies
4. `cli/main.py` — shell-sticky session lock file creation/cleanup
5. `storage/sqlite.py` — `session_clean_research()` — does it clear all three things claimed?

### Key Questions

- Does `session from-message last` work when the last message has no partner (assistant message only)?
- Is the deferred auto-rename triggered reliably, or can it be lost on crash?
- Does `session clean-research` actually clear uploaded document associations and corpus paths, or only findings?
- Is there a test for the compaction LLM strategy path (not just the summary concat path)?
- Do session query defaults survive a session resume in a fresh process? (Persistence check)

---

## Phase 4 — User Memory & Elephant Mode

### What Is Claimed

- Per-turn recall: embed query → cosine search → inject `## User Memory` into system prompt (threshold 0.35)
- Short-circuits if no memories exist (`has_any_memories()`)
- `save_memory` LLM tool available in all registries
- Dedup via cosine threshold 0.90 (update existing if near-duplicate found)
- `memory list`, `memory delete <id>`, `memory clear`
- `--elephant-mode` requires active session; warns and ignores if no session
- Auto-extraction: background daemon thread, never blocks response
- Auto-extraction uses LLM to extract JSON facts from query+answer
- Chroma primary; SQLite BLOB fallback if Chroma unavailable
- Memory is always global (never session-scoped)
- Memory recall disabled in `--lean` mode

### Entry Points to Trace

1. `memory/recall.py.inject_memory_context()` — called from where in `api/client.py`?
2. `memory/tools.py.execute_save_memory()` — dedup path
3. `memory/auto_extract.py` — background thread trigger in `cli/chat.py`
4. `cli/main.py --elephant-mode` — session guard
5. `cli/main.py` `memory` subcommand group → `storage/sqlite.py`

### Key Questions

- Is `--lean` actually suppressing memory recall, or just tool registration?
- Is the fallback to SQLite BLOB on Chroma unavailability actually tested?
- Does the background auto-extraction thread have a timeout? What happens if LLM call hangs?
- Are there any edge cases where `save_memory` could fire during lean mode (bypassing the lean guard)?

---

## Phase 5 — XMPP Daemon & Routing

### What Is Claimed

- `asky --daemon` starts XMPP daemon (macOS: menubar app; otherwise: foreground service)
- `DaemonService` raises `DaemonUserError` if 0 or >1 transport registered
- Singleton lock prevents multiple instances
- Per-JID serialized queues (no parallel processing per sender)
- Sender allowlist: bare JID wildcard or exact full-JID
- Group chat: room must be pre-bound or trusted-invited
- Ad-hoc commands (XEP-0050): multi-step forms, auth by full JID then bare JID fallback
- Trusted room invite: auto-bind → persistent session → auto-join
- TOML config upload (OOB or inline fenced): `general.toml`, `user.toml` only; last write wins
- Document upload: HTTPS only, size/type limits, global content-hash dedup, links to active session
- `/session` commands: new/child/<id|name>
- Voice transcription: mlx-whisper, background worker
- Image description: image-capable model, background worker
- Transcript management: pending/completed/failed, confirmation workflows
- Response chunking + status message update (XEP-0308 correction, 2s throttle)
- XHTML-IM attachment for single-chunk outbound (with plain-body fallback)
- Room bindings + session override files persisted; auto-rejoined on restart
- Session media pointers: `#aN`/`#atN` audio, `#iN`/`#itN` image
- Command presets: `\\name`, `\\presets` — expanded at ingress before policy
- Remote policy gate: blocked flags cannot be bypassed via presets
- Slash-command expansion: same recursive path as CLI (`/alias`, `/cp`)
- Unresolved `/prefix` returns filtered prompt listing (not error)
- Interface planner: prefixed text → direct command; non-prefixed → planner → action

### Entry Points to Trace

1. `cli/main.py --daemon` → `daemon/menubar.py` or `daemon/service.py`
2. `plugins/xmpp_daemon/plugin.py.activate()` → `DAEMON_TRANSPORT_REGISTER`
3. `plugins/xmpp_daemon/xmpp_service.py` → per-JID queue → `router.py`
4. `router.py` — each routing branch (trusted invite, TOML upload, doc upload, `/session`, interface planner, direct command, query)
5. `command_executor.py` — remote policy gate; `AskyClient.run_turn()`
6. `voice_transcriber.py` + `image_transcriber.py` — background worker lifecycle
7. `transcript_manager.py` — pending/completed/failed state machine

### Key Questions

- Is the singleton lock cleaned up properly on unclean exit (SIGKILL)?
- Is the remote policy gate applied after preset expansion (not before)?
- Can a user bypass blocked flags by embedding them in a TOML upload?
- Does XEP-0308 correction fallback to append reliably when the client doesn't support it?
- Are background voice/image jobs cancelled on daemon shutdown?
- Is the TOML upload "last write wins" actually enforced, or does it merge?
- Does auto-rejoin on restart handle rooms that no longer exist gracefully?

---

## Phase 6 — Persona System

### What Is Claimed

- `persona create` — CLI-guided creation with behavior prompts + knowledge sources
- `persona load <alias>` — bind to current session
- `persona import <file.zip>` — import ZIP
- `persona export <alias>` — export ZIP
- `@mention` syntax for deterministic loading mid-conversation
- Knowledge injection via embeddings (session-scoped)
- System prompt extension via `SYSTEM_PROMPT_EXTEND` hook
- One persona per session (last binding wins?)
- `manual_persona_creator` plugin: creates persona data
- `persona_manager` plugin: import/bind/inject

### Entry Points to Trace

1. `cli/main.py` `persona` subcommand group
2. `plugins/manual_persona_creator/plugin.py.activate()` → what CLI commands does it register?
3. `plugins/persona_manager/plugin.py` → `SYSTEM_PROMPT_EXTEND` hook handler
4. `@mention` detection: where in the message pipeline?

### Key Questions

- Does `@mention` work inside XMPP daemon messages, or only in CLI mode?
- What happens when persona knowledge sources are URLs that become unavailable?
- Is there a test for persona ZIP round-trip (export → import → session bind)?
- Is the "one persona per session" invariant enforced or advisory?

---

## Phase 7 — Plugin Runtime & Hook System

### What Is Claimed

- `plugins.toml` roster loaded from `~/.config/asky/plugins.toml`
- Dependency ordering respected
- Per-plugin failure isolation: load/activation failures don't crash main execution
- Hook order deterministic: `(priority, plugin_name, registration_index)`
- `TRAY_MENU_REGISTER` gracefully handles empty subscriber list
- `enable_plugin()` TOML write is atomic (`os.replace()`)
- Interactive dependency prompt in CLI context; tray warning in daemon context
- `LaunchContext` gates interactive prompts correctly
- `CONFIG_LOADED`, `SESSION_END` explicitly deferred (v1 known gap — documented)

### Entry Points to Trace

1. `plugins/runtime.py.get_or_create_plugin_runtime()` — full initialization path
2. `plugins/manager.py._detect_early_dependency_issues()` → `_handle_dependency_issues()`
3. `plugins/hooks.py.invoke()` — ordering verification
4. `daemon/launch_context.py` — where is context set in each entry point?

### Key Questions

- Is `LaunchContext` set before plugin runtime init in all three contexts (CLI, daemon, app)?
- Does a plugin crash in `activate()` truly isolate — or can it corrupt shared state (e.g., partially registered hooks)?
- Are deferred hooks (`CONFIG_LOADED`, `SESSION_END`) documented as gaps in the user-facing docs, or only in ARCHITECTURE.md?
- Is `enable_plugin()` called with proper file locking if two processes run simultaneously?

---

## Phase 8 — GUI Server Plugin

### What Is Claimed

- NiceGUI sidecar on default `127.0.0.1:8766`
- Page extension registry (plugins can add pages)
- `DAEMON_SERVER_REGISTER` hook integration
- Start/Stop Web GUI tray entry
- Open Settings tray action
- Configurable host/port in `plugins/gui_server.toml`

### Entry Points to Trace

1. `plugins/gui_server/plugin.py.activate()` → sidecar server lifecycle
2. `DAEMON_SERVER_REGISTER` handler
3. `TRAY_MENU_REGISTER` handler in gui_server plugin
4. `plugins/gui_server/pages/` — what pages exist?

### Key Questions

- Does the GUI server actually start in CLI (non-daemon) mode, or only in daemon mode?
- What happens if NiceGUI is not installed — does the plugin fail gracefully or crash daemon startup?
- Are there any actual functional pages, or is it mostly a scaffold?
- Is the settings page functional or placeholder?

---

## Phase 9 — Playwright Browser Plugin

### What Is Claimed

- `asky --browser <url>` opens browser for login; saves session
- `FETCH_URL_OVERRIDE` hook intercepts `fetch_url_document` before requests/trafilatura pipeline
- Non-headless (`headless=False` always)
- Session state stored globally in `context.data_dir / "session.json"`
- Per-domain same-site delay: random 1.5s–4s
- CAPTCHA/challenge detection: known selectors + HTTP 403/429 + URL change
- On CAPTCHA: browser pops up (already visible), polls up to 5 minutes
- On Playwright failure: transparent fallback to requests/trafilatura
- Configurable intercept call-sites: `get_url_content`, `get_url_details`, `shortlist`, `research`
- Disabled by default; requires `uv pip install 'asky-cli[playwright]'` + `playwright install chromium`
- `trace_context` required on `research/tools.py._fetch_and_parse` for research interception to work

### Entry Points to Trace

1. `cli/main.py --browser` → `_run_playwright_login()`
2. `retrieval.py.fetch_url_document()` → `_try_fetch_url_plugin_override()`
3. `plugins/playwright_browser/plugin.py._on_fetch_url_override()`
4. `plugins/playwright_browser/browser.py.fetch_page()`
5. `research/tools.py._fetch_and_parse()` — does it pass `trace_context`?

### Key Questions

- The plan doc (Step 3) says add `trace_context={"tool_name": "research"}` to `_fetch_and_parse` — is this actually implemented in the current code?
- Is `--browser` documented as `--playwright-login` in the plan but `--browser` in the CLI? Reconcile.
- Does `_try_fetch_url_plugin_override` return `None` safely when plugin runtime is not initialized (critical for non-plugin test runs)?
- Is `session.json` save/load tested with a mock Playwright context?

---

## Phase 10 — CLI Surface & Command Routing

### What Is Claimed

Full CLI surface (from `configuration.md` and ARCHITECTURE.md):

```
asky history list/show/delete
asky session list/show/create/use/end/delete/clean-research/from-message
asky memory list/delete/clear
asky corpus query/summarize
asky prompts list
asky --config model add/edit
asky --config daemon edit
asky --tools [off|reset]
asky --shortlist [on|off|reset]
asky --completion-script bash|zsh
asky persona <subcommand>
```

Plus all query modifier flags (`-r`, `-s`, `-L`, `-m`, `-t`, `-sp`, `-tl`, `-v`, `-vv`, `-c`, `-ss`, `-rs`).

### Entry Points to Trace

1. `cli/main.py` — full argparse definition vs. what `--help` shows
2. Each grouped command handler — does it actually call the documented subcommands?
3. `--config model add/edit` — is this implemented or documented-only?
4. `--config daemon edit` — is this a real editor invocation or placeholder?
5. `--completion-script` — does it work with both bash and zsh?

### Key Questions

- Are there any flags documented in `configuration.md` that don't appear in `cli/main.py`?
- Are there any flags in `cli/main.py` that aren't documented anywhere?
- Does `session from-message` actually appear in the grouped `session` subcommands?
- Is `--browser` the correct flag name in the current code (vs `--playwright-login` in the plan)?
- Does `asky prompts list` show user-defined prompts from `user.toml` or only built-in ones?

---

## Phase 11 — Library API (AskyClient)

### What Is Claimed

From `library_usage.md`:

- `AskyClient(config: AskyConfig)` — full constructor
- `AskyClient.run_turn(request: AskyTurnRequest) -> AskyTurnResult`
- `AskyTurnResult.answer`, `.halt`, `.preload_meta`, `.session_id`
- `AskyConfig` field surface
- `AskyTurnRequest` field surface (all documented options)
- `on_tool_call`, `on_turn_start`, `on_stream_chunk` callbacks
- Shell session integration (lock file reuse)
- Error handling: `AskyError`, `AskyConfigError`, `AskyContextError`

### Entry Points to Trace

1. `api/types.py` — `AskyConfig`, `AskyTurnRequest`, `AskyTurnResult` fields vs. docs
2. `api/client.py.run_turn()` — does it honor all `AskyTurnRequest` options?
3. `api/exceptions.py` — are all documented exception types present?
4. Callbacks: where are `on_tool_call`, `on_turn_start`, `on_stream_chunk` invoked?

### Key Questions

- Does the documented callback surface match what's actually in `AskyTurnRequest`?
- Are all `AskyConfig` fields in the docs reflected in the actual dataclass?
- Is there a test that exercises the full `library_usage.md` quick-start example end-to-end?

---

## Phase 12 — macOS Menubar / Tray

### What Is Claimed

- Singleton lock prevents multiple instances
- Dynamic menu assembled from plugin `TRAY_MENU_REGISTER` contributions
- XMPP plugin contributes: XMPP status, JID, Voice status + Start/Stop XMPP + Voice toggle
- GUI plugin contributes: Start/Stop Web GUI + Open Settings
- Core fixed items: startup-at-login status/action + Quit
- Startup warnings displayed once on first menu refresh
- `--config daemon edit` is CLI-only (no menubar credential editor)
- `app_bundle_macos.py` creates `.app` bundle

### Entry Points to Trace

1. `cli/main.py --daemon` (macOS path) → `daemon/menubar.py` → `daemon/tray_macos.py`
2. `daemon/tray_controller.py` → `TRAY_MENU_REGISTER` fire
3. `plugins/xmpp_daemon/plugin.py` → `TRAY_MENU_REGISTER` handler
4. `plugins/gui_server/plugin.py` → `TRAY_MENU_REGISTER` handler
5. `daemon/tray_macos.py` — menu assembly from plugin entries

### Key Questions

- Is there a non-macOS tray fallback, or does `--daemon` fail on Linux/Windows?
- Does the singleton lock file get cleaned up on normal exit vs crash?
- Are startup warnings truly displayed only once, or on every menu open?

---

## Phase 13 — Output Delivery (Email, Browser, Push-Data)

### What Is Claimed

- `--open` / `-o`: renders answer to browser via `rendering.py`
- `--sendmail RECIPIENTS`: sends final answer via SMTP
- SMTP configuration in `general.toml` or `user.toml`
- `push_data_*` tools: configured HTTP endpoints in `user.toml`
- `POST_TURN_RENDER` hook receives `answer_title`, `cli_args`, `final_answer`
- Push-data plugin registers `push_data_*` tools via `TOOL_REGISTRY_BUILD`

### Entry Points to Trace

1. `cli/chat.py` → `-o` / `--open` → `rendering.py`
2. `plugins/email_sender/plugin.py` → `POST_TURN_RENDER` handler
3. `plugins/push_data/plugin.py` → `TOOL_REGISTRY_BUILD` handler
4. `push_data.py` — actual HTTP call

### Key Questions

- Is `POST_TURN_RENDER` documented as deferred (v1) in ARCHITECTURE.md but actually implemented? (Decision 19 says deferred; check actual code)
- Is `--sendmail` a CLI flag or is it provided only via plugin `POST_TURN_RENDER`?
- Does the browser rendering handle non-ASCII / CJK content correctly?

---

## Phase 14 — Interface Planner (Unification)

### What Is Claimed

From `plans/interface_model_upgrade_v1.md` (pending work):

- `src/asky/plugins/xmpp_daemon/interface_planner.py` is a fork of `daemon/interface_planner.py`
- Core planner does not support `chat` action type; plugin planner does
- Plan: unify to core planner, add `ACTION_CHAT`, delete plugin copy, update router + service imports

This is a known issue documented in `plans/` — the review should confirm current state and whether unification has been done.

### Entry Points to Trace

1. `daemon/interface_planner.py` — current `VALID_ACTIONS`, `ACTION_CHAT` presence
2. `plugins/xmpp_daemon/interface_planner.py` — does the file still exist?
3. `plugins/xmpp_daemon/router.py` — which planner does it import?
4. `plugins/xmpp_daemon/xmpp_service.py` — which planner does it import?
5. `tests/test_interface_planner.py` — is there a `test_planner_parses_chat_action` test?

### Key Questions

- Has the interface planner unification been done already, or is it still pending?
- If still pending: the plan is precise and ready — execute it.
- If done: verify there are no stale references to the old plugin planner.

---

## Cross-Phase Issues to Track

These are issues visible across multiple phases. Flag them during the phase review and address collectively if needed:

| Issue | Relevant Phases |
|-------|----------------|
| `POST_TURN_RENDER` is listed as "deferred" in Decision 19 but may be implemented in email/push plugins | 1, 7, 13 |
| `--browser` vs `--playwright-login` naming inconsistency | 9, 10 |
| `trace_context` in `research/tools.py._fetch_and_parse` — plan says to add it, check if done | 2, 9 |
| Interface planner fork may still exist | 5, 14 |
| `session clean-research` — plan claims 3 things are cleared; verify all 3 | 3, 5 |
| Lean mode guard — memory recall, shortlist, AND plugin hooks | 1, 4, 7 |

---

## Starting Point

**Start with Phase 1.**

For each phase, produce:
1. A **findings list** — numbered, prioritized (P1=correctness bug / P2=doc mismatch / P3=missing test / P4=minor inconsistency)
2. A **verdict per finding** — Fix Now / Document / Accept as-is
3. Changes made
4. Confirmation: full test suite passes after changes

Mark the phase complete and move to Phase 2.

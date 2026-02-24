# Plan: Asky Plugin System

## Overview

Introduce a plugin architecture that allows extending Asky's capabilities without enlarging the core. Plugins can register tools, add daemon servers, inject pipeline hooks, contribute configuration, and provide CLI commands. The system must:

- **Not break** any existing functionality — all current features continue working without plugins installed.
- **Be specific and deterministic** — small local models power the pipeline, so hooks must be precise, not open-ended.
- **Support the proposed plugins** — GUI Server, Puppeteer Browser, Manual Persona Creator, Persona Manager & Chat, and eventually Automatic Persona Creator.
- **Enable future extraction** — existing features (XMPP daemon, research tools, memory, email/push) can be gradually migrated to plugins.

Companion documents:
- [Plugin API Specification](plugin-system-api.md) — classes, protocols, lifecycle, configuration contract
- [Hook Points & Extraction Map](plugin-system-hooks.md) — every hook point, what it intercepts, and which existing features map to which hooks

---

## Phases

### Phase 1: Core Plugin Infrastructure

**Goal**: A working `PluginManager` that can discover, load, validate, and lifecycle-manage plugins. No hooks yet — just the skeleton.

**Files to create**:
- `src/asky/plugins/__init__.py` — public re-exports
- `src/asky/plugins/base.py` — `AskyPlugin` abstract base class (see [API spec](plugin-system-api.md#askyPlugin-base-class))
- `src/asky/plugins/manager.py` — `PluginManager` (discovery, loading, ordering, lifecycle)
- `src/asky/plugins/errors.py` — plugin-specific exceptions
- `src/asky/plugins/types.py` — shared type aliases and dataclasses for hook payloads

**Files to modify**:
- `src/asky/config/loader.py` — add `[plugins]` section loading from `plugins.toml`
- `src/asky/config/__init__.py` — export `PLUGINS_CONFIG`

**Tasks**:
1. Define `AskyPlugin` ABC with: `name`, `version`, `dependencies`, `activate(context)`, `deactivate()`.
2. Define `PluginContext` dataclass passed to `activate()` — gives plugins access to: config dict, logger, data directory path, hook registry reference.
3. Implement `PluginManager`:
   - Discovery: scan `plugins.toml` for `[plugin.<name>]` entries with `enabled = true` and `module = "dotted.path"`.
   - Loading: `importlib.import_module(module)` → find subclass of `AskyPlugin` → instantiate.
   - Dependency ordering: topological sort on `dependencies` list (plugin names).
   - Lifecycle: `activate_all()` called once at startup, `deactivate_all()` on shutdown (reverse order).
   - Error isolation: a failing plugin logs error and is skipped, never crashes the host.
4. Create `~/.config/asky/plugins.toml` default template (empty, commented examples).
5. Write unit tests:
   - Plugin discovery with valid/invalid modules.
   - Dependency ordering (diamond, cycle detection).
   - Activate/deactivate lifecycle.
   - Error isolation (bad plugin doesn't crash manager).

**Expected outcome**: `PluginManager` can load a no-op test plugin, activate it, and deactivate it. No integration with the rest of Asky yet.

**Verification**:
```bash
pytest tests/test_plugin_manager.py -v
```

---

### Phase 2: Hook Registry

**Goal**: A typed hook system that plugins use to attach to Asky's pipeline. Hooks are defined centrally; plugins subscribe during `activate()`.

**Files to create**:
- `src/asky/plugins/hooks.py` — `HookRegistry` class + hook point enum/constants

**Files to modify**:
- `src/asky/plugins/base.py` — `PluginContext` gains `.hooks: HookRegistry`
- `src/asky/plugins/manager.py` — `PluginManager` owns a `HookRegistry`, passes it via context

**Tasks**:
1. Define hook point constants (see [Hook Points doc](plugin-system-hooks.md) for the full list). Initial set:
   - `TOOL_REGISTRY_BUILD` — called after default tools are registered, before registry is finalized.
   - `SYSTEM_PROMPT_EXTEND` — called after system prompt is constructed, allows appending sections.
   - `PRE_LLM_CALL` — called before each LLM API call with messages payload (read-only inspection or mutation).
   - `POST_LLM_RESPONSE` — called after LLM response is received, before tool dispatch.
   - `PRE_TOOL_EXECUTE` — called before a tool executor runs, can modify args or short-circuit.
   - `POST_TOOL_EXECUTE` — called after a tool executor returns, can modify result.
   - `DAEMON_SERVER_REGISTER` — called during daemon startup to register additional server protocols.
   - `CONFIG_LOADED` — called after config is loaded, allows plugins to register their own config sections.
   - `SESSION_START` — called when a session begins or resumes.
   - `SESSION_END` — called when a session ends.
   - `PRE_PRELOAD` — called before the preload pipeline runs.
   - `POST_PRELOAD` — called after preload pipeline, before message assembly.
2. Implement `HookRegistry`:
   - `register(hook_point, callback, priority=100)` — subscribe.
   - `unregister(hook_point, callback)` — unsubscribe.
   - `invoke(hook_point, **payload)` — call all subscribers in priority order, passing payload as kwargs.
   - `invoke_chain(hook_point, data, **context)` — sequential pipeline where each callback receives the previous output (for mutation hooks like `SYSTEM_PROMPT_EXTEND`).
   - Priority: lower number = earlier execution. Default 100.
3. Type each hook point's payload signature in `types.py` (using `TypedDict` or `dataclass`).
4. Write unit tests:
   - Register/unregister/invoke basic flow.
   - Priority ordering.
   - Chain invocation (data flows through).
   - Error in one hook doesn't block others.

**Expected outcome**: `HookRegistry` is functional, documented with typed payloads, but not yet wired into Asky's pipeline.

**Verification**:
```bash
pytest tests/test_plugin_hooks.py -v
```

---

### Phase 3: Pipeline Integration

**Goal**: Wire hooks into the actual Asky pipeline so plugins can affect real behavior.

**Files to modify**:
- `src/asky/cli/main.py` — initialize `PluginManager` at startup, call `activate_all()`. Pass manager to `chat` and `daemon` flows.
- `src/asky/core/tool_registry_factory.py` — invoke `TOOL_REGISTRY_BUILD` hook after building default tools.
- `src/asky/api/client.py` — invoke `SYSTEM_PROMPT_EXTEND`, `PRE_PRELOAD`, `POST_PRELOAD` hooks.
- `src/asky/core/engine.py` — invoke `PRE_LLM_CALL`, `POST_LLM_RESPONSE`, `PRE_TOOL_EXECUTE`, `POST_TOOL_EXECUTE` hooks.
- `src/asky/daemon/service.py` — invoke `DAEMON_SERVER_REGISTER` during startup.
- `src/asky/config/loader.py` — invoke `CONFIG_LOADED` hook.

**Tasks**:
1. Add `plugin_manager: Optional[PluginManager]` parameter to `AskyClient.__init__()` (default `None` for backward compatibility).
2. In `create_tool_registry()` and `create_research_tool_registry()`, accept optional `hook_registry` parameter. After registering all built-in tools, call `hook_registry.invoke("TOOL_REGISTRY_BUILD", registry=registry)`.
3. In `AskyClient.build_messages()`, after constructing system prompt, call `hook_registry.invoke_chain("SYSTEM_PROMPT_EXTEND", data=system_prompt, config=self.config)`.
4. In `ConversationEngine.run()`, wrap the LLM call with `PRE_LLM_CALL` / `POST_LLM_RESPONSE` hooks.
5. In `ToolRegistry.dispatch()`, wrap executor calls with `PRE_TOOL_EXECUTE` / `POST_TOOL_EXECUTE` hooks.
6. In `XMPPDaemonService.__init__()`, store `plugin_manager` reference. In `run_foreground()`, invoke `DAEMON_SERVER_REGISTER` passing self (service context).
7. Ensure all hook invocations are guarded: if no `plugin_manager` or `hook_registry`, skip (zero overhead when no plugins).
8. Write integration tests:
   - A test plugin that registers a custom tool via `TOOL_REGISTRY_BUILD` → verify tool appears in registry.
   - A test plugin that extends system prompt via `SYSTEM_PROMPT_EXTEND` → verify prompt contains extension.
   - A test plugin that modifies tool args via `PRE_TOOL_EXECUTE` → verify modified args reach executor.

**Constraints**:
- Every hook call site must be wrapped in `if self._hook_registry:` guard — no perf overhead for non-plugin users.
- No existing test should break.
- No change to public CLI interface.

**Expected outcome**: A test plugin can register a tool and extend the system prompt in a real Asky turn.

**Verification**:
```bash
pytest tests/ -v  # full suite must pass
pytest tests/test_plugin_integration.py -v
```

---

### Phase 4: Plugin Configuration & Data Directories

**Goal**: Each plugin gets its own config section and data directory, managed by the plugin system.

**Files to modify**:
- `src/asky/plugins/manager.py` — create per-plugin data dirs, load per-plugin config
- `src/asky/config/loader.py` — support `plugins/<plugin_name>.toml` config files

**Tasks**:
1. Each plugin gets a data directory at `~/.config/asky/plugins/<plugin_name>/`.
2. Plugin config: `~/.config/asky/plugins/<plugin_name>.toml` merged into `PluginContext.config`.
3. `PluginContext` provides:
   - `.config: dict` — plugin-specific config section
   - `.data_dir: Path` — plugin-specific data directory
   - `.global_config: dict` — read-only access to global Asky config
4. `PluginManager` creates data dirs on first activation.
5. Write tests for config loading and data dir creation.

**Expected outcome**: Plugins have isolated config and storage.

**Verification**:
```bash
pytest tests/test_plugin_config.py -v
```

---

### Phase 5: First Plugin — Manual Persona Creator

**Goal**: Implement the Manual Persona Creator as the first real plugin, validating the plugin architecture.

**Files to create**:
- `src/asky/plugins/persona_creator/__init__.py`
- `src/asky/plugins/persona_creator/plugin.py` — `ManualPersonaCreatorPlugin(AskyPlugin)`
- `src/asky/plugins/persona_creator/ingestion.py` — file ingestion logic (reuse local loader patterns)
- `src/asky/plugins/persona_creator/persona_format.py` — persona ZIP format creation
- `src/asky/plugins/persona_creator/tools.py` — LLM tool definitions

**Plugin capabilities** (using hooks):
- `TOOL_REGISTRY_BUILD`: registers `create_persona`, `add_to_persona`, `list_personas`, `export_persona` tools.
- `CONFIG_LOADED`: registers `[persona_creator]` config section (supported file types, max corpus size, etc.).

**Tool definitions**:
- `create_persona(name, description, system_prompt?)` → creates a new persona skeleton
- `add_to_persona(persona_name, source)` → adds content from file/folder/URL to persona corpus. Uses existing local loader for txt/html/md/json/csv/pdf/epub. Chunks and embeds into persona-scoped vector collection.
- `list_personas()` → lists available personas with stats
- `export_persona(persona_name, output_path?)` → creates ZIP file (system_prompt.txt, user_prompts/, embeddings.json, metadata.json)

**Persona storage**:
- `~/.config/asky/plugins/persona_creator/personas/<name>/`
- Each persona dir contains: `metadata.json`, `system_prompt.txt`, raw source files, and a Chroma collection scoped to `persona_<name>`.

**Verification**:
```bash
pytest tests/test_persona_creator.py -v
# Manual: asky --persona-tools "create a persona named 'TestPerson'"
```

---

### Phase 6: Persona Manager & Chat Plugin

**Goal**: Load a persona into an Asky session so the model adopts that persona's voice and knowledge.

**Files to create**:
- `src/asky/plugins/persona_manager/__init__.py`
- `src/asky/plugins/persona_manager/plugin.py` — `PersonaManagerPlugin(AskyPlugin)`
- `src/asky/plugins/persona_manager/loader.py` — persona loading and session binding
- `src/asky/plugins/persona_manager/tools.py` — LLM tool definitions
- `src/asky/plugins/persona_manager/hub.py` — persona hub client (fetch persona index, download)

**Plugin capabilities** (using hooks):
- `TOOL_REGISTRY_BUILD`: registers `load_persona`, `unload_persona`, `query_persona_knowledge`, `import_persona` tools.
- `SYSTEM_PROMPT_EXTEND`: when a persona is loaded, prepends persona's system prompt.
- `SESSION_START`: checks if session has a bound persona, auto-loads it.
- `PRE_PRELOAD`: injects persona vector data into the preload pipeline.

**Tool definitions**:
- `load_persona(name_or_path)` → activates persona for current session (loads system prompt, user prompts, vector data)
- `unload_persona()` → deactivates current persona
- `query_persona_knowledge(query)` → searches persona's vector store, returns relevant chunks
- `import_persona(path_or_url)` → imports a persona ZIP into local storage
- `browse_persona_hub(hub_url?)` → lists personas available on a hub
- `install_from_hub(hub_url, persona_name)` → downloads and imports persona

**Persona Hub API contract** (simple JSON):
```
GET /personas → [{"name": "...", "description": "...", "version": "...", "download_url": "..."}]
GET /personas/<name>/download → ZIP file
```

**Dependencies**: Depends on `persona_creator` plugin (for format/storage conventions).

**Verification**:
```bash
pytest tests/test_persona_manager.py -v
```

---

### Phase 7: GUI Server Plugin (NiceGUI/Gradio)

**Goal**: A plugin that adds a web-based GUI server to the Asky daemon, providing basic configuration and data manipulation widgets.

**Files to create**:
- `src/asky/plugins/gui_server/__init__.py`
- `src/asky/plugins/gui_server/plugin.py` — `GUIServerPlugin(AskyPlugin)`
- `src/asky/plugins/gui_server/server.py` — web server (NiceGUI or Gradio)
- `src/asky/plugins/gui_server/pages/` — page modules (config editor, persona browser, session viewer)

**Plugin capabilities** (using hooks):
- `DAEMON_SERVER_REGISTER`: starts a web server alongside XMPP daemon.
- `CONFIG_LOADED`: registers `[gui_server]` config (port, host, auth).
- `TOOL_REGISTRY_BUILD`: optionally registers GUI-related tools.

**Library choice**: NiceGUI (mature, Pythonic, supports custom widgets, SSE for live updates).

**Building blocks provided**:
- Config editor page (read/write TOML sections)
- Session browser (list/switch/delete sessions)
- Persona browser (if persona plugins are active)
- Chat widget (simple text input → AskyClient → response display)
- Log viewer (tail asky.log)

**Verification**:
```bash
pytest tests/test_gui_server.py -v
# Manual: asky --xmpp-daemon → open browser at http://localhost:8765
```

---

### Phase 8: Puppeteer Browser Plugin

**Goal**: A plugin that provides real-browser web retrieval via Playwright (Python), replacing basic `requests` when enabled.

**Files to create**:
- `src/asky/plugins/puppeteer_browser/__init__.py`
- `src/asky/plugins/puppeteer_browser/plugin.py` — `PuppeteerBrowserPlugin(AskyPlugin)`
- `src/asky/plugins/puppeteer_browser/browser.py` — Playwright browser management
- `src/asky/plugins/puppeteer_browser/profiles.py` — site profile management (cookies, credentials)
- `src/asky/plugins/puppeteer_browser/tools.py` — LLM tool definitions

**Plugin capabilities** (using hooks):
- `TOOL_REGISTRY_BUILD`: registers `browser_fetch`, `browser_login`, `list_browser_profiles` tools.
- `PRE_TOOL_EXECUTE`: intercepts `get_url_content` calls and routes through Playwright when a matching profile exists or when the basic fetch fails with 403.
- `CONFIG_LOADED`: registers `[puppeteer_browser]` config (headless mode, profile storage path, timeout).

**Library**: `playwright` (Python bindings, mature, supports profiles/cookies/storage state).

**Tool definitions**:
- `browser_fetch(url, wait_for?, extract_selector?)` → fetch page content via real browser
- `browser_login(profile_name, url)` → opens browser for manual login, saves storage state
- `list_browser_profiles()` → lists saved browser profiles with sites

**Profile storage**: `~/.config/asky/plugins/puppeteer_browser/profiles/<name>.json` (Playwright storage state).

**Verification**:
```bash
pytest tests/test_puppeteer_browser.py -v
```

---

### Phase 9: Extract Existing Features (Optional, Incremental)

**Goal**: Gradually move existing features to plugins to validate the architecture and reduce core size. Each extraction is independent and optional.

See [Hook Points & Extraction Map](plugin-system-hooks.md#extraction-candidates) for the full mapping.

**Candidates** (in order of risk/effort):

1. **Push Data** → plugin using `TOOL_REGISTRY_BUILD` (lowest risk, already isolated in `push_data.py` + `push_data.toml`)
2. **Email Sender** → plugin using `TOOL_REGISTRY_BUILD` (already isolated in `email_sender.py`)
3. **Browser Rendering** → plugin using `POST_TOOL_EXECUTE` or new `RENDER_OUTPUT` hook (already in `rendering.py`)
4. **XMPP Daemon** → plugin using `DAEMON_SERVER_REGISTER` (high effort, but daemon is already modular)

**Constraints**:
- Each extraction must be behind a feature flag: if plugin is not installed, the built-in version is used.
- No extraction is required — the plugin system works alongside built-in features.

---

## Notes

- **No new dependencies in core**: Plugin infrastructure uses only stdlib (`importlib`, `inspect`, `pathlib`). Individual plugins declare their own deps.
- **Entry points alternative**: Phase 1 uses config-driven discovery (`plugins.toml`). A future enhancement could use `setuptools` entry points for third-party plugin distribution, but that's out of scope for now.
- **Thread safety**: Hook invocations must be thread-safe since the daemon uses per-JID worker threads. `HookRegistry` should use a lock for registration but not for invocation (registry is frozen after startup).
- **Performance**: All hook call sites are guarded by `if hook_registry:` checks. Zero overhead when no plugins are configured.
- **Testing strategy**: Each phase has its own test file. Integration tests use a minimal test plugin that exercises the hooks.

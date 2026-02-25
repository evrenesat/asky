# Plan: Asky Plugin System (Revised)

## Goal

Build a deterministic plugin architecture that lets Asky grow through optional extensions without bloating core modules. Plugins must be able to:

- register tools,
- extend prompt/preload/turn behavior through typed hooks,
- attach additional daemon servers,
- keep their own config + persistent data,
- fail safely without taking down the host.

This revision is aligned to the *current* code paths in:

- `src/asky/api/client.py`
- `src/asky/core/tool_registry_factory.py`
- `src/asky/core/registry.py`
- `src/asky/core/engine.py`
- `src/asky/daemon/service.py`
- `src/asky/daemon/command_executor.py`

Companion docs:

- [Plugin API Specification](plugin-system-api.md)
- [Hook Points & Extraction Map](plugin-system-hooks.md)

---

## Definition of Done

The plugin initiative is complete when all of the following are true:

1. Asky runs exactly as today when no plugins are configured.
2. Plugins can be discovered, dependency-sorted, activated, deactivated, and inspected.
3. Hook contracts are typed, deterministic, and tied to real call sites.
4. Plugin failures are isolated (load/activate/hook/deactivate).
5. Plugin config/data are isolated under `~/.config/asky/plugins/`.
6. At least one real plugin (Manual Persona Creator) ships on top of the system.
7. Full pytest suite passes after each phase gate.

---

## Current-State Constraints (From Codebase)

1. `asky.config` is imported early and exports module-level constants; plugin bootstrap must not depend on mutating config loader globals.
2. `AskyClient` is instantiated in both CLI and daemon (`command_executor.py`), so runtime injection must work for both.
3. Tool execution interception belongs in `ToolRegistry.dispatch()`, not in `ConversationEngine`.
4. Daemon runs per-conversation worker threads; hook invocation must be thread-safe for read paths.
5. Some proposed hooks in earlier drafts (for example global `CONFIG_LOADED` from `config/loader.py`) create bootstrap-order problems and are deferred.

---

## Open Questions (Need Decision Before Phase 3)

1. Trust model for third-party plugins:
   - Recommended: only local Python modules explicitly listed in `plugins.toml`, no remote auto-install.
2. Plugin class resolution:
   - Recommended: require explicit `class` in `plugins.toml` for deterministic loading.
3. Hook mutability policy:
   - Recommended: mutable context objects for pre/post hooks, chain-return only for text transforms (`SYSTEM_PROMPT_EXTEND`).
4. Plugin dependency packaging:
   - Recommended: plugin deps stay optional extras; no new hard dependency in core.
5. Persona artifact format scope:
   - Recommended: v1 persona export contains prompt + metadata + raw/source-derived chunks; not raw vector DB internals.
6. GUI framework choice:
   - Recommended: lock one (`NiceGUI` or `Gradio`) before implementation; do not support both in first pass.

---

## Suggested Improvements Over Prior Draft

1. Add a dedicated Phase 0 for decision lock + test harness scaffolding before runtime code.
2. Split daemon integration from turn-pipeline integration (separate risk profiles).
3. Remove bootstrap-cyclic config hook from initial milestone.
4. Define deterministic ordering explicitly: dependency order, then hook priority, then plugin name.
5. Add plugin state/health inspection surface for troubleshooting.
6. Gate all new plugin features behind optional runtime presence.

---

## Phase Plan

## Phase 0: Decision Lock + Scaffolding

**Objective**: finalize unresolved contracts so implementation cannot drift.

**Files to modify**:

- `plans/plugin-system.md`
- `plans/plugin-system-api.md`
- `plans/plugin-system-hooks.md`

**Steps**:

1. Lock hook list for v1 and defer unstable hooks.
2. Lock plugin manifest schema and deterministic class loading strategy.
3. Lock order/priority/error semantics.
4. Lock verification gates for each phase.

**Exit criteria**:

- Team can start coding without API ambiguity.

**Verification**:

```bash
uv run pytest
```

---

## Phase 1: Plugin Runtime Foundation

**Objective**: working plugin runtime without touching chat/daemon call paths yet.

**Files to create**:

- `src/asky/plugins/__init__.py`
- `src/asky/plugins/base.py`
- `src/asky/plugins/errors.py`
- `src/asky/plugins/manifest.py`
- `src/asky/plugins/manager.py`
- `src/asky/plugins/runtime.py`

**Files to modify**:

- `src/asky/config/loader.py` (only to ensure `plugins.toml` bootstrap copy behavior if adopted)

**Files to add**:

- `tests/test_plugin_manager.py`

**Before/After**:

- Before: no plugin package/runtime exists.
- After: runtime can read roster, import plugin classes, topologically order them, activate/deactivate safely.

**Steps**:

1. Define manifest dataclasses and roster parser (`plugins.toml`).
2. Define `AskyPlugin` base class + `PluginContext`.
3. Implement `PluginManager` with state tracking and dependency ordering.
4. Implement `PluginRuntime` container (`manager` + `hook_registry`).
5. Add default `plugins.toml` creation template (commented examples only).
6. Add unit tests for discovery, ordering, cycles, and failure isolation.

**Constraints**:

- No hook call-site integration yet.
- No core behavior change when runtime is absent.

**Verification**:

```bash
uv run pytest tests/test_plugin_manager.py -v
uv run pytest
```

---

## Phase 2: Typed Hook Kernel

**Objective**: implement deterministic hook registry and typed contexts.

**Files to create**:

- `src/asky/plugins/hooks.py`
- `src/asky/plugins/hook_types.py`

**Files to modify**:

- `src/asky/plugins/base.py`
- `src/asky/plugins/manager.py`
- `src/asky/plugins/runtime.py`

**Files to add**:

- `tests/test_plugin_hooks.py`

**Before/After**:

- Before: plugins can activate but cannot subscribe to lifecycle events.
- After: plugins can register/unregister/invoke/invoke_chain hooks with stable ordering.

**Steps**:

1. Add hook name constants (see `plugin-system-hooks.md`).
2. Implement registry with:
   - registration lock,
   - deterministic ordering: `(priority, plugin_name, registration_index)`,
   - exception isolation,
   - freeze-after-startup option.
3. Add typed context dataclasses for each hook payload.
4. Wire registry into `PluginContext`.
5. Add unit tests for ordering, chaining, freeze behavior, and callback failures.

**Constraints**:

- Hook registry exists, but core pipeline still not invoking hooks.

**Verification**:

```bash
uv run pytest tests/test_plugin_hooks.py -v
uv run pytest
```

---

## Phase 3: Turn Pipeline Integration (API + Core)

**Objective**: make plugins able to affect real turns.

**Files to modify**:

- `src/asky/api/client.py`
- `src/asky/api/types.py`
- `src/asky/core/tool_registry_factory.py`
- `src/asky/core/registry.py`
- `src/asky/core/engine.py`
- `src/asky/cli/chat.py`
- `src/asky/daemon/command_executor.py`

**Files to add**:

- `tests/test_plugin_integration.py`

**Before/After**:

- Before: hook system exists but not connected to turn execution.
- After: plugins can register tools, modify system prompt/preload context, intercept tool execution, and observe LLM I/O.

**Steps**:

1. Extend `AskyClient` constructor with optional `plugin_runtime` / `hook_registry`.
2. Pass optional hooks into registry factory functions.
3. Add `TOOL_REGISTRY_BUILD` invocation at end of both registry factory builders.
4. Add `SESSION_RESOLVED`, `PRE_PRELOAD`, `POST_PRELOAD`, `SYSTEM_PROMPT_EXTEND`, `TURN_COMPLETED` call sites in `AskyClient`.
5. Add `PRE_LLM_CALL` and `POST_LLM_RESPONSE` in `ConversationEngine.run()`.
6. Add `PRE_TOOL_EXECUTE` and `POST_TOOL_EXECUTE` inside `ToolRegistry.dispatch()`.
7. Thread runtime injection through CLI and daemon query execution (`chat.py`, `command_executor.py`).
8. Add integration tests with a minimal test plugin exercising all wired hooks.

**Constraints**:

- Guard every call site (`if hook_registry is not None`).
- No existing public CLI argument behavior changes.
- No performance regression when plugins are disabled.

**Verification**:

```bash
uv run pytest tests/test_plugin_integration.py -v
uv run pytest
```

---

## Phase 4: Daemon Server Integration

**Objective**: allow plugins to register extra long-running servers when daemon starts.

**Files to modify**:

- `src/asky/daemon/service.py`
- `src/asky/daemon/command_executor.py`
- `src/asky/cli/main.py`

**Files to add**:

- `tests/test_plugin_daemon_integration.py`

**Before/After**:

- Before: daemon always starts only XMPP pipeline.
- After: daemon can host additional plugin servers with start/stop lifecycle integration.

**Steps**:

1. Add optional plugin runtime to daemon service constructor.
2. Invoke `DAEMON_SERVER_REGISTER` during daemon startup.
3. Start registered servers before entering foreground loop.
4. Ensure stop/cleanup runs even on daemon errors.
5. Add tests for server registration and teardown ordering.

**Constraints**:

- Existing XMPP behavior unchanged when no plugins are active.
- Plugin server failures are logged and isolated.

**Verification**:

```bash
uv run pytest tests/test_plugin_daemon_integration.py -v
uv run pytest
```

---

## Phase 5: Plugin Config + Data Isolation + Diagnostics

**Objective**: per-plugin config/data directories and basic runtime introspection.

**Files to modify**:

- `src/asky/plugins/manager.py`
- `src/asky/plugins/base.py`
- `src/asky/cli/main.py` (optional diagnostics command)

**Files to add**:

- `tests/test_plugin_config.py`

**Before/After**:

- Before: plugin runtime exists but no clear per-plugin config/data ownership.
- After: each plugin gets isolated config (`plugins/<name>.toml`) and data dir (`plugins/<name>/`).

**Steps**:

1. Load plugin-local TOML into `PluginContext.plugin_config`.
2. Create `data_dir` on activation.
3. Make `global_config` read-only in context.
4. Add plugin status listing API (`active`, `failed`, `skipped`, reason).
5. Add tests for config merge and dir creation behavior.

**Constraints**:

- No mutation of module-level exported constants in `asky.config`.

**Verification**:

```bash
uv run pytest tests/test_plugin_config.py -v
uv run pytest
```

---

## Phase 6: First Real Plugin - Manual Persona Creator

**Objective**: validate architecture with a real, deterministic plugin.

**Files to create**:

- `src/asky/plugins/persona_creator/__init__.py`
- `src/asky/plugins/persona_creator/plugin.py`
- `src/asky/plugins/persona_creator/ingestion.py`
- `src/asky/plugins/persona_creator/storage.py`
- `src/asky/plugins/persona_creator/tools.py`

**Files to add**:

- `tests/test_persona_creator.py`

**Before/After**:

- Before: plugin system is infrastructure only.
- After: plugin adds persona creation/import/export tools and persistent persona assets.

**Steps**:

1. Implement persona schema + storage layout.
2. Reuse existing local ingestion pathways for content acquisition.
3. Register persona tools via `TOOL_REGISTRY_BUILD`.
4. Add tests covering creation, ingestion, export, and error paths.

**Verification**:

```bash
uv run pytest tests/test_persona_creator.py -v
uv run pytest
```

---

## Phase 7: Persona Manager & Chat Plugin

**Objective**: bind personas to sessions and apply persona behavior/context during turns.

**Files to create**:

- `src/asky/plugins/persona_manager/__init__.py`
- `src/asky/plugins/persona_manager/plugin.py`
- `src/asky/plugins/persona_manager/session_binding.py`
- `src/asky/plugins/persona_manager/tools.py`
- `src/asky/plugins/persona_manager/hub_client.py`

**Files to add**:

- `tests/test_persona_manager.py`

**Before/After**:

- Before: personas can exist but cannot be loaded into active conversation behavior.
- After: persona loading/unloading, prompt injection, and persona knowledge retrieval work per session.

**Steps**:

1. Add session-binding persistence for active persona id/name.
2. Add `SYSTEM_PROMPT_EXTEND` + preload hooks for persona context.
3. Add tools for load/unload/query/import.
4. Add minimal hub API client contract.

**Verification**:

```bash
uv run pytest tests/test_persona_manager.py -v
uv run pytest
```

---

## Phase 8: GUI Server + Browser Retrieval Plugins (Parallel Track)

**Objective**: deliver optional high-value plugins without expanding core dependency footprint.

**Subphase A - GUI Server**

- `src/asky/plugins/gui_server/*`
- uses `DAEMON_SERVER_REGISTER`
- dependency approval required before adding framework

**Subphase B - Browser Retrieval**

- `src/asky/plugins/puppeteer_browser/*` (Playwright-backed)
- uses `TOOL_REGISTRY_BUILD` and `PRE_TOOL_EXECUTE`
- dependency approval required before adding Playwright

**Verification**:

```bash
uv run pytest tests/test_gui_server.py -v
uv run pytest tests/test_puppeteer_browser.py -v
uv run pytest
```

---

## Phase 9: Optional Core Feature Extractions

**Objective**: progressively move suitable core features to plugins once plugin runtime is proven.

Candidate order:

1. Push Data
2. Email Sender
3. Rendering
4. Research tool registration split
5. XMPP daemon (long-term)

Each extraction must:

- preserve backward compatibility,
- keep a fallback path,
- ship with explicit migration notes.

---

## Global Constraints

1. No new mandatory dependency in core plugin runtime.
2. No behavior changes for users without plugin config.
3. No silent hook failures (must log with plugin + hook name).
4. Full suite must stay green at every phase boundary.
5. New dependencies require explicit user approval before implementation.

---

## Final Checklist (Per Implementation PR)

1. Full suite passes (`uv run pytest`).
2. New tests added for new behavior.
3. Plugin runtime disabled path validated.
4. No debug artifacts.
5. Docs updated (`ARCHITECTURE.md`, `DEVLOG.md`, relevant `AGENTS.md` files when code changes land).

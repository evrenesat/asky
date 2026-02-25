# Asky Plugin System: Implementation Blueprint (Decision-Complete)

## 1. Purpose

This document is the implementation handoff plan for Asky's plugin architecture.

It is intentionally strict and exhaustive so a smaller model or junior agent can execute it without making product or architectural decisions.

If this plan conflicts with older plugin plan docs, this file is authoritative for implementation.

---

## 2. Locked Product Decisions

These are finalized and must not be re-decided during implementation.

1. Plugin distribution model: local-only roster loaded from `~/.config/asky/plugins.toml`.
2. No remote plugin install/discovery flow in v1.
3. Plugin class resolution: `class` is required per plugin manifest entry.
4. Hook mutability model: mutable context objects for pre/post hooks; prompt hooks use chain-return.
5. `SESSION_END` is not part of v1.
6. `CONFIG_LOADED` and `POST_TURN_RENDER` are deferred from v1.
7. Milestone 1 feature scope: plugin runtime + Manual Persona Creator + Persona Manager.
8. GUI plugin is immediate next milestone after Milestone 1.
9. GUI framework: NiceGUI.
10. NiceGUI packaging policy: base dependency in main project install.
11. Plugin capability declarations are warn-only (do not block activation).
12. Persona package v1 export format: prompt files + metadata + normalized chunks; vectors/embeddings are rebuilt on import.

---

## 3. Definition Of Done

The full initiative is done when all of the following are true.

1. Asky behavior is unchanged when plugins are not configured.
2. Plugin runtime can discover, load, sort, activate, and deactivate plugins with deterministic behavior.
3. Hook call ordering and error isolation are deterministic and tested.
4. Plugin failures do not crash normal chat/daemon operations.
5. Milestone 1 plugins (persona creator + persona manager) are usable end-to-end.
6. GUI plugin starts alongside daemon and can edit at least `general.toml` settings.
7. Full test suite passes.
8. Architecture/devlog/docs are updated for all implemented runtime behavior changes.

---

## 4. Non-Goals (This Cycle)

1. Automatic Persona Creator crawler pipeline.
2. Puppeteer/Playwright browser plugin.
3. Plugin marketplace / remote update mechanism.
4. XMPP daemon extraction into a plugin.
5. Hot-reload plugins while process is running.

---

## 5. Global Constraints (Do Not Violate)

1. Do not mutate `asky.config` module-level exported constants at runtime.
2. Do not introduce global catch-all exception swallowing in runtime control flow.
3. Do not alter existing CLI flags/behavior unless explicitly listed in this plan.
4. Do not make plugin system mandatory for normal startup.
5. Do not add hidden side-effectful plugin auto-discovery outside `plugins.toml`.
6. Do not block startup because one plugin fails.
7. Do not create any temporary files outside `temp/`.
8. Use `uv` for all Python commands.
9. All new dependencies require explicit recording in docs and lockfile updates.
10. Avoid magic numbers in implementation; use named constants.

---

## 6. Implementation Order Summary

1. Phase 0: Pre-flight verification and decision lock in docs.
2. Phase 1: Plugin runtime foundation.
3. Phase 2: Hook kernel and core call-site integration.
4. Phase 3: Milestone 1 plugins (Manual Persona Creator + Persona Manager).
5. Phase 4: GUI server plugin.
6. Phase 5: Hardening, extraction-prep hooks, and documentation closure.

Phases are sequential; do not start a later phase before phase verification gates pass.

---

## 7. File Inventory (Planned)

## 7.1 Files To Create

1. `src/asky/plugins/__init__.py`
2. `src/asky/plugins/base.py`
3. `src/asky/plugins/errors.py`
4. `src/asky/plugins/manifest.py`
5. `src/asky/plugins/runtime.py`
6. `src/asky/plugins/manager.py`
7. `src/asky/plugins/hooks.py`
8. `src/asky/plugins/hook_types.py`
9. `src/asky/plugins/manual_persona_creator/__init__.py`
10. `src/asky/plugins/manual_persona_creator/plugin.py`
11. `src/asky/plugins/manual_persona_creator/storage.py`
12. `src/asky/plugins/manual_persona_creator/ingestion.py`
13. `src/asky/plugins/manual_persona_creator/exporter.py`
14. `src/asky/plugins/manual_persona_creator/tools.py`
15. `src/asky/plugins/persona_manager/__init__.py`
16. `src/asky/plugins/persona_manager/plugin.py`
17. `src/asky/plugins/persona_manager/session_binding.py`
18. `src/asky/plugins/persona_manager/importer.py`
19. `src/asky/plugins/persona_manager/tools.py`
20. `src/asky/plugins/persona_manager/knowledge.py`
21. `src/asky/plugins/gui_server/__init__.py`
22. `src/asky/plugins/gui_server/plugin.py`
23. `src/asky/plugins/gui_server/server.py`
24. `src/asky/plugins/gui_server/pages/general_settings.py`
25. `src/asky/plugins/gui_server/pages/plugin_registry.py`
26. `tests/test_plugin_manager.py`
27. `tests/test_plugin_hooks.py`
28. `tests/test_plugin_integration.py`
29. `tests/test_manual_persona_creator.py`
30. `tests/test_persona_manager.py`
31. `tests/test_gui_server_plugin.py`
32. `plans/plugin-system-implementation-detailed.md` (this file)

## 7.2 Files To Modify

1. `src/asky/api/client.py`
2. `src/asky/api/types.py`
3. `src/asky/core/tool_registry_factory.py`
4. `src/asky/core/registry.py`
5. `src/asky/core/engine.py`
6. `src/asky/cli/chat.py`
7. `src/asky/daemon/command_executor.py`
8. `src/asky/daemon/service.py`
9. `src/asky/cli/main.py`
10. `src/asky/config/loader.py`
11. `src/asky/config/__init__.py` (only if new constants are required for plugin path helpers)
12. `pyproject.toml` (NiceGUI base dependency)
13. `uv.lock`
14. `ARCHITECTURE.md`
15. `DEVLOG.md`
16. `README.md`
17. `docs/configuration.md`

## 7.3 Files To Avoid Modifying Unless Needed

1. Existing daemon routing behavior files unrelated to plugin runtime.
2. Existing research ranking logic.
3. Existing storage schema files, unless session persona binding cannot be implemented without persistence change.

If a schema change is needed for persona session binding, add a dedicated migration step and tests.

---

## 8. Public Interfaces To Add/Change

## 8.1 Plugin Manifest Schema

`~/.config/asky/plugins.toml`

```toml
[plugin.manual_persona_creator]
enabled = true
module = "asky.plugins.manual_persona_creator.plugin"
class = "ManualPersonaCreatorPlugin"
dependencies = []
capabilities = ["tool_registry", "preload", "prompt"]
config_file = "plugins/manual_persona_creator.toml"
```

Rules:

1. `enabled`, `module`, and `class` are required.
2. Unknown keys are ignored with warning.
3. `dependencies`, `capabilities`, `config_file` are optional.
4. Missing class or import failure marks plugin as failed, does not crash host.

## 8.2 Runtime APIs

1. `PluginManager.load_roster() -> list[PluginManifest]`
2. `PluginManager.discover_and_import() -> None`
3. `PluginManager.activate_all() -> None`
4. `PluginManager.deactivate_all() -> None`
5. `PluginManager.list_status() -> list[PluginStatus]`
6. `PluginManager.is_active(name: str) -> bool`
7. `PluginManager.get_plugin(name: str) -> AskyPlugin | None`

## 8.3 AskyClient Constructor Change

Add optional runtime parameter:

1. `AskyClient(..., plugin_runtime: PluginRuntime | None = None)`

Compatibility rule:

1. `plugin_runtime=None` must keep current behavior.

## 8.4 Factory and Engine Hook Plumbing

1. `create_tool_registry(..., hook_registry: HookRegistry | None = None)`
2. `create_research_tool_registry(..., hook_registry: HookRegistry | None = None)`
3. `ConversationEngine(..., hook_registry: HookRegistry | None = None)` only if needed for direct hook access; otherwise pass through existing container.

## 8.5 Hook Names (v1)

1. `TOOL_REGISTRY_BUILD`
2. `SESSION_RESOLVED`
3. `PRE_PRELOAD`
4. `POST_PRELOAD`
5. `SYSTEM_PROMPT_EXTEND` (chain)
6. `PRE_LLM_CALL`
7. `POST_LLM_RESPONSE`
8. `PRE_TOOL_EXECUTE`
9. `POST_TOOL_EXECUTE`
10. `TURN_COMPLETED`
11. `DAEMON_SERVER_REGISTER`

Deferred (not implement now):

1. `CONFIG_LOADED`
2. `POST_TURN_RENDER`
3. `SESSION_END`

---

## 9. Hook Contracts (Exact)

## 9.1 Ordering

Hook execution order is sorted by tuple:

1. `priority` ascending
2. `plugin_name` ascending
3. `registration_index` ascending

## 9.2 Error Handling

1. Hook callback exception must be logged with hook name + plugin name + callback qualname.
2. Continue to remaining callbacks.
3. Never bubble callback exceptions to user-facing chat response path.

## 9.3 Context Mutability

1. Pre/post hook dataclass payloads are mutable unless explicitly marked read-only.
2. `SYSTEM_PROMPT_EXTEND` uses chain-return style.

---

## 10. Step-By-Step Atomic Execution Plan

## Phase 0: Pre-flight and Baseline

### Step 0.1 - Baseline repository health

1. Run full tests.
2. Record baseline runtime and pass count.

Verification:

```bash
uv run pytest
```

Acceptance:

1. No new failures relative to baseline.

### Step 0.2 - Confirm current call sites

Run discovery commands and record locations in implementation notes.

```bash
rg -n "create_tool_registry|create_research_tool_registry|ToolRegistry.dispatch|ConversationEngine.run|run_turn\(|run_foreground|AskyClient\(" src/asky
```

Acceptance:

1. All planned call sites exist and are mapped.

---

## Phase 1: Plugin Runtime Foundation

### Step 1.1 - Add plugin package skeleton

Files:

1. `src/asky/plugins/__init__.py`
2. `src/asky/plugins/errors.py`

Before:

1. No plugin package exists.

After:

1. Package import works without side effects.
2. Error types exist for load/manifest/dependency failures.

Verification:

```bash
uv run python -c "import asky.plugins"
```

### Step 1.2 - Define core plugin dataclasses and base classes

Files:

1. `src/asky/plugins/base.py`
2. `src/asky/plugins/manifest.py`
3. `src/asky/plugins/runtime.py`

Requirements:

1. `PluginManifest` immutable dataclass.
2. `PluginContext` immutable container except mutable references it carries.
3. `AskyPlugin` abstract base class.
4. `PluginStatus` state dataclass.
5. `PluginRuntime` dataclass with manager + hooks.

Verification:

```bash
uv run python -c "from asky.plugins.base import AskyPlugin; from asky.plugins.manifest import PluginManifest"
```

### Step 1.3 - Implement roster parsing and validation

Files:

1. `src/asky/plugins/manager.py`
2. `src/asky/config/loader.py` (if needed for default file bootstrapping only)

Requirements:

1. Read `~/.config/asky/plugins.toml`.
2. Create default commented template when missing.
3. Validate required fields.
4. Missing required fields create failed status entries and warnings.
5. Do not crash startup.

Verification:

```bash
uv run pytest tests/test_plugin_manager.py -k roster -v
```

### Step 1.4 - Implement deterministic dependency ordering

Files:

1. `src/asky/plugins/manager.py`

Requirements:

1. Topological sort by declared dependencies.
2. Ties resolved by plugin name ascending.
3. Cycles produce failure status for involved plugins.
4. Dependents of failed plugins become `skipped_dependency`.

Verification:

```bash
uv run pytest tests/test_plugin_manager.py -k dependency -v
```

### Step 1.5 - Implement activation/deactivation lifecycle

Files:

1. `src/asky/plugins/manager.py`

Requirements:

1. `activate_all()` iterates in deterministic order.
2. Create per-plugin data directory before activation.
3. Load per-plugin config file into context.
4. `deactivate_all()` reverse activation order.
5. Deactivation errors logged, not fatal.

Verification:

```bash
uv run pytest tests/test_plugin_manager.py -k lifecycle -v
```

---

## Phase 2: Hook Kernel + Runtime Integration

### Step 2.1 - Implement hook registry

Files:

1. `src/asky/plugins/hooks.py`
2. `src/asky/plugins/hook_types.py`

Requirements:

1. Registration lock.
2. Ordered callback storage.
3. `invoke` and `invoke_chain` behavior.
4. Optional freeze mode after startup.
5. Deferred hooks are declared but marked unsupported or omitted from constants.

Verification:

```bash
uv run pytest tests/test_plugin_hooks.py -v
```

### Step 2.2 - Integrate hook registry with plugin manager

Files:

1. `src/asky/plugins/manager.py`
2. `src/asky/plugins/runtime.py`
3. `src/asky/plugins/base.py`

Requirements:

1. Manager owns single hook registry instance.
2. PluginContext exposes hook registry.
3. `plugin_name` is attached to every registration.
4. Capability mismatch logs warning only.

Verification:

```bash
uv run pytest tests/test_plugin_manager.py -k capability -v
```

### Step 2.3 - Wire tool registry build hook

Files:

1. `src/asky/core/tool_registry_factory.py`

Requirements:

1. Both standard and research factory functions accept optional hook registry.
2. Invoke `TOOL_REGISTRY_BUILD` after built-in/custom registration and before return.
3. Payload includes mode and disabled tools.

Verification:

```bash
uv run pytest tests/test_plugin_integration.py -k tool_registry_build -v
```

### Step 2.4 - Wire AskyClient turn lifecycle hooks

Files:

1. `src/asky/api/client.py`
2. `src/asky/api/types.py`

Requirements:

1. `AskyClient` accepts optional `plugin_runtime`.
2. Emit `SESSION_RESOLVED` after session resolution.
3. Emit `PRE_PRELOAD` before calling preload pipeline.
4. Emit `POST_PRELOAD` immediately after preload resolution.
5. Apply `SYSTEM_PROMPT_EXTEND` as chain on final system prompt text.
6. Emit `TURN_COMPLETED` at end with final result payload.

Verification:

```bash
uv run pytest tests/test_plugin_integration.py -k "session_resolved or preload or prompt_extend or turn_completed" -v
```

### Step 2.5 - Wire engine and dispatch hooks

Files:

1. `src/asky/core/engine.py`
2. `src/asky/core/registry.py`

Requirements:

1. `PRE_LLM_CALL` before each main-model call.
2. `POST_LLM_RESPONSE` after response parse and before tool dispatch.
3. `PRE_TOOL_EXECUTE` before executor call.
4. `POST_TOOL_EXECUTE` after executor returns with timing.

Verification:

```bash
uv run pytest tests/test_plugin_integration.py -k "llm or tool_execute" -v
```

### Step 2.6 - Thread runtime through CLI and daemon paths

Files:

1. `src/asky/cli/main.py`
2. `src/asky/cli/chat.py`
3. `src/asky/daemon/command_executor.py`
4. `src/asky/daemon/service.py`

Requirements:

1. Plugin runtime initialized once for interactive process.
2. Runtime injected into AskyClient instances used in CLI and daemon queries.
3. Daemon service supports `DAEMON_SERVER_REGISTER` hook path.
4. No runtime means exact existing behavior.

Verification:

```bash
uv run pytest tests/test_plugin_integration.py -k daemon -v
uv run pytest tests/test_xmpp_daemon.py -v
```

---

## Phase 3: Milestone 1 Plugins (Runtime + Persona Pair)

### Step 3.1 - Manual Persona Creator plugin scaffolding

Files:

1. `src/asky/plugins/manual_persona_creator/*`

Requirements:

1. Plugin class registers creator tools via `TOOL_REGISTRY_BUILD`.
2. Uses plugin data dir for storage.
3. Clean error responses for invalid persona names/sources.

Verification:

```bash
uv run pytest tests/test_manual_persona_creator.py -k register -v
```

### Step 3.2 - Persona storage and schema

Files:

1. `src/asky/plugins/manual_persona_creator/storage.py`

Requirements:

1. Canonical persona directory layout.
2. Metadata schema versioning field.
3. Atomic write for metadata updates.
4. Validation on read.

Verification:

```bash
uv run pytest tests/test_manual_persona_creator.py -k storage -v
```

### Step 3.3 - Content ingestion for persona corpus

Files:

1. `src/asky/plugins/manual_persona_creator/ingestion.py`

Requirements:

1. Reuse local ingestion patterns for supported file types.
2. Normalize into chunk/provenance format.
3. Respect configured limits.
4. Surface partial ingestion warnings.

Verification:

```bash
uv run pytest tests/test_manual_persona_creator.py -k ingestion -v
```

### Step 3.4 - Persona export format implementation

Files:

1. `src/asky/plugins/manual_persona_creator/exporter.py`

Requirements:

1. ZIP includes prompts, metadata, normalized chunks.
2. Exclude local absolute source paths from export payload unless explicitly intended.
3. Include schema version and checksums.

Verification:

```bash
uv run pytest tests/test_manual_persona_creator.py -k export -v
```

### Step 3.5 - Persona Manager plugin scaffolding

Files:

1. `src/asky/plugins/persona_manager/*`

Requirements:

1. Register manager tools via `TOOL_REGISTRY_BUILD`.
2. Bind persona to session context.
3. Load/unload behavior deterministic and idempotent.

Verification:

```bash
uv run pytest tests/test_persona_manager.py -k register -v
```

### Step 3.6 - Persona import and embedding rebuild

Files:

1. `src/asky/plugins/persona_manager/importer.py`
2. `src/asky/plugins/persona_manager/knowledge.py`

Requirements:

1. Import ZIP, validate schema.
2. Rebuild embeddings from normalized chunks.
3. Reject incompatible schema versions with clear error.

Verification:

```bash
uv run pytest tests/test_persona_manager.py -k import -v
```

### Step 3.7 - Prompt and preload integration for active persona

Files:

1. `src/asky/plugins/persona_manager/plugin.py`
2. hook handlers in same package

Requirements:

1. `SYSTEM_PROMPT_EXTEND` injects persona behavior prompt.
2. `PRE_PRELOAD` or `POST_PRELOAD` injects persona context blocks when helpful.
3. Injection should not break lean mode semantics unless explicitly designed.

Verification:

```bash
uv run pytest tests/test_persona_manager.py -k "prompt or preload" -v
```

### Step 3.8 - Session persona binding persistence

Files:

1. `src/asky/plugins/persona_manager/session_binding.py`
2. storage/repo files only if needed

Requirements:

1. Keep session-to-persona binding persistent.
2. Resume session restores loaded persona behavior.
3. Child-session behavior is explicitly defined and tested.

Verification:

```bash
uv run pytest tests/test_persona_manager.py -k session -v
```

---

## Phase 4: GUI Server Plugin (Immediate Next Milestone)

### Step 4.1 - Add NiceGUI dependency and lockfile

Files:

1. `pyproject.toml`
2. `uv.lock`

Requirements:

1. NiceGUI is base dependency.
2. Dependency resolution passes.

Verification:

```bash
uv run python -c "import nicegui"
```

### Step 4.2 - GUI server plugin runtime

Files:

1. `src/asky/plugins/gui_server/plugin.py`
2. `src/asky/plugins/gui_server/server.py`

Requirements:

1. Register daemon server via `DAEMON_SERVER_REGISTER`.
2. Non-blocking startup and clean stop.
3. Health check callable for daemon status integration.

Verification:

```bash
uv run pytest tests/test_gui_server_plugin.py -k lifecycle -v
```

### Step 4.3 - General settings panel (first required feature)

Files:

1. `src/asky/plugins/gui_server/pages/general_settings.py`

Requirements:

1. Read existing `general.toml`.
2. Validate edits and write safely.
3. Display friendly validation errors.
4. No destructive overwrite of unrelated keys/comments unless unavoidable by chosen writer.

Verification:

```bash
uv run pytest tests/test_gui_server_plugin.py -k general_settings -v
```

### Step 4.4 - Plugin UI extension contract

Files:

1. `src/asky/plugins/gui_server/pages/plugin_registry.py`
2. `src/asky/plugins/gui_server/plugin.py`

Requirements:

1. Other plugins can register GUI panels/routes.
2. Registration failure in one plugin does not break GUI server startup.

Verification:

```bash
uv run pytest tests/test_gui_server_plugin.py -k extension -v
```

---

## Phase 5: Hardening and Documentation Closure

### Step 5.1 - End-to-end regression and performance checks

Requirements:

1. Full suite green.
2. Startup and daemon tests unaffected.
3. No major runtime regression in plugin-disabled mode.

Verification:

```bash
uv run pytest
uv run pytest tests/test_startup_performance.py -v
```

### Step 5.2 - Documentation updates

Files:

1. `ARCHITECTURE.md`
2. `README.md`
3. `docs/configuration.md`
4. `DEVLOG.md`
5. `src/asky/core/AGENTS.md` if architecture notes require
6. `src/asky/api/AGENTS.md` if API contract changed
7. `src/asky/daemon/AGENTS.md` if daemon plugin integration changed
8. `tests/AGENTS.md` if test taxonomy changes

Requirements:

1. Document plugin runtime startup flow.
2. Document plugin manifest format.
3. Document hook list and v1 deferred hooks.
4. Document persona package format and import behavior.
5. Document GUI plugin setup and dependency expectations.

Verification:

```bash
rg -n "plugin|plugins.toml|hook|persona|NiceGUI" ARCHITECTURE.md README.md docs/configuration.md
```

---

## 11. Required Test Matrix

## 11.1 Plugin Runtime Tests

1. Missing manifest file creates template and yields no active plugins.
2. Invalid manifest entry is marked failed and logged.
3. Import failure in one plugin does not block others.
4. Dependency cycle detection marks affected plugins failed.
5. Activation order deterministic across runs.
6. Deactivation reverse order deterministic.

## 11.2 Hook Tests

1. Registration ordering with same priority and different plugin names.
2. `invoke_chain` transforms value in deterministic order.
3. Callback exception isolation.
4. Freeze behavior blocks new registrations when expected.

## 11.3 Integration Tests

1. Test plugin registers tool into standard registry.
2. Test plugin registers tool into research registry.
3. Prompt extension appears in actual model message payload path.
4. Preload hooks mutate/append context as expected.
5. Tool pre-hook can mutate args and short-circuit.
6. Tool post-hook can mutate result.
7. Daemon server register path accepts plugin server spec.

## 11.4 Persona Plugin Tests

1. Create persona with valid/invalid names.
2. Ingest folder with mixed file types and partial failures.
3. Export and re-import roundtrip preserving metadata and chunks.
4. Rebuild embeddings on import.
5. Load persona into active session and verify prompt injection.
6. Resume session restores persona binding.

## 11.5 GUI Plugin Tests

1. GUI plugin register/start/stop lifecycle.
2. General settings form read/write validation.
3. Extension registry can mount additional plugin panels.
4. Failure in one panel registration does not crash server.

---

## 12. Edge Cases (Must Be Implemented, Not Deferred)

1. Plugin name collision across roster entries.
2. Dependency references unknown plugin.
3. Plugin declares dependency on disabled plugin.
4. Callback mutates payload to invalid type.
5. Persona import path traversal attempt inside ZIP.
6. Persona package with unsupported schema version.
7. Large persona import memory pressure mitigation.
8. GUI server port conflict behavior.
9. Daemon shutdown while GUI server start is in progress.
10. Plugin config TOML decode error handling.

---

## 13. Rollout Strategy

1. Land runtime foundation + hooks behind optional runtime injection.
2. Land persona plugins and validate milestone acceptance.
3. Land GUI plugin and daemon integration.
4. Keep extractions (push/email/render/etc.) as follow-up tasks after hardening.

No user-facing breaking change should occur before phase completion.

---

## 14. Per-Phase Acceptance Gates

## Gate A (after Phase 1)

1. `tests/test_plugin_manager.py` green.
2. Full suite green.

## Gate B (after Phase 2)

1. `tests/test_plugin_hooks.py` and `tests/test_plugin_integration.py` green.
2. Full suite green.

## Gate C (after Phase 3)

1. Persona plugin tests green.
2. End-to-end persona load/use flow verified.
3. Full suite green.

## Gate D (after Phase 4)

1. GUI plugin tests green.
2. Daemon integration tests green.
3. Full suite green.

## Gate E (after Phase 5)

1. Docs updated and grep-verified.
2. Full suite green.
3. No open P0/P1 known issues.

---

## 15. Final Binary Checklist (Must All Be True)

1. [ ] No plugin configured -> behavior identical to current baseline.
2. [ ] Plugin manifest errors are isolated and visible in logs.
3. [ ] Activation/deactivation and hook execution are deterministic.
4. [ ] Milestone 1 persona pair works end-to-end.
5. [ ] GUI plugin runs with NiceGUI and edits general settings.
6. [ ] Deferred hooks remain deferred (`CONFIG_LOADED`, `POST_TURN_RENDER`, `SESSION_END`).
7. [ ] Full test suite passes.
8. [ ] Architecture/docs/devlog updated.
9. [ ] No temporary/debug artifacts committed.
10. [ ] No unapproved dependency additions besides locked NiceGUI base dependency.

---

## 16. Command Bundle For Handoff Agent

Run these in order after each phase:

```bash
# phase-specific
uv run pytest tests/test_plugin_manager.py -v
uv run pytest tests/test_plugin_hooks.py -v
uv run pytest tests/test_plugin_integration.py -v
uv run pytest tests/test_manual_persona_creator.py -v
uv run pytest tests/test_persona_manager.py -v
uv run pytest tests/test_gui_server_plugin.py -v

# full regression
uv run pytest
```

If any phase command fails, stop and fix within same phase before proceeding.

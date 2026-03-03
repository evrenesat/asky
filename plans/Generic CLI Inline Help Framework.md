## Generic CLI Inline Help Framework (Extensible, Plugin-Aware)

### Summary
Build a **CLI-wide inline help framework** (not research-specific) that can print concise one-line guidance after parsing and before dispatch.  
Use research-mode guidance as the first built-in provider, but architect this as a reusable engine for any flag/command combinations.  
Support plugin-driven hints via:
1. **Static class-level contributions** (works for all parsed commands, no activation required), and  
2. **Runtime hook contributions** (for rich post-turn context in chat flows).

This gives immediate value for your local-corpus reminder while creating a durable expansion path for future built-in and plugin hints.

---

## Done State (Acceptance Criteria)

1. A generic inline-help engine exists in CLI and is not hardcoded to research mode.
2. Hints are emitted for **all parsed command flows** (including non-chat command paths), after parse and before dispatch.
3. Built-in first provider covers research source-mode reminder (`local_only` / `mixed` / `web_only`) with actionable next-step one-liners.
4. Plugins can add hint logic via:
   - static classmethod contributions (pre-dispatch),
   - runtime hook (post-turn, chat-specific contextual hints).
5. Chat path can emit richer runtime hints using resolved effective state (session/profile/preload).
6. XMPP behavior is not regressed (no unintended extra user-visible output in normal command executor responses).
7. Full test suite remains green.

---

## Public Interfaces / Type Changes

### 1) Plugin base API extensions
File: `src/asky/plugins/base.py`

Add new plugin-level static hint contract:

- `CLIHintContext` dataclass (parsed args + token/command metadata, phase).
- `CLIHint` dataclass (id, message, priority, frequency, channel).
- `AskyPlugin.get_cli_hint_contributions(context: CLIHintContext) -> list[CLIHint]` (classmethod, default empty).

This is lightweight and works before plugin activation.

### 2) Plugin manager extension
File: `src/asky/plugins/manager.py`

Add collector method:

- `collect_cli_hint_contributions(context: CLIHintContext) -> list[tuple[str, CLIHint]]`

Mirrors existing lightweight CLI contribution import behavior (import failures are logged/skipped, never block CLI).

### 3) Runtime hook extension for rich post-turn hints
Files:
- `src/asky/plugins/hook_types.py`
- `src/asky/plugins/hooks.py` (supported hook name list)

Add hook:
- `CLI_INLINE_HINTS_BUILD`

Add context:
- `CLIInlineHintsContext` with `request`, `result`, `cli_args`, and mutable `hints`.

This enables runtime-aware plugin hints for chat turns.

---

## Implementation Plan (Sequential, Atomic)

### Step 1 — Add core inline-help engine module
Files:
- `src/asky/cli/inline_help.py` (new)

Before:
- No centralized hint system; messaging is ad-hoc notices/warnings.

After:
- Central engine with:
  - `collect_pre_dispatch_hints(...)`
  - `collect_post_turn_hints(...)`
  - `dedupe/sort/cap` logic
  - `render_inline_hints(console, hints)` one-liner renderer
- Constants for defaults:
  - max hints per emission (small cap),
  - internal session key for seen hints.

### Step 2 — Implement built-in providers (first: research source-mode)
Files:
- `src/asky/cli/inline_help.py` (or `src/asky/cli/inline_help_providers.py` if split)

Built-in provider behavior:
- If effective/parsed context indicates research:
  - `local_only`: one-liner with current mode + how to enrich (`-r "...,web"`).
  - `mixed`: one-liner with mode + suggestion for stronger web expansion.
  - `web_only`: one-liner with mode + how to add local corpus.
- Operational tone, single line, action-oriented.

### Step 3 — Wire pre-dispatch hints into main CLI flow (all parsed command paths)
Files:
- `src/asky/cli/main.py`

Before:
- No generic hint emission point.

After:
- Emit pre-dispatch hints after parse + normalization (including research pointer resolution), before command routing.
- Ensure this runs in:
  - normal parser path,
  - persona subcommand parser path.
- Skip internal process-spawn paths where output noise is harmful (`--xmpp-daemon`, `--xmpp-menubar-child`, etc.).

### Step 4 — Add plugin static hint contribution pipeline
Files:
- `src/asky/plugins/base.py`
- `src/asky/plugins/manager.py`
- `src/asky/cli/main.py` (integration call)

Before:
- Plugins can contribute argparse flags, but not inline guidance rules.

After:
- Plugin classmethod hints are collected with parsed context and merged with built-ins.
- Fail-open behavior: plugin hint errors do not block CLI.

### Step 5 — Add runtime post-turn hint pipeline for chat
Files:
- `src/asky/cli/chat.py`
- `src/asky/plugins/hook_types.py`
- `src/asky/plugins/hooks.py`

Before:
- Chat prints notices only; no structured post-turn hint extension slot.

After:
- After `run_turn`, build post-turn hint context using actual resolved result (`turn_result.session`, preload outcome).
- Invoke runtime hook `CLI_INLINE_HINTS_BUILD` to let activated plugins add contextual hints.
- Render deduped hints in CLI output stream.

### Step 6 — Frequency controls (minimal, no user config)
Files:
- `src/asky/cli/inline_help.py`
- `src/asky/cli/chat.py` (session persistence helper usage)

Behavior:
- `per_invocation` (default): dedupe only within current emission.
- `per_session`: for chat turns with session id, persist seen hint IDs in session `query_defaults` internal key (e.g. `__inline_help_seen`) and suppress repeats.
- No new config flags in v1 (per your preference).

### Step 7 — XMPP compatibility guard
Files:
- `src/asky/plugins/xmpp_daemon/command_executor.py` (verify/no-op change only if needed)

Policy:
- Do not inject CLI inline hints into XMPP final answer formatting in v1.
- Ensure new hook/type additions are additive and do not alter existing result handling.

### Step 8 — Documentation updates
Files:
- `ARCHITECTURE.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/plugins/AGENTS.md`
- `src/asky/api/AGENTS.md` (if runtime hook mention needed)
- `docs/research_mode.md` (briefly reference this as first provider)
- `DEVLOG.md`

Document:
- Framework purpose/scope.
- Pre-dispatch and post-turn phases.
- Plugin static + runtime extension model.
- Frequency semantics.

---

## Exact Behavior Defaults (Locked)

1. Emission timing:
- **After successful parse/normalization, before dispatch** (CLI-wide pre-dispatch phase).

2. Plugin model:
- **Hybrid static + runtime**:
  - static classmethod for all parsed commands,
  - runtime hook for chat contextual hints.

3. Controls:
- Minimal controls only (code defaults, no user-facing toggle in v1).

4. Tone:
- Operational one-liners.

5. Research reminder cadence:
- Use `per_session` frequency where session exists; otherwise `per_invocation`.

---

## Test Plan

### Unit tests
1. `tests/test_inline_help.py` (new):
- Built-in provider outputs correct one-liners for `local_only`, `mixed`, `web_only`.
- Deduplication/priority/cap behavior.
- Frequency handling (`per_invocation` and `per_session` with seen set logic).

2. `tests/test_plugin_manager.py` (or plugin-specific tests):
- `collect_cli_hint_contributions` imports enabled plugins and collects hints.
- Plugin import failure in hint collection does not crash CLI.

3. `tests/test_plugin_hooks.py`:
- `CLI_INLINE_HINTS_BUILD` is recognized and invoked safely.

### CLI integration tests
4. `tests/test_cli.py`:
- Pre-dispatch hint prints for parsed research-local pointer invocation.
- Hints print on non-chat command paths (at least one representative command).
- Internal daemon/spawn paths suppress hint output.
- Persona command parsing path can emit hints (or explicitly tested if suppressed by policy).

5. `tests/test_chat.py` or existing chat tests:
- Post-turn runtime hints are rendered.
- Per-session hint suppression works across two turns in same session.

### Compatibility tests
6. XMPP tests:
- Existing command-executor output behavior unchanged (no unexpected hint text in final answer body).

### Final verification
- `uv run pytest`

---

## Explicit Assumptions

1. “All parsed commands” includes normal parser path and persona parser path.
2. CLI inline hints are a user-facing UX layer; API `notices` remain unchanged.
3. Session persistence for seen hints is acceptable via internal `query_defaults` key.
4. No new TOML/config switches are added in v1.
5. Plugins may provide both static and runtime hints; static path is the baseline compatibility path.


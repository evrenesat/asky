## Plan V2: Shared Adaptive Interface Policy + Full XMPP Module Canonicalization

### Brief Summary
Implement a shared, deterministic-first pre-handover policy layer in the API preload path so CLI and XMPP query execution get the same shortlist behavior for local-corpus turns, with interface-model fallback only for ambiguous cases. In the same implementation, remove legacy `asky.daemon` XMPP modules entirely and migrate all imports/tests/docs to `asky.plugins.xmpp_daemon.*`.

## 1) Define Done (Observable End State)
1. Local-corpus turns in both CLI and XMPP query paths follow one shared shortlist policy:
   - explicit web intent => shortlist runs,
   - explicit local-only intent => shortlist skipped,
   - ambiguous => interface model fallback decides,
   - `research_source_mode=local_only` => shortlist always skipped.
2. CLI/XMPP behavior parity is visible through shared preload metadata:
   - `PreloadResolution.shortlist_enabled` and `shortlist_reason` reflect adaptive decisions,
   - verbose preload provenance includes policy source and diagnostics.
3. Existing precedence still holds:
   - `lean` disables shortlist,
   - request/session overrides (`on/off/reset`) continue to work,
   - non-local-corpus turns keep existing shortlist logic.
4. Legacy daemon XMPP module paths no longer exist:
   - importing `asky.daemon.router`, `asky.daemon.command_executor`, `asky.daemon.xmpp_client`, `asky.daemon.voice_transcriber`, `asky.daemon.image_transcriber`, `asky.daemon.transcript_manager`, `asky.daemon.session_profile_manager`, `asky.daemon.chunking` fails (files removed),
   - all runtime/tests/docs reference plugin module paths only.
5. Full suite passes with updated tests.

## 2) Pin Assumptions
1. Python version: 3.13.x (current run showed 3.13.5).
2. Test runner: `uv run pytest` with xdist available.
3. Existing config shape remains TOML via `asky.config`.
4. Interface-model alias source remains `general.interface_model` (reuse, no new model alias key).
5. No backward-compat requirement for deleted legacy daemon XMPP paths (alpha project, breaking changes allowed).
6. Deterministic policy constants are defined as named constants (no magic numbers in function bodies).

## 3) Explicit Constraints (What NOT To Do)
1. Do not add new third-party dependencies.
2. Do not add compatibility wrappers/re-export shims for deleted daemon XMPP modules.
3. Do not change CLI command parsing semantics or grouped-command routing behavior.
4. Do not weaken existing override precedence (`lean`, request/session shortlist override).
5. Do not add broad `except Exception` in policy logic; catch parse/validation errors narrowly and fail safe.
6. Do not move shortlist orchestration out of API preload; parity must come from shared API path, not transport-specific forks.
7. Do not leave stale docs/tests importing deleted daemon XMPP modules.
8. Do not change unrelated behavior (voice/image processing semantics, remote policy gate semantics, session lifecycle semantics).

## 4) Full File Inventory (Before/After)

| File | Action | Before | After |
|---|---|---|---|
| `src/asky/api/preload_policy.py` | Create | No shared adaptive policy module exists | New deterministic-first policy module with fallback contract and diagnostics |
| `tests/test_preload_policy.py` | Create | No focused unit tests for new policy engine | Dedicated policy tests for web/local/ambiguous/fallback decisions |
| `src/asky/api/preload.py` | Modify | Shortlist enablement is config/override-driven, not query-intent-adaptive for local corpus | Calls policy engine when local corpus exists, sets decision metadata, preserves precedence |
| `src/asky/api/types.py` | Modify | `PreloadResolution` has shortlist fields but no policy diagnostics | Adds policy source/diagnostic fields |
| `src/asky/api/client.py` | Modify | Preload provenance does not expose policy decision details | Provenance includes policy metadata for debug/parity visibility |
| `src/asky/config/__init__.py` | Modify | No dedicated preload-policy prompt constant | Exports `INTERFACE_PRELOAD_POLICY_SYSTEM_PROMPT` (name to be finalized in code) |
| `src/asky/data/config/prompts.toml` | Modify | Has XMPP interface planner prompt only | Adds prompt template for preload policy fallback classification |
| `tests/test_api_preload.py` | Modify | Tests current shortlist behavior/preload flow | Adds adaptive local-corpus shortlist policy assertions |
| `tests/test_api_library.py` | Modify | No assertions on preload policy diagnostics in provenance | Adds provenance metadata assertions |
| `src/asky/daemon/router.py` | Delete | Legacy duplicate XMPP router module exists | Removed |
| `src/asky/daemon/command_executor.py` | Delete | Legacy duplicate XMPP command executor exists | Removed |
| `src/asky/daemon/xmpp_client.py` | Delete | Legacy duplicate XMPP client exists | Removed |
| `src/asky/daemon/voice_transcriber.py` | Delete | Legacy duplicate voice transcriber exists | Removed |
| `src/asky/daemon/image_transcriber.py` | Delete | Legacy duplicate image transcriber exists | Removed |
| `src/asky/daemon/transcript_manager.py` | Delete | Legacy duplicate transcript manager exists | Removed |
| `src/asky/daemon/session_profile_manager.py` | Delete | Legacy duplicate session profile manager exists | Removed |
| `src/asky/daemon/chunking.py` | Delete | Legacy duplicate chunking exists | Removed |
| `tests/test_xmpp_router.py` | Modify | Imports `asky.daemon.router` | Imports plugin router path |
| `tests/test_xmpp_commands.py` | Modify | Imports/patches `asky.daemon.command_executor` | Imports/patches plugin command_executor path |
| `tests/test_xmpp_client.py` | Modify | Imports `asky.daemon.xmpp_client` | Imports plugin xmpp_client path |
| `tests/test_voice_transcription.py` | Modify | Imports `asky.daemon.voice_transcriber` | Imports plugin voice transcriber path |
| `tests/test_image_transcription.py` | Modify | Imports `asky.daemon.image_transcriber` | Imports plugin image transcriber path |
| `tests/test_safety_and_resilience_guards.py` | Modify | Inline imports include daemon command_executor constants | Uses plugin module paths/constants |
| `ARCHITECTURE.md` | Modify | May still imply legacy daemon XMPP module availability | States plugin-only canonical XMPP modules and shared policy flow |
| `docs/xmpp_daemon.md` | Modify | Planner contract/fallback docs partially outdated, no shared preload policy mention | Updated behavior docs for policy parity and plugin-only module ownership |
| `src/asky/api/AGENTS.md` | Modify | No shared adaptive shortlist policy guidance | Documents adaptive policy stage and precedence |
| `src/asky/daemon/AGENTS.md` | Modify | References daemon package context where legacy duplicates may be implied | Clarifies daemon core has no XMPP implementation modules |
| `src/asky/plugins/AGENTS.md` | Modify | May still imply mixed path ownership | States plugin modules are sole XMPP implementation |
| `DEVLOG.md` | Modify | No entry for this change | New dated entry with behavior changes, why, risks, follow-up |

If additional files are discovered during migration, discover first with:
`rg -n "asky\\.daemon\\.(router|command_executor|xmpp_client|voice_transcriber|image_transcriber|transcript_manager|session_profile_manager|chunking)" src tests docs`

## 5) Sequential Atomic Steps (with Dependencies + Verification)

1. Discovery lock-in (pre-change scan).
Dependency: none.
Work: run import/reference scans to ensure file inventory completeness before edits.
Verify:
- `rg -n "asky\\.daemon\\.(router|command_executor|xmpp_client|voice_transcriber|image_transcriber|transcript_manager|session_profile_manager|chunking)" src tests docs`
- `rg -n "shortlist_enabled_for_request|run_preload_pipeline" src/asky/api src/asky/cli src/asky/plugins/xmpp_daemon`

2. Add shared preload policy module.
Dependency: Step 1 complete.
Work: create `src/asky/api/preload_policy.py` with:
- deterministic intent extraction,
- ambiguity detection,
- fallback request/response contract,
- safe default behavior,
- structured diagnostics object.
Verify:
- `uv run pytest tests/test_preload_policy.py -q`

3. Add policy tests.
Dependency: Step 2.
Work: create `tests/test_preload_policy.py` covering deterministic web/local/ambiguous and fallback parse failures.
Verify:
- `uv run pytest tests/test_preload_policy.py -q`

4. Integrate policy into preload pipeline.
Dependency: Steps 2-3.
Work: modify `src/asky/api/preload.py`:
- preserve existing precedence,
- for local-corpus turns call new policy engine,
- force skip for `local_only`,
- write reason/source/diagnostics to preload result fields.
Verify:
- `uv run pytest tests/test_api_preload.py -q`

5. Extend preload types and provenance metadata.
Dependency: Step 4.
Work:
- modify `src/asky/api/types.py` to include policy fields,
- modify `src/asky/api/client.py` provenance payload.
Verify:
- `uv run pytest tests/test_api_library.py -q`

6. Add fallback prompt config and config export.
Dependency: Step 2.
Work:
- modify `src/asky/data/config/prompts.toml` with dedicated policy fallback prompt,
- modify `src/asky/config/__init__.py` to export constant.
Verify:
- `uv run pytest tests/test_config.py -q`

7. Delete legacy daemon XMPP module files.
Dependency: Step 1 (to ensure migration targets are known).
Work: delete the 8 daemon duplicate files listed above.
Verify:
- `test ! -f src/asky/daemon/router.py`
- `test ! -f src/asky/daemon/command_executor.py`
- `test ! -f src/asky/daemon/xmpp_client.py`
- `test ! -f src/asky/daemon/voice_transcriber.py`
- `test ! -f src/asky/daemon/image_transcriber.py`
- `test ! -f src/asky/daemon/transcript_manager.py`
- `test ! -f src/asky/daemon/session_profile_manager.py`
- `test ! -f src/asky/daemon/chunking.py`

8. Migrate tests/imports to plugin module paths.
Dependency: Step 7.
Work: update all affected tests and patch strings to `asky.plugins.xmpp_daemon.*`.
Verify:
- `rg -n "asky\\.daemon\\.(router|command_executor|xmpp_client|voice_transcriber|image_transcriber|transcript_manager|session_profile_manager|chunking)" tests src docs`
  Expected: no matches.
- `uv run pytest tests/test_xmpp_router.py tests/test_xmpp_commands.py tests/test_xmpp_client.py tests/test_voice_transcription.py tests/test_image_transcription.py tests/test_safety_and_resilience_guards.py -q`

9. Documentation and AGENTS updates.
Dependency: Steps 4 and 8.
Work: update architecture, behavior docs, and AGENTS files for new ownership and policy flow.
Verify:
- `rg -n "daemon/router\\.py|daemon/command_executor\\.py|daemon/xmpp_client\\.py|daemon/voice_transcriber\\.py|daemon/image_transcriber\\.py" ARCHITECTURE.md docs src/asky/*/AGENTS.md`
  Expected: no stale ownership claims.

10. DEVLOG update.
Dependency: all behavior changes done.
Work: append dated entry with summary, changed files/behavior, gotchas, follow-ups.
Verify:
- `rg -n "2026-03-01|shared adaptive policy|daemon XMPP canonicalization" DEVLOG.md`

11. Full regression.
Dependency: all prior steps.
Work: run full suite and ensure no regressions.
Verify:
- `uv run pytest`

## 6) Edge Cases as Requirements
1. `lean=True` must still disable shortlist regardless of policy output.
2. `shortlist_override="on"` must force shortlist even if policy says off.
3. `shortlist_override="off"` must disable shortlist even if policy says on.
4. `shortlist_override="reset"` must defer to session/global/mode + policy (not force behavior itself).
5. Local corpus absent must keep current non-adaptive shortlist logic.
6. `research_source_mode="local_only"` must skip shortlist even if query says “latest”.
7. Ambiguous query + interface model unset must fail-safe to shortlist off for local-corpus path.
8. Ambiguous query + malformed fallback JSON must fail-safe deterministically (no crash).
9. Fallback should receive compact context only (query text + minimal metadata), never full corpus bodies.
10. Query classification (`one_shot` vs `research`) must continue to function unchanged.
11. XMPP `ACTION_CHAT` path remains intact and unaffected by module migration.
12. No remaining references to deleted daemon XMPP modules in runtime/test/docs.

## 7) Verification Commands (Consolidated)
1. `uv run pytest tests/test_preload_policy.py -q`
2. `uv run pytest tests/test_api_preload.py -q`
3. `uv run pytest tests/test_api_library.py -q`
4. `uv run pytest tests/test_config.py -q`
5. `uv run pytest tests/test_xmpp_router.py tests/test_xmpp_commands.py tests/test_xmpp_client.py tests/test_voice_transcription.py tests/test_image_transcription.py tests/test_safety_and_resilience_guards.py -q`
6. `rg -n "asky\\.daemon\\.(router|command_executor|xmpp_client|voice_transcriber|image_transcriber|transcript_manager|session_profile_manager|chunking)" src tests docs`
7. `uv run pytest`

## 8) Final Checklist (Binary)
- [ ] Shared adaptive shortlist policy implemented in API preload path.
- [ ] Deterministic-first + ambiguous-only interface-model fallback implemented.
- [ ] `local_only` always skips shortlist.
- [ ] Override precedence unchanged and covered by tests.
- [ ] Preload policy diagnostics exposed in provenance metadata.
- [ ] Legacy daemon XMPP modules removed (no wrappers).
- [ ] All imports/tests/docs migrated to plugin XMPP module paths.
- [ ] `ARCHITECTURE.md`, relevant `AGENTS.md`, and docs updated.
- [ ] `DEVLOG.md` updated with date/summary/gotchas/follow-ups.
- [ ] Full test suite passes via `uv run pytest`.
- [ ] No debug artifacts, no commented-out code, no ad-hoc temporary files.

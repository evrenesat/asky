# RALF Plan: Plain-Query Interface Helper

## Summary
Extend the existing interface model into the shared standard-query pre-LLM path so normal turns can get one structured helper decision before preload and main-model execution. In v1, the helper applies only to standard (non-research) turns, never overrides explicit user constraints, never asks clarifying questions, and never generates the final answer.

Public/config contract to implement:
- New config keys in `general.toml`:
  - `interface_model_plain_query_enabled = true`
  - `interface_model_plain_query_prompt_enrichment_enabled = false`
- Reuse `general.interface_model` as the model alias; no new alias key.
- Add `AskyConfig` optional client overrides:
  - `plain_query_interface_enabled: Optional[bool] = None`
  - `plain_query_prompt_enrichment_enabled: Optional[bool] = None`
- Add a new prompt in `prompts.toml`: `plain_query_interface_system`
- Add plain-query helper metadata to `PreloadResolution`:
  - `interface_helper_applied: bool`
  - `interface_helper_source: str`
  - `interface_helper_reason: str`
  - `interface_helper_web_tools_mode: str` (`full|search_only|off`)
  - `interface_prompt_enrichment: Optional[str]`
  - `interface_memory_result: Optional[dict]`
  - `interface_notices: list[str]`
  - `interface_diagnostics: Optional[dict]`

Helper JSON contract to implement:
```json
{
  "shortlist_enabled": true,
  "web_tools_mode": "search_only",
  "prompt_enrichment": "",
  "memory_action": null,
  "reason": "simple_live_lookup"
}
```
Rules:
- `web_tools_mode` is exactly `full`, `search_only`, or `off`.
- `prompt_enrichment` is optional and only applied when prompt enrichment config is enabled.
- `memory_action` is either `null` or one global-memory save payload: `{"scope":"global","memory":"...","tags":[...]}`.
- No clarification field. No answer-style field. No final-answer text.

## Done Means
1. Standard CLI/API/XMPP query turns that reach shared `AskyClient.run_turn()` can use the helper before preload when `general.interface_model` is configured and plain-query helper is enabled.
2. Explicit user constraints remain hard gates:
   - `lean=True`
   - `preload_shortlist=False`
   - `shortlist_override=on|off`
   - caller-provided disabled tools
3. The helper may only shape:
   - shortlist on/off
   - turn-level availability of `web_search`, `get_url_content`, `get_url_details`
   - optional prompt enrichment
   - one automatic global-memory save
4. Prompt enrichment preserves the original query and appends helper context; it never replaces user text.
5. Automatic global-memory saves happen pre-LLM, use existing dedupe/storage logic, and always emit a user-visible notification:
   - CLI live banner status during the turn
   - green post-turn notice when rendered in CLI
   - structured metadata in `PreloadResolution` for non-CLI consumers
6. If the helper is disabled, misconfigured, returns invalid JSON, or transport fails, the turn falls back to current standard-query behavior with no prompt rewrite and no automatic memory write.
7. Full suite passes, and the final `time uv run pytest -q` is compared against the baseline:
   - `1387 passed in 25.96s`
   - `real 26.28s`

## Critical Invariants
1. The helper never overrides explicit user intent or explicit caller constraints.
2. Research-mode behavior stays unchanged in this handoff; existing research preload policy remains the only research helper path.
3. XMPP router classification stays unchanged; if a remote message is already classified as a query, the new helper may run later inside shared standard-query execution for that turn.
4. Automatic memory writes are global, pre-LLM, and use existing `save_memory` dedupe semantics; they are not routed through `--elephant-mode`.
5. Prompt enrichment is append-only and original-query-preserving.
6. `web_tools_mode=search_only` disables only `get_url_content` and `get_url_details`; `web_search` remains available.
7. `web_tools_mode=off` disables `web_search`, `get_url_content`, and `get_url_details`.
8. Helper parse/transport failures must be fail-open for answer flow and fail-closed for side effects: no crash, no rewrite, no memory save.
9. The helper must not alter answer verbosity policy in v1; short/simple queries only reduce retrieval depth.
10. User-visible docs must explicitly state that plain-query helper memory capture is separate from session-scoped `--elephant-mode`.

## Forbidden Implementations
1. Do not replace the original user prompt with rewritten text.
2. Do not let the helper touch custom tools, research tools, or `save_memory` tool availability in v1.
3. Do not auto-save memory after a fallback, parse failure, or config-disabled path.
4. Do not couple this feature to `--elephant-mode` session persistence or post-turn auto-extraction.
5. Do not add new CLI flags in this handoff.
6. Do not add a new interface-model alias key or a second planner model.
7. Do not document this as changing XMPP router classification or research-mode policy.
8. Do not update root `AGENTS.md`.
9. Do not add README sections if no relevant existing section already covers interface-model or memory behavior.

## Checkpoints

### [x] Checkpoint 1: Plain-Query Helper Contract And Config

**Goal:**
- Introduce the plain-query helper module, prompt contract, config keys, and typed metadata without changing runtime behavior yet.

**Context Bootstrapping:**
- Run these commands before editing:
- `rg -n "interface_model|PreloadResolution|AskyConfig|preload_policy" src/asky/api src/asky/config tests/asky/api tests/asky/config`
- `sed -n '1,220p' src/asky/api/types.py`
- `sed -n '1,220p' src/asky/config/__init__.py`
- `sed -n '140,230p' src/asky/data/config/prompts.toml`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/interface_query_policy.py`, `src/asky/api/types.py`, `src/asky/config/__init__.py`, `src/asky/data/config/general.toml`, `src/asky/data/config/prompts.toml`, `tests/asky/api/test_interface_query_policy.py`, `tests/asky/config/test_config.py`
- Must not touch: `src/asky/daemon/*`, `src/asky/plugins/xmpp_daemon/*`, `src/asky/memory/*`, CLI rendering
- Constraints: keep research `preload_policy.py` contract unchanged; do not add new dependencies; reuse `general.interface_model`

**Steps:**
- [ ] Add `InterfaceQueryPolicyEngine` with strict JSON parsing and a typed decision object for `shortlist_enabled`, `web_tools_mode`, optional `prompt_enrichment`, optional global `memory_action`, and `reason`.
- [ ] Add the new plain-query config defaults and exports.
- [ ] Add `AskyConfig` overrides and the new `PreloadResolution` metadata fields.
- [ ] Add unit tests for valid decision parsing, invalid JSON fallback, invalid mode fallback, and config export/default behavior.

**Dependencies:**
- Depends on none.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/api/test_interface_query_policy.py tests/asky/config/test_config.py -q`
- Run non-regression checks: `rg -n "interface_model_plain_query_enabled|plain_query_interface_system|plain_query_prompt_enrichment_enabled" src/asky/config src/asky/data/config src/asky/api tests/asky/config tests/asky/api`

**Done When:**
- Verification commands pass cleanly.
- The helper contract is typed, config-backed, and isolated behind a new module.
- A git commit is created with message: `Add plain-query interface helper contract`

**Stop and Escalate If:**
- A new alias key or CLI flag seems necessary to express the approved behavior.
- The contract cannot represent `search_only` cleanly without expanding v1 tool scope.

### [x] Checkpoint 2: Standard-Turn Integration For Shortlist, Web Tools, And Prompt Enrichment

**Goal:**
- Wire the helper into standard-turn `AskyClient.run_turn()` so it can shape shortlist behavior, web-tool availability, and optional prompt enrichment while preserving all explicit user constraints.

**Context Bootstrapping:**
- Run these commands before editing:
- `sed -n '560,980p' src/asky/api/client.py`
- `sed -n '150,260p' src/asky/api/preload.py`
- `sed -n '1,220p' src/asky/api/AGENTS.md`
- `rg -n "disabled_tools|shortlist_override|preload_shortlist|build_messages" src/asky/api src/asky/core`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/client.py`, `src/asky/api/preload.py`, `src/asky/api/AGENTS.md`, `tests/asky/api/test_api_preload.py`, `tests/asky/api/test_api_library.py`
- Must not touch: research tool registry behavior, `src/asky/daemon/interface_planner.py`, XMPP router classification, CLI rendering code
- Constraints: helper runs only for standard turns; do not change current research-mode policy; do not change answer-style behavior

**Steps:**
- [ ] Invoke the helper before `run_preload_pipeline()` for eligible standard turns only.
- [ ] Apply precedence exactly as approved:
  - explicit request/caller constraints first
  - helper decision only fills gaps
  - existing seed-direct-answer optimization still wins later if triggered
- [ ] Add an internal helper shortlist override path below explicit `shortlist_override` and above model/global defaults.
- [ ] Apply `web_tools_mode` by adding only helper-owned disables for `web_search`, `get_url_content`, and `get_url_details`.
- [ ] Apply prompt enrichment only when `plain_query_prompt_enrichment_enabled` is true, preserving the original query and appending helper context for preload and main-model visibility.
- [ ] Emit helper metadata through `PreloadResolution` and verbose preload provenance.

**Dependencies:**
- Depends on Checkpoint 1.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/api/test_api_preload.py tests/asky/api/test_api_library.py -q`
- Run non-regression tests: `uv run pytest tests/asky/daemon/test_interface_planner.py -q`
- Run search checks: `rg -n "interface_helper_|web_tools_mode|prompt_enrichment" src/asky/api`

**Done When:**
- Verification commands pass cleanly.
- A standard non-research turn can resolve `full`, `search_only`, or `off` web behavior without changing research-mode logic.
- Prompt enrichment is append-only and metadata-visible.
- A git commit is created with message: `Wire plain-query helper into standard turns`

**Stop and Escalate If:**
- The shared API path cannot support XMPP standard-query reuse without touching router semantics.
- Prompt enrichment requires replacing original user text to be effective.

### [x] Checkpoint 3: Automatic Global Memory Save And User Notifications

**Goal:**
- Add pre-LLM automatic global-memory saves from the helper, with banner/notices output and no ambiguity/confirmation path.

**Context Bootstrapping:**
- Run these commands before editing:
- `sed -n '1,220p' src/asky/memory/tools.py`
- `sed -n '660,980p' src/asky/api/client.py`
- `sed -n '760,1060p' src/asky/cli/chat.py`
- `sed -n '1,220p' src/asky/src/asky/memory/AGENTS.md`

**Scope & Blast Radius:**
- May create/modify: `src/asky/api/client.py`, `src/asky/cli/chat.py`, `src/asky/cli/AGENTS.md`, `tests/asky/memory/test_user_memory.py`, `tests/asky/cli/test_cli.py`
- Must not touch: `src/asky/memory/store.py`, `src/asky/memory/vector_ops.py`, research memory, elephant-mode extraction logic
- Constraints: use existing `execute_save_memory()` path; save is global only; do not add a confirmation loop; do not create multiple UX surfaces with conflicting messages

**Steps:**
- [ ] Execute helper `memory_action` before preload memory recall so the saved global memory can participate in the same turn’s recall if relevant.
- [ ] Limit v1 to at most one automatic global-memory write per turn; ignore extras with diagnostics.
- [ ] Record structured `interface_memory_result` metadata and human-readable `interface_notices`.
- [ ] In CLI, surface helper notices as:
  - live banner status message during the turn
  - bold green post-turn output after the answer
- [ ] Use exact notice wording:
  - `New memory: <text>. MemID#<id>`
  - `Updated memory: <text>. MemID#<id>`
  - `Your prompt enriched: <preview>`
- [ ] Add tests for saved vs updated memory, helper-disabled path, fallback path, and green-notice rendering behavior.

**Dependencies:**
- Depends on Checkpoint 2.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/memory/test_user_memory.py tests/asky/cli/test_cli.py -q`
- Run non-regression tests: `uv run pytest tests/asky/api/test_api_library.py -q`
- Run search checks: `rg -n "New memory:|Updated memory:|Your prompt enriched:" src/asky/api src/asky/cli tests/asky`

**Done When:**
- Verification commands pass cleanly.
- Automatic helper memory saves use the existing dedupe path and always produce user-visible output.
- CLI notices are green for helper save/enrichment messages without changing unrelated notice formatting.
- A git commit is created with message: `Add helper-driven global memory saves and notices`

**Stop and Escalate If:**
- More than one automatic memory save per turn becomes necessary to meet product expectations.
- The existing CLI notice/banner surfaces cannot represent the approved UX without broader UI changes.

### [x] Checkpoint 4: Documentation, AGENTS Parity, And Full Regression

**Goal:**
- Update architecture/user docs to match the implemented behavior and verify that runtime/test performance remains proportional.

**Context Bootstrapping:**
- Run these commands before editing:
- `sed -n '1,220p' ARCHITECTURE.md`
- `sed -n '1,220p' devlog/DEVLOG.md`
- `sed -n '1,220p' src/asky/api/AGENTS.md`
- `sed -n '1,220p' src/asky/config/AGENTS.md`
- `sed -n '1,220p' src/asky/cli/AGENTS.md`
- `sed -n '1,260p' docs/configuration.md`
- `sed -n '240,360p' docs/library_usage.md`
- `sed -n '1,220p' docs/elephant_mode.md`
- `sed -n '120,220p' docs/xmpp_daemon.md`

**Scope & Blast Radius:**
- May create/modify: `ARCHITECTURE.md`, `devlog/DEVLOG.md`, `src/asky/api/AGENTS.md`, `src/asky/config/AGENTS.md`, `src/asky/cli/AGENTS.md`, `docs/configuration.md`, `docs/library_usage.md`, `docs/elephant_mode.md`, `docs/xmpp_daemon.md`
- Must not touch: root `AGENTS.md`; README unless an already-relevant section exists
- Constraints: document only shipped behavior; if no relevant README section exists, leave README unchanged and say so in commit notes

**Steps:**
- [ ] Update architecture flow to show the new standard-query interface helper before preload and main-model execution.
- [ ] Update config and library docs with the new defaults, client overrides, and metadata fields.
- [ ] Update elephant-mode docs to state clearly that post-turn session auto-extraction and pre-LLM helper global-memory capture are separate features.
- [ ] Update XMPP docs to state that router classification is unchanged, but standard query execution later inherits the shared plain-query helper.
- [ ] Update `src/asky/api/AGENTS.md`, `src/asky/config/AGENTS.md`, and `src/asky/cli/AGENTS.md` only where local behavior/maintenance guidance changed.
- [ ] Add a DEVLOG entry with date, summary, changed behavior, and follow-up notes.
- [ ] Run the full suite and compare runtime to the baseline.

**Dependencies:**
- Depends on Checkpoint 3.

**Verification:**
- Run scoped tests: `uv run pytest tests/asky/api tests/asky/cli tests/asky/memory -q`
- Run non-regression tests: `time uv run pytest -q`
- Run doc consistency checks:
  - `rg -n "plain query|prompt enrichment|interface_model_plain_query_enabled|Updated memory|elephant-mode" ARCHITECTURE.md devlog/DEVLOG.md docs src/asky/*/AGENTS.md`
  - `rg -n "daemon routing|router classification|shared plain-query helper" docs/xmpp_daemon.md`

**Done When:**
- Verification commands pass cleanly.
- Documentation reflects only the implemented behavior.
- Final runtime is reviewed against baseline `1387 passed in 25.96s` / `real 26.28s`; any disproportionate increase is explained or fixed.
- A git commit is created with message: `Document plain-query interface helper`

**Stop and Escalate If:**
- Docs imply behavior that is not yet implemented.
- Test runtime grows materially beyond the added targeted coverage and the slowdown source is unclear.

## Behavioral Acceptance Tests
1. Given a standard query like “weather in Amsterdam”, the helper can enable shortlist but set `web_tools_mode=search_only`, so the turn may use search/snippets without allowing page fetch tools.
2. Given a standard query with prompt enrichment enabled, the main-model request still includes the original user query verbatim plus appended helper context, and the CLI shows `Your prompt enriched: ...`.
3. Given a standard query with prompt enrichment disabled, the helper may still shape shortlist/tool policy, but no rewrite text is appended anywhere.
4. Given a standard query that clearly contains a durable user fact like “I prefer Python for backend work”, the helper can save one global memory pre-LLM, the save goes through dedupe, and the user sees `New memory:` or `Updated memory:` with `MemID#...`.
5. Given `--lean`, `--shortlist off`, `preload_shortlist=False`, or caller-disabled web tools, the helper does not override those constraints.
6. Given helper invalid JSON or transport failure, the query still completes using current behavior and no prompt enrichment or memory save happens.
7. Given a standard XMPP query already routed as a query, the router behavior is unchanged, but the downstream standard-turn execution may still apply the shared helper policy.
8. Given research mode, the new plain-query helper does not run and the current research preload policy remains authoritative.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Explicit user constraints always win | `uv run pytest tests/asky/api/test_api_preload.py -q` |
| Standard helper only affects standard turns | `uv run pytest tests/asky/api/test_api_preload.py tests/asky/daemon/test_interface_planner.py -q` |
| Prompt enrichment is append-only and separately gated | `uv run pytest tests/asky/api/test_api_library.py tests/asky/cli/test_cli.py -q` |
| Web-tool scope is limited to `web_search/get_url_content/get_url_details` | `rg -n "web_tools_mode|get_url_content|get_url_details|web_search" src/asky/api src/asky/core tests/asky/api` |
| Automatic memory save is global and dedup-backed | `uv run pytest tests/asky/memory/test_user_memory.py -q` |
| Helper failures produce no side effects | `uv run pytest tests/asky/api/test_interface_query_policy.py tests/asky/api/test_api_preload.py -q` |
| CLI users are notified about save/enrichment | `uv run pytest tests/asky/cli/test_cli.py -q` |
| Docs accurately distinguish helper memory vs elephant mode | `rg -n "elephant-mode|global memory|plain-query helper" docs/elephant_mode.md docs/configuration.md docs/library_usage.md ARCHITECTURE.md` |
| Runtime stays proportional | `time uv run pytest -q` compared to baseline `real 26.28s` |

## Assumptions And Defaults
1. `general.interface_model` remains the only model-alias source for router/preload/plain-query helper work.
2. Plain-query helper config is default-enabled, but it is inert unless `general.interface_model` resolves to a non-empty valid alias.
3. Prompt enrichment is off by default and must be independently enabled.
4. No new CLI flag is added in v1; configurability comes from TOML plus `AskyConfig` client overrides.
5. `AskyTurnRequest` stays unchanged in v1.
6. Helper memory automation is not elephant mode; elephant mode remains post-turn, session-scoped extraction.
7. The memory package’s storage/dedupe implementation remains unchanged; only a new caller path is added.
8. README stays untouched unless an already-relevant section exists; do not create a new README section just for this feature.
9. `src/asky/memory/AGENTS.md` and `tests/AGENTS.md` remain unchanged unless implementation work actually alters their local maintenance rules; otherwise leave them untouched and note why in the final implementation summary.

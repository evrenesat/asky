## Plan: Add Configurable Local-Ingestion Security Gates (Absolute Path Relaxation + Extension Allowlist)

### Summary
Implement two new research security configs while preserving current defaults:

1. `research.allow_absolute_paths_outside_roots` (bool, default `false`): keeps current strict behavior by default; when `true`, absolute local paths can be ingested even if outside `local_document_roots`.
2. `research.allowed_ingestion_extensions` (list, default `[]`): global allowlist for ingestion file extensions; empty list preserves current behavior (all supported built-in + plugin extensions), non-empty list restricts ingestion surface.

Done means both controls are enforced consistently across CLI `-r` parsing, local adapter ingestion, and XMPP document ingestion, with updated docs and tests.

### Objective
Provide explicit, user-controlled hardening against data exfiltration risks from prompt-injection-driven local ingestion while maintaining backward compatibility by default.

### Public Interfaces / Type Changes
1. Add config key in `research.toml`:
`allow_absolute_paths_outside_roots = false`
2. Add config key in `research.toml`:
`allowed_ingestion_extensions = []`
3. Add exported constants in `asky.config`:
`RESEARCH_ALLOW_ABSOLUTE_PATHS_OUTSIDE_ROOTS`
`RESEARCH_ALLOWED_INGESTION_EXTENSIONS`
4. Extension parsing contract:
case-insensitive; normalize to lowercase with leading `.`; invalid/blank entries ignored.

### File Inventory (create/modify)
1. [/Users/evren/code/asky/src/asky/data/config/research.toml](/Users/evren/code/asky/src/asky/data/config/research.toml)
2. [/Users/evren/code/asky/src/asky/config/__init__.py](/Users/evren/code/asky/src/asky/config/__init__.py)
3. [/Users/evren/code/asky/src/asky/cli/main.py](/Users/evren/code/asky/src/asky/cli/main.py)
4. [/Users/evren/code/asky/src/asky/research/adapters.py](/Users/evren/code/asky/src/asky/research/adapters.py)
5. [/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/document_ingestion.py](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/document_ingestion.py) (only if explicit messaging needs alignment; logic should mostly inherit from adapters helper)
6. [/Users/evren/code/asky/tests/test_research_corpus_resolution.py](/Users/evren/code/asky/tests/test_research_corpus_resolution.py)
7. [/Users/evren/code/asky/tests/test_research_adapters.py](/Users/evren/code/asky/tests/test_research_adapters.py)
8. [/Users/evren/code/asky/tests/test_local_source_handler_plugins.py](/Users/evren/code/asky/tests/test_local_source_handler_plugins.py)
9. [/Users/evren/code/asky/tests/test_xmpp_document_ingestion.py](/Users/evren/code/asky/tests/test_xmpp_document_ingestion.py)
10. [/Users/evren/code/asky/ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md)
11. [/Users/evren/code/asky/docs/research_mode.md](/Users/evren/code/asky/docs/research_mode.md)
12. [/Users/evren/code/asky/docs/troubleshooting.md](/Users/evren/code/asky/docs/troubleshooting.md)
13. [/Users/evren/code/asky/docs/configuration.md](/Users/evren/code/asky/docs/configuration.md)
14. [/Users/evren/code/asky/src/asky/config/AGENTS.md](/Users/evren/code/asky/src/asky/config/AGENTS.md)
15. [/Users/evren/code/asky/src/asky/research/AGENTS.md](/Users/evren/code/asky/src/asky/research/AGENTS.md)
16. [/Users/evren/code/asky/src/asky/cli/AGENTS.md](/Users/evren/code/asky/src/asky/cli/AGENTS.md) (if `-r` behavior text is documented there)
17. [/Users/evren/code/asky/src/asky/plugins/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/AGENTS.md) or [/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/AGENTS.md](/Users/evren/code/asky/src/asky/plugins/xmpp_daemon/AGENTS.md) if extension-policy behavior is documented there
18. [/Users/evren/code/asky/devlog/DEVLOG.md](/Users/evren/code/asky/devlog/DEVLOG.md)

### Before/After (key behavior)
1. Absolute path handling:
Before: absolute paths must be inside roots.
After: same when flag is `false`; bypass root containment when flag is `true`.
2. Relative path handling:
Before: must resolve under configured roots.
After: unchanged.
3. Extension acceptance:
Before: any built-in + plugin extension is accepted.
After: same when allowlist is empty; restricted to configured extension set when non-empty.
4. Scope:
Before: rules differ by codepath.
After: extension allowlist and absolute-path policy apply globally across local ingestion surfaces.

### Sequential Atomic Steps
1. Add new config defaults and exports.
Update `research.toml`; parse/normalize in `config/__init__.py` and expose constants.
2. Apply absolute-path config in CLI parser path.
In `_resolve_research_corpus`, gate outside-root absolute acceptance on new bool; keep existing fallback for non-existing `/foo/bar` to root-relative lookup.
3. Apply absolute-path config in adapter path.
In `_resolve_local_target_paths`, allow existing absolute paths outside roots only when bool is enabled; preserve current strict default.
4. Implement extension allowlist filtering in adapters.
Add a normalized configured-extension set helper; enforce it in directory discovery, built-in reads, and plugin handler reads.
5. Ensure XMPP document ingestion uses same extension policy.
Keep `get_all_supported_extensions()` as policy source so `split_document_urls` and URL ingestion checks follow config automatically; adjust explicit error text only if needed.
6. Add/adjust tests for strict-default behavior and opt-in behavior.
Cover both flags and both path types; include plugin extension restriction tests and XMPP URL filtering tests.
7. Update architecture/user/internal docs and AGENTS docs.
Document defaults, security rationale, and examples.
8. Update `DEVLOG.md`.
Record date, change summary, rationale, verification, and any gotchas.
9. Run full suite and compare runtime.
Use existing baseline and note pre-existing unrelated failures.

### Edge Cases (requirements)
1. `allow_absolute_paths_outside_roots=false` and absolute outside roots -> reject (current behavior).
2. `allow_absolute_paths_outside_roots=true` and absolute outside roots -> ingest.
3. Absolute path + no roots configured:
reject when flag is false; allow when true.
4. Relative path + no roots configured -> reject with roots guidance.
5. `/nested/doc.txt` not existing absolute but exists under root -> still resolves under roots.
6. Allowlist set to `[".pdf"]` blocks `.txt` and plugin extensions.
7. Allowlist empty keeps current behavior for built-in and plugin extensions.
8. Extension tokens provided as `PDF` or `pdf` normalize to `.pdf`.
9. Unknown/invalid extension items in config do not crash; ignored safely.

### Constraints (do not do)
1. Do not change default security behavior for absolute paths; must remain strict by default.
2. Do not weaken relative-path sanitization/root containment checks.
3. Do not introduce new dependencies.
4. Do not modify unrelated failing tests (`tests/test_devlog_weekly_archiver.py`) in this task.
5. Do not bypass extension allowlist for plugin handlers when allowlist is configured.

### Verification Plan
1. `uv run pytest tests/test_research_corpus_resolution.py tests/test_research_adapters.py tests/test_local_source_handler_plugins.py tests/test_xmpp_document_ingestion.py -q`
2. `uv run pytest tests/test_local_ingestion_flow.py -q`
3. `time uv run pytest -q`
4. `rg -n "allow_absolute_paths_outside_roots|allowed_ingestion_extensions" src/asky/data/config/research.toml src/asky/config/__init__.py docs ARCHITECTURE.md`
5. Confirm runtime comparison against baseline (~9.85s total, with 2 known pre-existing failures before this change).

### Assumptions / Defaults Chosen
1. Config key names: `allow_absolute_paths_outside_roots`, `allowed_ingestion_extensions`.
2. Extension allowlist default: empty means “no extra restriction” (backward compatible).
3. Allowlist scope: global ingestion surface (CLI/local preload/plugin handlers/XMPP URL ingestion).

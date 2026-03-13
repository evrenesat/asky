# CLI Help Discoverability Sync RALF Handoff v2

## Summary

Re-implement the CLI help discoverability work from scratch, keeping the original goal but incorporating the two concrete lessons from the failed first implementation:

- the `--help-all` contract must hold for direct `parse_args()` callers, not only for the local `main()` entrypoint,
- the discoverability tests must enforce the full declared public CLI surface, not only the specific omissions found during the first review.

The target behavior remains:

- `asky --help` is a short grouped guide,
- `asky --help-all` is the full public flag reference,
- `asky persona --help` remains the persona-specific subcommand help,
- every public user-facing capability is discoverable from at least one documented help surface.

This handoff does **not** add literal `asky help all`. The supported full-reference command remains `asky --help-all`.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `6387e1a9fb8edc0951fcd32a3418dbde71f587a3`
- Last Reviewed HEAD: `6e429b1367080ef11dfed5dce48d7d393d0d2de8`
- Review Log:
  - 2026-03-13: reviewed range `6387e1a9fb8edc0951fcd32a3418dbde71f587a3..cb454d0af7277e29449990043abb194283f6fe47`, squashed to `6e429b1367080ef11dfed5dce48d7d393d0d2de8`, outcome `approved+squashed`.

## Done Means

- Curated short help and grouped help pages are rendered from a production-side help/discoverability catalog, not long handwritten string blocks in `main.py`.
- `asky --help` remains materially shorter than `asky --help-all`, but explicitly exposes:
  - `asky persona --help`
  - `--continue-chat`
  - `--reply`
  - `--elephant-mode`
  - `session delete`
- `asky session --help` includes `session delete`.
- `asky --help-all` includes all declared public flags, including plugin-contributed public flags such as `--sendmail`, `--subject`, `--push-data`, `--browser`, and `--daemon`.
- The `--help-all` contract holds both for:
  - the normal local CLI entrypoint (`python -m asky --help-all` / console script), and
  - direct callers of `asky.cli.parse_args()`.
- Persona help remains authoritative for persona subcommands and is reachable from top-level help.
- The test suite enforces the full declared public help contract:
  - every `PUBLIC_TOP_LEVEL_FLAGS` item is asserted on `--help-all`,
  - every `PLUGIN_FLAGS` item is asserted on `--help-all`,
  - every `PERSONA_SUBCOMMANDS` item is asserted on `asky persona --help`,
  - every `GROUPED_COMMANDS` item is asserted on its assigned grouped help page,
  - the intentionally curated short-help items are asserted on `asky --help`.
- Existing command semantics, parser routing, plugin activation behavior, and non-help CLI behavior remain unchanged.

## Critical Invariants

- `--help-all` remains the only supported full-reference command in this handoff.
- Top-level `asky --help` must remain a short grouped page; do not let it become a near-duplicate of full help.
- Plugin help collection must remain light-import only; no plugin activation is allowed to render help.
- Suppressed internal routing flags must remain suppressed in `--help-all`.
- The `main()` path and the exported `asky.cli.parse_args()` wrapper must not disagree about `--help-all` public flag coverage.
- Production code must own curated help/discoverability metadata; tests may validate it, but production must not import test manifests.
- The canonical parser-surface manifest in `tests/integration/cli_recorded/cli_surface.py` remains authoritative for what is public.
- Grouped-command routing behavior must remain unchanged.
- `corpus summarize-section` remains an internal/equivalent routing alias for this handoff, not a separately documented grouped public command.

## Forbidden Implementations

- Do not add a new dependency such as `rich-argparse`, `totalhelp`, Click, Typer, or another CLI framework in this handoff.
- Do not rewrite the CLI around argparse subparsers.
- Do not keep the old handwritten curated help blocks as the long-term source of truth.
- Do not fix `--help-all` completeness only on the `main()` path while leaving direct `parse_args()` callers inconsistent.
- Do not hardcode fake plugin managers in production or require external callers to pass plugin managers manually.
- Do not activate plugin runtime or plugin hooks to render help.
- Do not rely on full-output snapshots of help text in tests.
- Do not weaken discoverability assertions to vague substring checks that pass when the actual token or command is missing.
- Do not duplicate the public CLI surface in a third unrelated mapping just to make tests pass.
- Do not modify root `AGENTS.md`.

## Checkpoints

### [x] Checkpoint 1: Define the discoverability contract and production-side help catalog

**Goal:**

- Create one production-owned help catalog that can render curated short/grouped help and define the explicit discoverability contract the tests will enforce.

**Context Bootstrapping:**

- Run these commands before editing:
- `pwd`
- `git branch --show-current`
- `git rev-parse HEAD`
- `sed -n '120,360p' src/asky/cli/main.py`
- `sed -n '760,1265p' src/asky/cli/main.py`
- `sed -n '1768,1845p' src/asky/cli/main.py`
- `sed -n '1,220p' tests/integration/cli_recorded/cli_surface.py`
- `sed -n '68,130p' tests/asky/cli/test_cli.py`
- Capture the Git Tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
  - `src/asky/cli/help_catalog.py`
  - `src/asky/cli/main.py`
- Must not touch:
  - `src/asky/plugins/**`
  - tests in this checkpoint
  - documentation in this checkpoint
- Constraints:
  - Keep `persona` on its separate parser path.
  - Preserve grouped routing and existing command names.
  - The catalog must be able to express:
    - curated top-level short-help sections,
    - grouped help pages,
    - top-level short-help required items,
    - secondary-help entrypoints.

**Steps:**

- [ ] Step 1: Create `src/asky/cli/help_catalog.py` with typed structures for:
  - help items,
  - help sections,
  - curated help pages,
  - rendering helpers,
  - explicit discoverability sets for top-level curated requirements.
- [ ] Step 2: Move the curated top-level/grouped help content out of raw string blocks in `src/asky/cli/main.py` and into the catalog.
- [ ] Step 3: Define top-level short-help content to include:
  - grouped commands,
  - configuration commands,
  - a short “Conversation & Memory” or equivalent section containing `--continue-chat`, `--reply`, and `--elephant-mode`,
  - query options,
  - plugin-contributed sections,
  - “More help” including `asky persona --help`.
- [ ] Step 4: Define grouped help pages for `history`, `session`, `memory`, `corpus`, and `prompts`.
- [ ] Step 5: Include `session delete` in grouped session help.
- [ ] Step 6: Keep `corpus summarize-section` undocumented as a separate grouped command, but ensure `corpus summarize --help` still exposes section-summarization semantics.

**Dependencies:**

- No prior checkpoint.

**Verification:**

- Run scoped help checks:
- `uv run python -m asky --help`
- `uv run python -m asky session --help`
- `uv run python -m asky corpus --help`
- `uv run python -m asky corpus summarize --help`
- Run targeted assertions:
- `uv run python -m asky --help | rg "asky persona --help|--continue-chat|--reply|--elephant-mode"`
- `uv run python -m asky session --help | rg "session delete"`
- Run non-regression tests:
- `uv run pytest tests/asky/cli/test_cli.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- `src/asky/cli/main.py` no longer owns large handwritten curated help blocks.
- `asky --help` remains short and grouped while surfacing the required top-level discoverability items.
- `asky session --help` includes `session delete`.
- A git commit is created with message: `Refactor curated CLI help around discoverability catalog`

**Stop and Escalate If:**

- The catalog cannot express the current grouped layout without reintroducing large raw string templates.
- Keeping `asky --help` short while surfacing the required missing items proves impossible without a product decision on top-level help size.
- `corpus summarize-section` is discovered to have materially distinct public semantics.

### [x] Checkpoint 2: Make `--help-all` complete on both `main()` and direct `parse_args()` paths

**Goal:**

- Ensure the full-help contract does not depend on which entrypoint invoked parsing.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '32,48p' src/asky/cli/__init__.py`
- `sed -n '760,1265p' src/asky/cli/main.py`
- `sed -n '308,325p' src/asky/plugins/xmpp_daemon/command_executor.py`
- `sed -n '570,590p' src/asky/plugins/xmpp_daemon/command_executor.py`
- `uv run python -m asky --help-all`
- `uv run python - <<'PY'\nimport io, contextlib\nfrom asky.cli import parse_args\nfrom unittest.mock import patch\nimport sys\nbuf = io.StringIO()\nwith patch.object(sys, 'argv', ['asky', '--help-all']), contextlib.redirect_stdout(buf):\n    try:\n        parse_args()\n    except SystemExit:\n        pass\nprint(buf.getvalue())\nPY`

**Scope & Blast Radius:**

- May create/modify:
  - `src/asky/cli/__init__.py`
  - `src/asky/cli/main.py`
  - `tests/asky/cli/test_help_discoverability.py`
- Must not touch:
  - plugin implementation files
  - non-help command behavior in XMPP or CLI
  - documentation in this checkpoint
- Constraints:
  - Keep `parse_args(argv=None)` as the exported wrapper signature.
  - Do not require external callers to know about `plugin_manager`.
  - Plugin bootstrap must stay narrow and light-import only.
  - Ordinary non-help direct parse paths must preserve existing behavior.

**Steps:**

- [ ] Step 1: Implement narrow automatic plugin-manager bootstrap for parser invocations that require plugin-contributed help/flags when `plugin_manager` is not already supplied.
- [ ] Step 2: Make that narrow bootstrap cover:
  - `--help-all`,
  - direct parses of plugin-contributed public flags where needed for argparse recognition/help fidelity.
- [ ] Step 3: Do not bootstrap broadly for unrelated non-help parses.
- [ ] Step 4: Ensure the exported `asky.cli.parse_args()` wrapper uses the same narrow bootstrap behavior as the local CLI path.
- [ ] Step 5: Add direct-wrapper regression tests proving `from asky.cli import parse_args` plus `--help-all` exposes plugin flags.
- [ ] Step 6: Add a negative regression proving non-help direct parses do not require plugin activation.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/cli/test_help_discoverability.py -q -n0`
- Run local CLI smoke:
- `uv run python -m asky --help-all | rg -- "--sendmail|--subject|--push-data|--browser|--daemon"`
- Run direct-wrapper smoke:
- `uv run python - <<'PY'\nimport io, contextlib\nfrom asky.cli import parse_args\nfrom unittest.mock import patch\nimport sys\nbuf = io.StringIO()\nwith patch.object(sys, 'argv', ['asky', '--help-all']), contextlib.redirect_stdout(buf):\n    try:\n        parse_args()\n    except SystemExit:\n        pass\ntext = buf.getvalue()\nfor token in ['--sendmail','--subject','--push-data','--browser','--daemon']:\n    assert token in text, token\nprint('ok')\nPY`
- Run non-regression tests:
- `uv run pytest tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Done When:**

- Verification commands pass cleanly.
- `--help-all` shows plugin public flags on both the normal local CLI path and direct `asky.cli.parse_args()` usage.
- Non-help direct parse callers retain current behavior.
- A git commit is created with message: `Fix help-all contract for direct parse_args callers`

**Stop and Escalate If:**

- The only working solution is broad plugin bootstrap on every parser call.
- The change would alter XMPP command classification/execution behavior instead of only help/bootstrap fidelity.

### [x] Checkpoint 3: Enforce the full discoverability contract from the declared public surface

**Goal:**

- Replace the first-pass handpicked assertions with comprehensive contract tests tied to the declared public CLI surface.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,220p' tests/integration/cli_recorded/cli_surface.py`
- `sed -n '1,220p' tests/integration/cli_recorded/test_cli_surface_manifest.py`
- `sed -n '1,260p' tests/asky/cli/test_help_discoverability.py`
- `sed -n '1,260p' src/asky/cli/help_catalog.py`
- `uv run python -m asky --help`
- `uv run python -m asky --help-all`
- `uv run python -m asky history --help`
- `uv run python -m asky session --help`
- `uv run python -m asky memory --help`
- `uv run python -m asky corpus --help`
- `uv run python -m asky persona --help`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/asky/cli/test_help_discoverability.py`
  - `tests/integration/cli_recorded/cli_surface.py`
  - `tests/integration/cli_recorded/test_cli_surface_manifest.py`
  - `src/asky/cli/help_catalog.py` only if extra discoverability metadata is needed
- Must not touch:
  - parser behavior unrelated to help discoverability
  - plugin implementation files
  - documentation in this checkpoint
- Constraints:
  - The canonical parser-surface manifest in `tests/integration/cli_recorded/cli_surface.py` remains authoritative for what is public.
  - Tests must assert exact option tokens or normalized same-line command prefixes.
  - No full-output snapshots.
  - Do not create a third disconnected source of truth for the public surface.

**Steps:**

- [ ] Step 1: Add explicit discoverability assignments that map the declared public surface to help surfaces.
- [ ] Step 2: Enforce this contract:
  - every item in `PUBLIC_TOP_LEVEL_FLAGS` appears in `asky --help-all`,
  - every item in `PLUGIN_FLAGS` appears in `asky --help-all`,
  - every item in `PERSONA_SUBCOMMANDS` appears in `asky persona --help`,
  - every item in `GROUPED_COMMANDS` appears on its assigned grouped help page,
  - the intentionally curated short-help items appear on `asky --help`.
- [ ] Step 3: Use grouped-page assignment by noun:
  - `history *` -> `asky history --help`
  - `session *` -> `asky session --help`
  - `memory *` -> `asky memory --help`
  - `corpus *` -> `asky corpus --help` or the specific corpus sub-help page if intentionally assigned there
  - `prompts list` -> top-level short help unless a dedicated grouped `prompts --help` surface is added in the same handoff
- [ ] Step 4: Add one cross-check that fails if any public manifest item lacks a declared discoverability surface.
- [ ] Step 5: Keep the narrow smoke assertions in `tests/asky/cli/test_cli.py`, but move the real comprehensive guarantee into `tests/asky/cli/test_help_discoverability.py`.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests:
- `uv run pytest tests/asky/cli/test_help_discoverability.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -n0`
- Run broader CLI tests:
- `uv run pytest tests/asky/cli/test_cli.py -q -n0`
- Run smoke commands:
- `uv run python -m asky --help`
- `uv run python -m asky --help-all`
- `uv run python -m asky session --help`
- `uv run python -m asky corpus --help`
- `uv run python -m asky persona --help`

**Done When:**

- Verification commands pass cleanly.
- The discoverability test suite enforces all declared public flags and commands, not only the originally missed ones.
- A future omission of any public flag or public command from its assigned help surface fails tests.
- A git commit is created with message: `Expand CLI help discoverability coverage`

**Stop and Escalate If:**

- Some manifest-declared public items cannot be assigned cleanly to top-level short help, grouped help, persona help, or `--help-all` without a product decision.
- The only practical implementation would duplicate the full parser surface in another large ad hoc mapping.

### [x] Checkpoint 4: Documentation parity and final verification

**Goal:**

- Update the docs to reflect the final shipped help contract and finish with full verification.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,120p' ARCHITECTURE.md`
- `sed -n '1,220p' src/asky/cli/AGENTS.md`
- `sed -n '1,160p' README.md`
- `sed -n '1,120p' devlog/DEVLOG.md`
- `rg -n "help-all|--help|persona --help|grouped help|curated top-level help" ARCHITECTURE.md src/asky/cli/AGENTS.md README.md docs tests`
- `uv run python -m asky --help`
- `uv run python -m asky --help-all`
- `uv run python -m asky persona --help`

**Scope & Blast Radius:**

- May create/modify:
  - `ARCHITECTURE.md`
  - `src/asky/cli/AGENTS.md`
  - `README.md` only if an existing relevant CLI/help section needs updating
  - `devlog/DEVLOG.md`
- Must not touch:
  - root `AGENTS.md`
  - unrelated docs
- Constraints:
  - Update docs only to match behavior implemented in Checkpoints 1 through 3.
  - If `README.md` has no relevant existing section, leave it unchanged.
  - Keep the devlog entry factual and record the final test runtime against the baseline.

**Steps:**

- [ ] Step 1: Update `ARCHITECTURE.md` so it describes:
  - the production-side help catalog,
  - the three help surfaces,
  - `--help-all` completeness including plugin public flags.
- [ ] Step 2: Update `src/asky/cli/AGENTS.md` so local guidance points contributors to the production-side help catalog and the discoverability contract.
- [ ] Step 3: Search for an existing relevant help section in `README.md`; update only that section if it exists.
- [ ] Step 4: Add a `devlog/DEVLOG.md` entry summarizing the help discoverability implementation and verification.
- [ ] Step 5: Run targeted verification and the full suite.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped verification:
- `uv run pytest tests/asky/cli/test_cli.py tests/asky/cli/test_help_discoverability.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -n0`
- Run full regression:
- `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Documentation matches the shipped help contract and does not describe unresolved follow-up work as already done.
- The final full-suite runtime is recorded and compared against the baseline.
- A git commit is created with message: `Document CLI help discoverability contract`

**Stop and Escalate If:**

- The implemented behavior differs from the contract enough that docs would need to describe a different user-facing model.
- Full regression fails or regresses materially for reasons not explained by the added tests.

## Behavioral Acceptance Tests

- Given `uv run python -m asky --help`, the output is still a short grouped page and explicitly includes `asky persona --help`.
- Given `uv run python -m asky --help`, the output includes `--continue-chat`, `--reply`, and `--elephant-mode`.
- Given `uv run python -m asky session --help`, the output includes `session delete`.
- Given `uv run python -m asky --help-all`, the output includes plugin public flags such as `--sendmail`, `--subject`, `--push-data`, `--browser`, and `--daemon`.
- Given `from asky.cli import parse_args` and `--help-all`, the output includes the same plugin public flags as the normal local CLI path.
- Given `uv run python -m asky persona --help`, the output still shows all public persona subcommands.
- Given the canonical public CLI surface manifest, every public item is enforced on an assigned help surface by automated tests.
- Given a future regression that removes any assigned public item from its help surface, tests fail without requiring a giant textual snapshot.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Top-level help stays short and grouped | `uv run python -m asky --help` + `uv run pytest tests/asky/cli/test_cli.py -q -n0` |
| Top-level help links persona help | `uv run python -m asky --help | rg "asky persona --help"` |
| Top-level help exposes `--continue-chat` | `uv run python -m asky --help | rg -- "--continue-chat"` |
| Top-level help exposes `--reply` | `uv run python -m asky --help | rg -- "--reply"` |
| Top-level help exposes `--elephant-mode` | `uv run python -m asky --help | rg -- "--elephant-mode"` |
| Grouped session help includes delete | `uv run python -m asky session --help | rg "session delete"` |
| Local CLI `--help-all` includes plugin flags | `uv run python -m asky --help-all | rg -- "--sendmail|--subject|--push-data|--browser|--daemon"` |
| Direct `parse_args()` `--help-all` includes plugin flags | direct-wrapper smoke script from Checkpoint 2 |
| Every public top-level flag is covered | discoverability tests cross-checked with `PUBLIC_TOP_LEVEL_FLAGS` |
| Every public plugin flag is covered | discoverability tests cross-checked with `PLUGIN_FLAGS` |
| Every persona subcommand is covered | discoverability tests cross-checked with `PERSONA_SUBCOMMANDS` |
| Every grouped command is covered | discoverability tests cross-checked with `GROUPED_COMMANDS` |
| Full regression remains green | `uv run pytest -q` |

## Assumptions And Defaults

- This is a restart from the clean baseline `6387e1a9fb8edc0951fcd32a3418dbde71f587a3`.
- The previous failed implementation is not being preserved; this plan is intended to be the single fresh handoff.
- The public CLI surface manifest in `tests/integration/cli_recorded/cli_surface.py` remains the source of truth for what is public.
- `prompts list` may remain discoverable through top-level short help unless a dedicated grouped `prompts --help` surface is added in the same handoff.
- The preferred bootstrap design is narrow plugin bootstrap only when the invocation needs plugin-contributed help/flags, not blanket bootstrap for every parser call.

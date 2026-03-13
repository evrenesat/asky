# RALF Handoff Plan: Persona Milestone 1 Follow-Up Fixes

## Summary

This follow-up handoff fixes the authored-book milestone implementation already sitting in the dirty worktree. It does not re-scope the milestone. It closes the review gaps that currently violate the original handoff contract:

- `ingest-book` must not overwrite a completed book identity,
- resumable jobs must still go through a mandatory editable preflight,
- metadata lookup must expose ambiguity instead of silently defaulting to the first candidate,
- extraction output must be validated strictly and persisted with warnings and stage timings,
- inspection commands must use reusable backend services and expose the fields promised by the milestone,
- documentation must reach parity with the actually shipped behavior.

This fix plan supplements, and does not replace, [persona-milestone1-authored-book-ingestion-ralf.md](/Users/evren/.codex/worktrees/4f90/asky/plans/persona-milestone1-authored-book-ingestion-ralf.md).

## Git Tracking

- Plan Branch: `codex/persona-roadmap-v1`
- Pre-Handoff Base HEAD: `6387e1a9fb8edc0951fcd32a3418dbde71f587a3`
- Last Reviewed HEAD: `dee95d45846f177aca973fd4ffdfd46dae9ee025`
- Review Log:
  - 2026-03-13: reviewed `6387e1a9fb8edc0951fcd32a3418dbde71f587a3..dee95d45846f177aca973fd4ffdfd46dae9ee025`, outcome `approved+squashed`

## Done Means

- `asky persona ingest-book PERSONA BOOK_PATH` refuses to replace a completed authored book even if the user edits metadata during preflight; replacement is only possible through `reingest-book`.
- The duplicate/replacement guard is enforced in reusable backend services, not only in CLI prompts.
- Resuming an unfinished ingestion job still opens a mandatory editable preflight with the persisted metadata and targets preloaded, and the user must confirm before extraction continues.
- Metadata lookup returns a reusable candidate model with ranking/confidence or ambiguity markers plus an explicit manual-entry path. The CLI renders that data, but does not invent matching logic on its own.
- Topic discovery and viewpoint extraction reject malformed model payloads via explicit structural validation and persist warnings instead of silently synthesizing defaults.
- Persisted authored-book reports include metadata, requested targets, actual counts, warnings, and per-stage timings.
- `asky persona books PERSONA` includes `last_ingested_at`.
- `asky persona book-report PERSONA BOOK_KEY` renders metadata, targets, counts, warnings, and stage timings from persisted artifacts.
- `asky persona viewpoints PERSONA` uses a backend query surface instead of open-coding storage reads in the CLI layer.
- `src/asky/cli/persona_commands.py` is reduced to prompt/rendering code plus calls into reusable services that can be reused later by the web UI.
- The authored-book backend remains free of CLI-only imports.
- Docs and affected subdirectory `AGENTS.md` files are updated for the actual shipped behavior.
- `uv run pytest -q` passes at the end.

## Critical Invariants

- Duplicate-completed-book protection must be enforced by backend identity checks, not only by CLI branching.
- `ingest-book` and `reingest-book` must use different backend entrypoints or explicit mode flags with different overwrite policies.
- A resumable unfinished job must never skip the editable preflight step.
- Metadata ambiguity must remain explicit in the backend result until the user or caller selects a candidate or manual entry.
- Extraction warnings and stage timings must be durable artifacts, not console-only messages.
- CLI inspection commands must call reusable service functions and must not directly own authored-book storage traversal logic.
- No new third-party dependency may be added for schema validation or metadata lookup.
- Existing schema-v1 persona reads/imports must remain intact.

## Forbidden Implementations

- Do not fix duplicate protection only in `persona_commands.py`.
- Do not keep the current “first candidate wins” behavior by merely renaming it as a default.
- Do not resume a job directly from `resumable_job_id` without showing the editable preflight.
- Do not keep regex-extracted JSON plus fallback defaults as the acceptance path for model output.
- Do not leave `books`, `book-report`, or `viewpoints` with storage/business logic embedded in the CLI file.
- Do not add a new package dependency such as `jsonschema` just to validate model payloads.
- Do not update docs to describe GUI behavior or milestone 2 runtime behavior.
- Do not modify the root `AGENTS.md`.

## Checkpoints

### [x] Checkpoint 1: Harden Backend Contracts And Identity Guards

**Goal:**

- Move authored-book decision logic into reusable backend services and enforce duplicate/replacement rules below the CLI layer.

**Context Bootstrapping:**

- Run these commands before editing:
- `pwd`
- `git branch --show-current`
- `git rev-parse HEAD`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/cli/AGENTS.md`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_types.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_lookup.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/storage.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create: `src/asky/plugins/manual_persona_creator/book_service.py`
- May modify: `src/asky/plugins/manual_persona_creator/book_types.py`, `src/asky/plugins/manual_persona_creator/book_lookup.py`, `src/asky/plugins/manual_persona_creator/book_ingestion.py`, `src/asky/plugins/manual_persona_creator/storage.py`
- May create/modify tests: `tests/asky/plugins/manual_persona_creator/test_book_service.py`, `tests/asky/plugins/manual_persona_creator/test_book_lookup.py`, `tests/asky/plugins/manual_persona_creator/test_book_ingestion.py`
- Must not touch: `src/asky/core/**`, `src/asky/api/**`, `src/asky/plugins/persona_manager/plugin.py`, `docs/**`
- Constraints:
- backend modules must stay CLI-agnostic
- duplicate checks must run after final metadata is known
- `reingest-book` must require an expected `book_key`

**Steps:**

- [x] Expand `book_types.py` with reusable DTOs for:
- ranked metadata candidates with confidence or ambiguity markers
- explicit manual metadata draft payload
- resumable preflight payload with persisted metadata/targets
- inspection rows for `books` and `book-report`
- duplicate/replacement error types or result enums
- [x] Add `book_service.py` as the UI-agnostic orchestration layer with explicit entrypoints for:
- preparing preflight data
- confirming or resuming an ingestion request
- listing authored books
- loading one authored-book report
- querying authored viewpoints
- [x] Rework `run_preflight()` and related helpers so they return ranked candidate data instead of a raw `List[BookMetadata]`.
- [x] Add a backend identity guard that:
- computes the canonical `book_key` from the final metadata
- blocks `ingest-book` when that key already exists as a completed book
- allows `reingest-book` only when the final identity matches the expected `book_key`
- [x] Make job creation go through the service layer so the overwrite policy is enforced before `job.toml` is written.
- [x] Make materialization fail fast if an `ingest-book` path somehow reaches an existing completed `book_key`.
- [x] Add tests that prove:
- manual metadata edits cannot bypass duplicate protection
- `ingest-book` and `reingest-book` diverge correctly on the same final `book_key`
- resumable-job detection still works after the service-layer refactor

**Dependencies:**

- Depends on the existing dirty implementation only.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_service.py tests/asky/plugins/manual_persona_creator/test_book_lookup.py tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/persona_manager/test_authored_book_import.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- `ingest-book` cannot replace a completed book identity through manual metadata edits.
- A git commit is created with message: `persona: harden authored-book identity and service contracts`

**Stop and Escalate If:**

- Preserving the current storage layout would make backend duplicate protection impossible without changing exported artifact identities.
- The service-layer refactor would require changing persona runtime plugin hooks in this checkpoint.

### [x] Checkpoint 2: Strict Validation, Warnings, And Stage Timings

**Goal:**

- Replace permissive extraction parsing with strict structural validation and persist the missing report details required by the milestone.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_prompts.py`
- `sed -n '1,360p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_types.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/tests/asky/plugins/manual_persona_creator/test_book_ingestion.py`

**Scope & Blast Radius:**

- May modify: `src/asky/plugins/manual_persona_creator/book_prompts.py`, `src/asky/plugins/manual_persona_creator/book_ingestion.py`, `src/asky/plugins/manual_persona_creator/book_types.py`, `src/asky/plugins/manual_persona_creator/book_service.py`
- May create/modify tests: `tests/asky/plugins/manual_persona_creator/test_book_ingestion.py`, `tests/asky/plugins/manual_persona_creator/test_book_service.py`
- Must not touch: `src/asky/cli/**`, `src/asky/core/**`, `docs/**`
- Constraints:
- no new validation dependency
- malformed output must create warnings or errors, not synthetic defaults
- persisted reports must be sufficient for the inspection commands

**Steps:**

- [x] Add explicit validator helpers for:
- discovered topic payloads
- extracted viewpoint payloads
- allowed `stance_label` values
- evidence list size and shape
- [x] Update prompts so the expected JSON structure is concrete and matches the validator contract exactly.
- [x] Replace regex-plus-default parsing with:
- structured extraction of the JSON body
- validation against the local schema helpers
- warning accumulation when a topic extraction fails or returns invalid output
- [x] Persist per-stage timings in the job/report model for:
- `read_source`
- `summarize_sections`
- `discover_topics`
- `extract_viewpoints`
- `materialize_book`
- `project_compat_chunks`
- [x] Extend `AuthoredBookReport` and report serialization so it includes:
- confirmed metadata
- requested targets
- actual topic/viewpoint counts
- warnings
- stage timings
- ingestion timestamps
- [x] Ensure invalid topic/viewpoint outputs do not silently become `"Unknown claim"` or default stance values.
- [x] Add tests that cover:
- invalid topic JSON
- invalid viewpoint JSON
- invalid stance label
- missing evidence fields
- warning persistence in `report.json`
- stage timing persistence in `report.json`

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/plugins/manual_persona_creator/test_book_service.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Persisted reports include warnings and per-stage timings, and invalid model payloads are not silently accepted.
- A git commit is created with message: `persona: validate authored-book extraction and persist report details`

**Stop and Escalate If:**

- The existing model client cannot reliably return a parsable JSON body without touching shared core model plumbing.
- Stage timing persistence would require changing unrelated report formats outside persona-owned artifacts.

### [x] Checkpoint 3: Refactor CLI To Thin Wrappers And Complete Inspection Output

**Goal:**

- Make the CLI a presentation layer over reusable services and close the remaining user-visible contract gaps.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,360p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/cli/persona_commands.py`
- `sed -n '1800,1925p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/cli/main.py`
- `sed -n '1,320p' /Users/evren/.codex/worktrees/4f90/asky/tests/asky/cli/test_persona_ingestion_commands.py`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_service.py`

**Scope & Blast Radius:**

- May modify: `src/asky/cli/persona_commands.py`, `src/asky/cli/main.py`, `src/asky/plugins/manual_persona_creator/book_service.py`
- May modify tests: `tests/asky/cli/test_persona_ingestion_commands.py`
- May create tests if needed: `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- Must not touch: `src/asky/core/**`, `src/asky/api/**`, `src/asky/plugins/persona_manager/plugin.py`
- Constraints:
- CLI owns prompts/rendering only
- resumable jobs must show editable preflight
- candidate ambiguity must be visible to the user

**Steps:**

- [x] Refactor `handle_persona_ingest_book()` to:
- call a service-layer preflight API
- render all metadata candidates or a manual-entry path explicitly
- let the user choose candidate vs manual entry
- recompute the final backend decision after the user edits metadata and targets
- [x] Refactor the resumable-job flow so resume is a preloaded editable preflight, not a direct jump into `_run_ingestion_job()`.
- [x] Refactor `handle_persona_reingest_book()` to use the service-layer replacement API and preserve the expected `book_key` check below the CLI.
- [x] Replace direct storage traversal in:
- `handle_persona_books()`
- `handle_persona_book_report()`
- `handle_persona_viewpoints()`
- with service-layer reads returning DTOs.
- [x] Extend `books` output to include `last_ingested_at`.
- [x] Extend `book-report` output to show:
- confirmed metadata
- requested targets
- actual counts
- warnings
- stage timings
- [x] Keep `viewpoints --limit` defaulting to `20`, with service-driven filtering and sorting.
- [x] Add CLI tests for:
- ambiguous candidate selection
- manual metadata entry
- duplicate rejection after user edits
- resumable preflight editing
- `books` including `last_ingested_at`
- `book-report` rendering warnings and stage timings

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_persona_ingestion_commands.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_service.py tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The CLI authored-book commands are thin wrappers over reusable services and the promised inspection fields are visible.
- A git commit is created with message: `persona: refactor authored-book CLI onto reusable services`

**Stop and Escalate If:**

- The current parser structure in `main.py` cannot support the revised preflight loop without a larger CLI command-routing change.
- Recorded CLI coverage would require live network or live model calls.

### [x] Checkpoint 4: Documentation Parity And Final Regression

**Goal:**

- Update the docs that this implementation actually changed, then run the full regression suite.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/ARCHITECTURE.md`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/devlog/DEVLOG.md`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/cli/AGENTS.md`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,240p' /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' /Users/evren/.codex/worktrees/4f90/asky/docs/plugins.md`
- `rg -n "persona" /Users/evren/.codex/worktrees/4f90/asky/README.md /Users/evren/.codex/worktrees/4f90/asky/src/**/README.md`

**Scope & Blast Radius:**

- May modify: `ARCHITECTURE.md`, `devlog/DEVLOG.md`, `src/asky/cli/AGENTS.md`, `src/asky/plugins/manual_persona_creator/AGENTS.md`, `src/asky/plugins/persona_manager/AGENTS.md`, `docs/plugins.md`
- May modify `README.md` or affected subdirectory `README.md` files only if an already relevant persona section exists
- Must not touch: root `AGENTS.md`, docs for future GUI/runtime behavior
- Constraints:
- docs must describe shipped behavior only
- README remains untouched if no already relevant persona section exists

**Steps:**

- [x] Update `ARCHITECTURE.md` for the reusable authored-book service layer, duplicate-protection boundary, resumable preflight behavior, and inspection/report artifacts.
- [x] Update `devlog/DEVLOG.md` with one factual entry for the authored-book follow-up fixes.
- [x] Update affected subdirectory `AGENTS.md` files so they reflect:
- CLI thin-wrapper expectations
- reusable persona service ownership
- authored-book inspection/report artifact expectations
- [x] Update `docs/plugins.md` so the persona CLI docs match the shipped authored-book behavior.
- [x] Search existing README coverage and update only an already relevant persona section if one exists. Otherwise leave README unchanged and note that no relevant section existed.
- [x] Run the final regression suite.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped checks: `rg -n "ingest-book|reingest-book|books|book-report|viewpoints|last_ingested_at|stage timings" /Users/evren/.codex/worktrees/4f90/asky/ARCHITECTURE.md /Users/evren/.codex/worktrees/4f90/asky/docs/plugins.md`
- Run scoped checks: `rg -n "argparse|rich|Console|Prompt" /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_service.py /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_lookup.py /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py`
- Run final regression: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs describe the fixed authored-book behavior and the full suite is green.
- A git commit is created with message: `docs: document authored-book follow-up fixes`

**Stop and Escalate If:**

- Documentation parity would require describing behavior that did not actually land in the code.
- The full suite regresses and the cause is not attributable to the added persona coverage.

## Behavioral Acceptance Tests

- If persona `arendt` already contains `the-human-condition-1958`, then `asky persona ingest-book arendt /path/to/new-file.epub` must still refuse to proceed when the user manually edits the preflight metadata to the same canonical identity; it must direct the user to `reingest-book`.
- If an unfinished authored-book job exists for the same source fingerprint, `asky persona ingest-book ...` must reopen the editable preflight with the saved metadata and targets instead of jumping straight into extraction.
- If OpenLibrary returns multiple plausible matches, the CLI must show the candidate choices or manual entry path explicitly; it must not silently pre-commit to candidate index `0`.
- If the model returns malformed topic or viewpoint JSON, the ingestion job must record warnings and exclude the invalid payload instead of inventing `"Unknown claim"` or default stances.
- After a successful ingest, `asky persona books arendt` must show each book’s `book_key`, title, year, ISBN, viewpoint count, and `last_ingested_at`.
- After a successful ingest with partial extraction failures, `asky persona book-report arendt <book_key>` must show the requested targets, actual counts, warnings, and per-stage timings from `report.json`.
- The backend modules used for preflight, ingestion, books, reports, and viewpoints must remain callable without importing `argparse`, `rich`, `Console`, or `Prompt`.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| `ingest-book` cannot overwrite a completed identity | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_service.py tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0` |
| Replacement is allowed only through `reingest-book` with matching identity | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_service.py tests/asky/cli/test_persona_ingestion_commands.py -q -n0` |
| Resumable jobs still go through editable preflight | `uv run pytest tests/asky/cli/test_persona_ingestion_commands.py -q -n0` |
| Metadata ambiguity is explicit in backend results | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_lookup.py tests/asky/plugins/manual_persona_creator/test_book_service.py -q -n0` |
| Extraction payloads are validated strictly | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py -q -n0` |
| Warnings and stage timings persist in reports | `uv run pytest tests/asky/plugins/manual_persona_creator/test_book_ingestion.py tests/asky/cli/test_persona_ingestion_commands.py -q -n0` |
| CLI inspection commands are thin wrappers over reusable services | `rg -n "get_book_paths|read_book_metadata|read_job_manifest|json\\.loads\\(book_paths" /Users/evren/.codex/worktrees/4f90/asky/src/asky/cli/persona_commands.py` |
| Backend remains free of CLI-only imports | `rg -n "argparse|rich|Console|Prompt" /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_service.py /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_lookup.py /Users/evren/.codex/worktrees/4f90/asky/src/asky/plugins/manual_persona_creator/book_ingestion.py` |
| Docs reflect shipped authored-book behavior only | `rg -n "ingest-book|reingest-book|books|book-report|viewpoints|last_ingested_at" /Users/evren/.codex/worktrees/4f90/asky/ARCHITECTURE.md /Users/evren/.codex/worktrees/4f90/asky/docs/plugins.md` |
| Final regression remains green | `uv run pytest -q` |

## Assumptions And Defaults

- This fix plan targets the current dirty authored-book implementation and assumes no handoff commits have been created yet.
- The fix work stays within milestone 1. It does not add biographies, web scraping, YouTube ingestion, multilingual diarization, graph storage, or milestone 2 runtime answering.
- The reusable service layer may be introduced as a new module if that is the cleanest way to decouple CLI presentation from authored-book business logic.
- Local schema validation should use small local helper functions or dataclass checks, not a new validation dependency.
- If README has no already relevant persona section, README remains unchanged.
- This plan does not update the original handoff plan’s `Git Tracking`; it is a supplemental follow-up plan for the current branch state.

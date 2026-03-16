# Persona UI Creation And Shared Offline Docs RALF

## Summary

Add the missing persona-from-scratch browser workflow on top of the existing review/admin console.

This handoff is intentionally split into three product milestones that map to independent implementation checkpoints:

1. documentation groundwork first,
2. service-first offline persona creation second,
3. browser creation UX third.

The shipped end state must let a new user start from `/personas`, create a persona with:

- a canonical persona name,
- an optional description,
- a non-empty behavior prompt,
- at least one initial offline source,

and finish with a created persona plus queued ingestion jobs for the initial sources.

The same offline markdown documentation must be the single source of truth for:

- persona creation help in the browser,
- persona documentation shown from the CLI,
- user-facing repo docs updates that reference this workflow.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `8ada7e4d5b7a6512192bad1c53fa47bd4feff3ab`
- Last Reviewed HEAD: `none`
- Review Log:
  - None yet.

## Done Means

- A packaged offline persona-doc catalog exists inside the persona plugin package and is loaded without network access.
- `asky persona docs` lists available persona documentation topics, and `asky persona docs <topic>` renders the full markdown topic in the terminal.
- The browser admin console exposes a dedicated persona-creation flow from `/personas` that requires a valid persona name, a non-empty behavior prompt, and at least one staged offline source before submit is allowed.
- Initial offline sources supported in the creation flow are:
  - authored books via the existing authored-book preflight/identity rules,
  - manual offline source kinds via the existing milestone-3 source-ingestion rules for `biography`, `autobiography`, `interview`, `article`, `essay`, `speech`, `notes`, and `posts`.
- Submitting the browser creation flow creates the persona shell, prepares initial ingestion jobs, enqueues them on the existing `JobQueue`, and returns the user to a stable browser surface.
- Persona detail pages read and show the real `behavior_prompt.md` content rather than pretending prompt text lives in `metadata.toml`.
- Existing CLI persona creation and existing persona review/admin flows keep working.
- Docs and agent guidance are updated to the shipped behavior only.

## Critical Invariants

- The single source of truth for the new creation/help documentation is packaged local markdown under the persona plugin package. CLI and web must load the same files, not parallel prose copies.
- No help surface in this handoff may depend on GitHub URLs, remote fetches, or browser connectivity.
- Persona names remain the current canonical storage/mention identifier and must continue to satisfy `^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$`. This handoff does not introduce a separate display-name/slug model.
- Browser-side offline intake remains server-local-path based. Do not add upload support, temp-file staging, or browser file persistence in this handoff.
- Browser creation must require at least one initial source before final submit. A shell-only create path in the browser is explicitly out of scope.
- Authored-book creation must preserve the existing preflight, duplicate detection, resumable-job reuse, and identity-guard rules.
- Manual-source creation must preserve the existing `PersonaSourceKind` review semantics. `web_page` is not a browser-create offline source kind.
- The browser remains admin/review only. No browser chat, browser persona answering, or browser runtime inspection is added here.
- No new dependencies may be added.

## Forbidden Implementations

- Do not hardcode duplicate help strings in CLI handlers and NiceGUI pages while also storing “real” docs elsewhere.
- Do not load persona help from top-level `docs/` paths directly at runtime if that would break installed-package/offline usage.
- Do not auto-create a browser persona shell before validating the persona name, non-empty prompt, and presence of at least one staged source.
- Do not bypass `book_service.py` or `source_service.py` by writing authored-book or source job artifacts directly from the page layer.
- Do not silently turn authored-book entries into generic source-ingestion jobs or generic sources into authored-book jobs.
- Do not invent browser uploads, drag-and-drop ingestion, or hidden temp directories outside the existing repo rules.
- Do not keep reading prompt text from `metadata.toml` or add duplicate prompt storage there.
- Do not describe a broader persona-doc backfill or a browser editing surface as implemented if the code only covers creation.
- Do not update the root `AGENTS.md`.

## Checkpoints

### [ ] Checkpoint 1: Packaged Persona Docs Catalog And CLI Docs Surface

**Goal:**

- Before: persona help is scattered across `docs/plugins.md`, `asky persona --help`, and inline page text, with no packaged single-source offline topic catalog.
- After: packaged persona markdown topics exist under the plugin package, and the CLI can list/show those topics with no network dependency.

**Context Bootstrapping:**

- Run these commands before editing:
- `ssh evren@orb`
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,260p' AGENTS.md`
- `sed -n '1,260p' ARCHITECTURE.md`
- `sed -n '1,220p' devlog/DEVLOG.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1580,1685p' src/asky/cli/main.py`
- `sed -n '720,780p' src/asky/cli/persona_commands.py`
- `sed -n '1,220p' tests/integration/cli_recorded/cli_surface.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/plugins/manual_persona_creator/feature_docs.py`
- `src/asky/plugins/manual_persona_creator/docs/create_persona.md`
- `src/asky/plugins/manual_persona_creator/docs/authored_book.md`
- `src/asky/plugins/manual_persona_creator/docs/manual_source.md`
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- `tests/asky/plugins/manual_persona_creator/test_feature_docs.py`
- `tests/integration/cli_recorded/cli_surface.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `tests/asky/cli/test_help_discoverability.py`
- Must not touch:
- `src/asky/plugins/gui_server/**`
- `src/asky/plugins/manual_persona_creator/gui_service.py`
- `src/asky/plugins/manual_persona_creator/storage.py`
- Constraints:
- Runtime source-of-truth docs must live under `src/asky/plugins/manual_persona_creator/docs/`.
- Use plain markdown bodies with TOML front matter parsed by local code. Do not add a frontmatter dependency.
- Lock the topic ids to exactly:
- `create-persona`
- `authored-book`
- `manual-source`
- Lock the CLI surface to exactly:
- `asky persona docs`
- `asky persona docs <topic>`
- `asky persona docs` with no topic lists topics and summaries.
- `asky persona docs <topic>` renders the full body with `rich.markdown.Markdown`.

**Steps:**

- [ ] Step 1: Add `feature_docs.py` with typed topic/field models and a loader that:
- reads TOML front matter from the packaged markdown files,
- strips front matter from the markdown body,
- exposes topic metadata, field summaries, and the rendered markdown body,
- raises a clear error for unknown topic ids.
- [ ] Step 2: Create the three packaged markdown topics with front matter and bodies that cover:
- `create-persona`: overall workflow, persona name, description, behavior prompt, required initial sources,
- `authored-book`: supported authored-book purpose, server-local path requirement, preflight metadata, extraction targets, resumable/duplicate behavior,
- `manual-source`: supported offline source kinds, review implications, path semantics, when to choose each kind.
- [ ] Step 3: Extend the persona CLI parser with an immediate `docs` subcommand:
- `asky persona docs` lists topics,
- `asky persona docs create-persona` shows the full topic,
- unknown topics fail with actionable guidance that includes the valid topic ids.
- [ ] Step 4: Keep the existing `persona create --prompt <file>` flow unchanged in this checkpoint.
- [ ] Step 5: Update the CLI surface manifest and discoverability tests to include `persona docs`.

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_feature_docs.py tests/asky/cli/test_help_discoverability.py -q -n0`
- Run integration coverage: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression checks: `uv run pytest tests/asky/cli/test_persona_ingestion_commands.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- `asky persona docs` lists the three locked topic ids with one-line summaries.
- `asky persona docs create-persona` prints the full packaged markdown topic in the terminal.
- A git commit is created with message: `persona: add shared offline docs catalog`

**Stop and Escalate If:**

- The implementation still depends on reading docs from unpackaged top-level paths at runtime.
- The implementation start still has unrelated dirty daemon/tray work in the tree after the user said it would be removed.

### [ ] Checkpoint 2: UI-Agnostic Persona Creation Service With Initial Source Specs

**Goal:**

- Before: the browser can only queue work against already-existing personas, and persona detail does not expose the real prompt content.
- After: a reusable backend service can validate and create a persona plus its initial queued-source specs, and GUI DTOs expose the real behavior prompt.

**Context Bootstrapping:**

- Run these commands before editing:
- `ssh evren@orb`
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/storage.py`
- `sed -n '1,280p' src/asky/plugins/manual_persona_creator/gui_service.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/book_service.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/source_service.py`
- `sed -n '1,200p' src/asky/plugins/manual_persona_creator/source_types.py`
- `sed -n '1,220p' tests/asky/plugins/manual_persona_creator/test_persona_gui_service.py`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/plugins/manual_persona_creator/creation_service.py`
- `src/asky/plugins/manual_persona_creator/gui_service.py`
- `src/asky/plugins/manual_persona_creator/storage.py`
- `tests/asky/plugins/manual_persona_creator/test_creation_service.py`
- `tests/asky/plugins/manual_persona_creator/test_persona_gui_service.py`
- Must not touch:
- `src/asky/plugins/gui_server/**`
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- Constraints:
- New service must stay UI-agnostic and not import NiceGUI or `JobQueue`.
- The browser-create service must support only new-persona creation, not editing existing personas.
- Lock the staged source spec kinds to:
- `authored_book`
- `manual_source`
- Lock the manual-source kind picker values to:
- `biography`
- `autobiography`
- `interview`
- `article`
- `essay`
- `speech`
- `notes`
- `posts`
- No `web_page` staging in this flow.
- Prompt text remains stored only in `behavior_prompt.md`.

**Steps:**

- [ ] Step 1: Add `creation_service.py` with typed request/result DTOs for:
- persona basics,
- authored-book staged specs,
- manual-source staged specs,
- created job specs returned to the caller for later queue enqueue.
- [ ] Step 2: Enforce service-level validation:
- persona name uses the existing regex,
- description remains optional,
- behavior prompt must be non-empty after trim,
- at least one staged source is required,
- authored-book specs must carry the preflighted metadata/targets and optional resumable job id,
- manual-source specs must use one of the locked non-web `PersonaSourceKind` values.
- [ ] Step 3: Implement the create flow as:
- create the persona shell with `create_persona(...)`,
- create authored-book job manifests by reusing the existing authored-book service path,
- create manual-source job manifests by reusing the existing milestone-3 source-job path,
- return a list of queueable job specs that the page layer can enqueue on the existing `JobQueue`.
- [ ] Step 4: If any job-manifest preparation fails after the new persona shell was created, roll back the newly created persona root inside the service so the browser does not leave behind a half-created shell.
- [ ] Step 5: Extend `gui_service.get_persona_detail(...)` to read `behavior_prompt.md` via the existing prompt reader and include the real prompt text in the returned DTO.
- [ ] Step 6: Add small helper accessors in `gui_service.py` only when they make page rendering thinner, not to duplicate service logic.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_creation_service.py tests/asky/plugins/manual_persona_creator/test_persona_gui_service.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_persona_ingestion_commands.py tests/asky/cli/test_persona_source_commands.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The service can create a persona plus initial staged job manifests without touching NiceGUI or queue internals.
- Persona detail DTOs include the actual behavior prompt body.
- A git commit is created with message: `persona: add creation service for initial offline sources`

**Stop and Escalate If:**

- Rolling back a failed new-persona creation cannot be implemented safely without changing the on-disk persona layout.
- The create flow would require new source semantics beyond the locked authored-book and manual-source variants.

### [ ] Checkpoint 3: Browser Persona Creation Page With Shared Field Help

**Goal:**

- Before: `/personas` only lists existing personas and lets the user add books, sources, or URLs after a persona already exists.
- After: `/personas` links to a dedicated creation page that stages at least one offline source, reuses the packaged docs for field help, and creates/queues the persona workflow.

**Context Bootstrapping:**

- Run these commands before editing:
- `ssh evren@orb`
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/gui_server/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/gui_server/pages/AGENTS.md`
- `sed -n '1,420p' src/asky/plugins/gui_server/pages/personas.py`
- `sed -n '1,320p' src/asky/plugins/manual_persona_creator/gui_service.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/creation_service.py`
- `sed -n '1,240p' tests/asky/plugins/manual_persona_creator/test_gui_book_flow.py`
- `sed -n '1,240p' tests/asky/plugins/manual_persona_creator/test_gui_book_resume_flow.py`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/plugins/gui_server/pages/personas.py`
- `src/asky/plugins/manual_persona_creator/gui_service.py`
- `tests/asky/plugins/manual_persona_creator/test_gui_creation_flow.py`
- `tests/asky/plugins/manual_persona_creator/test_gui_book_flow.py`
- `tests/asky/plugins/manual_persona_creator/test_gui_book_resume_flow.py`
- `tests/asky/plugins/gui_server/test_gui_extension_registration.py`
- Must not touch:
- `src/asky/plugins/gui_server/server.py`
- `src/asky/plugins/persona_manager/**`
- `src/asky/core/**`
- Constraints:
- Add a real route at `/personas/new`; do not hide the full workflow inside a giant modal on `/personas`.
- `/personas` must add a primary “Create Persona” action that navigates to `/personas/new`.
- The new page must use existing NiceGUI layout primitives and the shared `page_layout(...)`.
- Help UX is locked to:
- short inline field summaries pulled from the packaged docs metadata,
- full-topic markdown shown from the same packaged docs inside browser-visible help affordances,
- no separate remote docs browser.
- Authoring a new persona must stage sources first and only create the persona on final submit.
- Offline source staging remains path-based and server-local.

**Steps:**

- [ ] Step 1: Register a new persona creation page at `/personas/new` from the existing persona page registration helper.
- [ ] Step 2: Build the page with three explicit sections:
- Basics: persona name, optional description, behavior prompt textarea,
- Initial Sources: staged authored-book/manual-source entries with add/remove controls,
- Review & Submit: summary of the staged basics and sources plus the final create action.
- [ ] Step 3: Wire inline help from the packaged docs:
- show short summaries under `persona_name`, `behavior_prompt`, and source-related controls,
- add browser-visible full-topic help actions for `create-persona`, `authored-book`, and `manual-source`.
- [ ] Step 4: Rework authored-book browser staging so the page reuses the existing preflight logic but does not create or enqueue the job immediately:
- the add-book flow runs preflight,
- stores the staged authored-book spec in page state,
- preserves resumable job ids when preflight reports them,
- continues to block duplicates using the existing authored-book identity rules.
- [ ] Step 5: Rework manual-source staging so the page:
- collects path and one locked manual source kind,
- validates the choice with the existing source-preflight/service rules,
- stages the normalized manual-source spec without creating the job yet.
- [ ] Step 6: On final submit:
- call the new creation service,
- enqueue each returned job spec on the existing queue using the existing job types `authored_book_ingest` and `source_ingest`,
- navigate to `/personas/{name}` after enqueue succeeds,
- show a clear error and stay on the page if validation or enqueue fails.
- [ ] Step 7: Update persona detail rendering to show the actual prompt text from the DTO returned by `get_persona_detail(...)`.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_creation_flow.py tests/asky/plugins/manual_persona_creator/test_gui_book_flow.py tests/asky/plugins/manual_persona_creator/test_gui_book_resume_flow.py -q -n0`
- Run GUI non-regression tests: `uv run pytest tests/asky/plugins/gui_server/test_gui_extension_registration.py tests/asky/plugins/manual_persona_creator/test_persona_gui_service.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A new user can reach `/personas/new`, cannot submit without a valid name, non-empty prompt, and at least one staged source, and is redirected to the new persona after successful create+enqueue.
- The persona detail page shows the real prompt body.
- A git commit is created with message: `persona: add browser creation flow for offline personas`

**Stop and Escalate If:**

- The new page would require browser upload semantics or a second background worker.
- Reusing authored-book preflight for staged creation would force implicit duplicate bypass or resumable-job loss.

### [ ] Checkpoint 4: Documentation Parity, Agent Guidance, And Full Regression

**Goal:**

- Before: repo docs describe persona creation as CLI-only and do not document the new packaged docs surface.
- After: architecture, user docs, and agent guidance all match the shipped packaged-docs and browser-create behavior.

**Context Bootstrapping:**

- Run these commands before editing:
- `ssh evren@orb`
- `cd /home/evren/code/asky`
- `sed -n '1,360p' ARCHITECTURE.md`
- `sed -n '1,260p' devlog/DEVLOG.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/gui_server/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/gui_server/pages/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' docs/plugins.md`
- `sed -n '1,220p' docs/web_admin.md`
- `rg -n "persona create|CLI-first|Web Admin|persona docs|browser" README.md docs ARCHITECTURE.md src/asky/*/AGENTS.md src/asky/plugins/*/AGENTS.md`

**Scope & Blast Radius:**

- May create/modify:
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `docs/plugins.md`
- `docs/web_admin.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/plugins/gui_server/AGENTS.md`
- `src/asky/plugins/gui_server/pages/AGENTS.md`
- `README.md` only if an existing relevant line or paragraph becomes factually incomplete after the feature ships
- Must not touch:
- root `AGENTS.md`
- docs that would claim browser uploads, browser chat, or broader persona-doc backfill exist
- Constraints:
- Docs must describe the packaged-docs surface as persona-scoped and offline.
- Docs must describe browser creation as server-local-path based and queue-backed.
- Docs must not claim the browser can create a shell without an initial source.
- If README is touched, only update an existing relevant section. Do not add a new README section.

**Steps:**

- [ ] Step 1: Update `ARCHITECTURE.md` for:
- the packaged persona docs catalog,
- the `asky persona docs` CLI surface,
- the new browser create route and staged-source flow,
- the corrected prompt-detail DTO behavior.
- [ ] Step 2: Update user docs in `docs/plugins.md` and `docs/web_admin.md` to describe:
- `asky persona docs [topic]`,
- `/personas/new`,
- required initial offline sources,
- supported manual source kinds,
- server-local path limitation,
- no browser upload/chat scope.
- [ ] Step 3: Update the affected `AGENTS.md` files so future agents know:
- persona docs are packaged and single-source,
- persona browser creation is route-based and service-first,
- browser create requires at least one staged source,
- prompt text lives in `behavior_prompt.md`, not metadata.
- [ ] Step 4: Run the relevant persona/browser test lanes and then the full suite.
- [ ] Step 5: Compare final full-suite runtime to the clean pre-implementation baseline captured at implementation start, and call out any disproportionate increase in `devlog/DEVLOG.md` if present.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator tests/asky/plugins/gui_server tests/asky/cli/test_help_discoverability.py -q -n0`
- Run CLI integration coverage: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run full regression: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs and agent guidance describe only the shipped packaged-docs and browser-create behavior.
- A git commit is created with message: `docs: describe persona browser creation and offline docs`

**Stop and Escalate If:**

- The clean pre-implementation baseline still contains unrelated failures or unrelated dirty work that make the final comparison ambiguous.
- Any doc update would need to claim upload support, browser chat, or unimplemented persona-doc coverage.

## Behavioral Acceptance Tests

- Given `asky persona docs` with no topic argument, the CLI prints the three packaged topic ids with titles and one-line summaries.
- Given `asky persona docs create-persona`, the CLI prints the packaged markdown topic using terminal markdown rendering and does not touch the network.
- Given `/personas/new`, leaving `persona_name` blank, leaving the prompt blank, or staging zero sources prevents final submission and shows actionable validation feedback.
- Given `/personas/new` and a staged authored-book entry, the page preserves the existing authored-book duplicate/resumable logic instead of creating a second job blindly.
- Given `/personas/new` and a staged manual-source entry, the page only accepts the locked offline source kinds and does not offer `web_page`.
- Given `/personas/new` with one authored book and one manual source, successful submit creates the persona shell once and enqueues one `authored_book_ingest` job plus one `source_ingest` job.
- Given a newly created persona, `/personas/{name}` shows the real behavior prompt body from `behavior_prompt.md`.
- Given any browser help action on the creation page, the short field summary and the longer full topic both come from the same packaged markdown topic metadata/body.
- Given the shipped feature set, the browser still does not offer uploads, browser chat, or shell-only persona creation.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Packaged docs are the runtime source of truth | `uv run pytest tests/asky/plugins/manual_persona_creator/test_feature_docs.py -q -n0` |
| CLI exposes persona docs without network access | `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none' -k docs` |
| Persona help surface tracks new docs command | `uv run pytest tests/asky/cli/test_help_discoverability.py -q -n0` |
| Creation service validates prompt and initial sources | `uv run pytest tests/asky/plugins/manual_persona_creator/test_creation_service.py -q -n0` |
| Persona detail reads real prompt content | `uv run pytest tests/asky/plugins/manual_persona_creator/test_persona_gui_service.py -q -n0` |
| Browser create route enforces required fields and staged sources | `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_creation_flow.py -q -n0` |
| Authored-book staging preserves duplicate/resumable rules | `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_book_flow.py tests/asky/plugins/manual_persona_creator/test_gui_book_resume_flow.py -q -n0` |
| Browser create uses existing queue job types | `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_creation_flow.py -q -n0 -k enqueue` |
| Docs parity matches shipped behavior | `rg -n "persona docs|/personas/new|server-local|upload|browser chat" ARCHITECTURE.md docs/plugins.md docs/web_admin.md src/asky/cli/AGENTS.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/plugins/gui_server/AGENTS.md src/asky/plugins/gui_server/pages/AGENTS.md` |
| Final regression remains acceptable | `uv run pytest -q` |

## Assumptions And Defaults

- The user-confirmed browser workflow is locked to “create plus at least one source”, not shell-only create and not optional-source create.
- The CLI docs surface is locked to `asky persona docs [topic]`, not a new top-level `asky docs` command.
- Initial browser-create source support is locked to authored books plus existing offline manual-source kinds. Web collection intake is not part of the creation wizard.
- Packaged markdown under the persona plugin package is the runtime source of truth because top-level `docs/` alone is not a safe installed-package runtime dependency.
- Short field help is sourced from markdown front matter metadata in the same files as the long help body.
- The new browser flow creates the persona only on final submit after staged validation, not at the start of the wizard.
- The browser-create route is `/personas/new`.
- Existing CLI `persona create --prompt <file>` remains supported; this handoff does not redesign it into a source-required flow.
- If implementation starts after the unrelated dirty daemon/tray work has been removed, the implementer must capture a fresh clean full-suite timing baseline before edits and use that for the final runtime comparison.

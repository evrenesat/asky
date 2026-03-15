# RALF Handoff Plan: Persona Milestone 6, Review Console And Web-Based Workflow

## Summary

Milestone 6 adds a daemon-backed, authenticated web admin console for persona workflows on top of the existing `GUIServerPlugin`. The GUI remains daemon-hosted; it does **not** become a standalone app and it does **not** require XMPP specifically. The daemon must continue to support sidecar-only mode, with GUI and transport enablement controlled by config/plugin state.

This handoff must deliver:

- a reusable GUI foundation inside `gui_server` with a shared layout/theme for all pages,
- plugin-isolated GUI extension points so persona plugins own persona behavior,
- a single-process SQLite-backed background job queue in daemon core, using only the needed ideas vendored from Pinion with attribution,
- authenticated admin/review pages for all persona management and review surfaces,
- authenticated intake endpoints for URL submission and browser-scraped text submission that stage the existing review pipeline,
- no browser chat/query UI,
- no per-entry edit/score/remove workflow beyond source/page/book-level review,
- no milestone-5 browser-assisted acquisition implementation beyond extension points and direct intake endpoints.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `807c554d12336559f1e56977760d3b138e7a860a`
- Last Reviewed HEAD: `finalized via accumulated squash on 2026-03-15`
- Review Log:
  - `2026-03-15` reviewed `807c554d12336559f1e56977760d3b138e7a860a..356fc06c502093b75792df79dc34cd490f0c8fa0`, outcome `changes-requested`
  - `2026-03-15` reviewed `356fc06c502093b75792df79dc34cd490f0c8fa0..8cacb99547e70c146c05e521ca7a1762cd90789f`, outcome `changes-requested`
  - `2026-03-15` reviewed `8cacb99547e70c146c05e521ca7a1762cd90789f..1304693df5816f6de7932b1f44410c094a6622db`, outcome `approved`
  - `2026-03-15` finalized full handoff range `807c554d12336559f1e56977760d3b138e7a860a..1304693df5816f6de7932b1f44410c094a6622db`, outcome `approved+squashed`

## Done Means

- Starting the daemon with `gui_server` enabled and `xmpp_daemon` disabled still supports a usable sidecar-only GUI flow.
- `GUIServerPlugin` exposes one reusable authenticated admin shell shared by:
  - `/settings/general`
  - `/plugins`
  - `/jobs`
  - `/sessions`
  - `/personas`
  - nested persona detail/review pages
- Every GUI/API route except login/logout is protected by a single-user password flow:
  - login form + cookie-backed session
  - password from GUI plugin config or env override
  - if auth is enabled but no effective password exists, GUI server refuses to start and reports a clear health error while the daemon continues running
- Persona pages remain plugin-isolated:
  - `gui_server` owns shell/auth/registries/job UI
  - `manual_persona_creator` owns persona catalog, ingestion, review, provenance, and intake surfaces
  - `persona_manager` owns session binding admin surfaces
- Browser admin supports all persona **admin/review** surfaces:
  - persona list/detail
  - create/import/export
  - authored-book submit/report
  - source ingest/review
  - web collection/review
  - provenance inspection
  - session binding load/unload as admin over existing sessions
- Browser admin does **not** ship:
  - browser chat/query UI
  - per-entry score/edit/remove UI
- Long-running persona actions run through a single in-process SQLite queue with visible job state. No second worker process is introduced.
- URL intake and scraped-content intake both stage standard review artifacts instead of bypassing review:
  - URL intake starts a one-URL review flow
  - scraped-content intake stages a review-ready page with preview extraction and provenance marking it as browser-provided content
- Threshold/tuning UI stays operational only:
  - book extraction targets
  - source kind selection
  - web target results
  - web approve-as authored/about
  - no duplicate-similarity or runtime retrieval tuning page in this milestone
- Final regression passes in the VM and docs match implemented behavior only.
- Final acceptance target:
  - `uv run pytest -q` passes in the VM
  - runtime remains proportionate to the added GUI/queue coverage
  - baseline for comparison is `1587 passed in 20.69s` with shell elapsed `21.156`

## Critical Invariants

- Daemon lifecycle remains transport-agnostic. GUI must not depend on XMPP being the active or only transport.
- `GUIServerPlugin` remains the reusable GUI host. Persona plugins must register pages/endpoints/jobs through GUI extension contracts, not by embedding persona behavior into `gui_server`.
- GUI page code must call service-layer functions. It must not read/write persona bundle files directly from page handlers.
- All non-login GUI/API routes are authenticated. Missing/invalid auth must not degrade into unauthenticated access.
- The background job layer stays single-process and single-worker-thread for this milestone.
- Vendored queue logic must include explicit source credit to Pinion in the module docstring and must not add Pinion as a dependency.
- URL intake and scraped-content intake must materialize normal review artifacts, not direct approved knowledge.
- Review/admin only: no browser-side persona query runtime and no browser-side answer generation.
- Entry-level editing/scoring/removal stays out of scope. Review granularity remains source/page/book plus session binding.
- GUI defaults remain localhost-oriented. Default bind stays `127.0.0.1` unless explicitly configured otherwise.

## Forbidden Implementations

- Do not add a second worker process, subprocess runner, or external queue service.
- Do not vendor the entire Pinion package tree or wire in its CLI/registry/in-memory backend.
- Do not let `GUIServerPlugin` directly own persona business logic pages that belong in persona plugins.
- Do not call CLI handlers from GUI pages to implement behavior.
- Do not bypass `book_service.py`, `source_service.py`, `web_service.py`, or session-binding services with direct storage mutations from the UI.
- Do not keep the current XMPP-specific tray/server wording that implies GUI requires XMPP.
- Do not silently disable auth or silently start the GUI insecurely when the password is missing.
- Do not add browser chat/query pages, per-entry editing, or runtime retrieval-threshold tuning in this handoff.
- Do not route scraped-content intake straight into approved source bundles or canonical knowledge.
- Do not update the root `AGENTS.md`.
- Do not add a new README section if no existing relevant GUI/persona section already exists.

## Checkpoints

### [x] Checkpoint 1: GUI Foundation, Shared Layout, Auth, And Daemon-Neutral Hosting

**Goal:**

- Turn `GUIServerPlugin` into a reusable authenticated admin host with one shared style/layout shell and no XMPP-specific hosting assumptions.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,260p' ARCHITECTURE.md`
- `sed -n '1,220p' devlog/DEVLOG.md`
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/gui_server/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/gui_server/pages/AGENTS.md`
- `sed -n '1,260p' src/asky/daemon/service.py`
- `sed -n '1,260p' src/asky/plugins/gui_server/plugin.py`
- `sed -n '1,260p' src/asky/plugins/gui_server/server.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/plugins/gui_server/**`
- `src/asky/plugins/hook_types.py`
- `src/asky/daemon/service.py`
- `src/asky/daemon/tray_controller.py`
- `src/asky/data/config/plugins.toml`
- new GUI config template under `src/asky/data/config/plugins/`
- GUI/daemon tests under `tests/asky/plugins/gui_server/` and `tests/asky/daemon/`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- persona plugin business logic outside extension registration seams
- Constraints:
- GUI still starts from daemon lifecycle only
- existing `/settings/general` and `/plugins` pages must move onto the shared shell instead of staying visually separate
- auth covers pages and API routes
- daemon sidecar-only mode must remain valid

**Steps:**

- [ ] Step 1: Add a real GUI plugin config file contract (`plugins/gui_server.toml`) and activate it from bundled `plugins.toml`.
- [ ] Step 2: Add a reusable page shell for all GUI pages with shared navigation, section/card layout, status banners, table styling, form styling, and consistent status badges.
- [ ] Step 3: Introduce GUI extension registration hooks/contexts that let other plugins register:
- authenticated pages with nav metadata
- authenticated API routes
- optional GUI-owned job handlers/status formatters
- [ ] Step 4: Add server-wide form login + cookie session auth:
- `/login` and `/logout`
- password from config with env override
- no remember-me or token mode in this milestone
- if no effective password exists, server start fails with a clear health error and no insecure fallback
- [ ] Step 5: Remove XMPP-specific GUI assumptions from tray/server behavior and wording:
- no “Start the XMPP client first to use the Web GUI” message
- “Open Settings” targets the login page when auth is enabled
- sidecar-only daemon startup remains supported
- [ ] Step 6: Add a generic `/jobs` placeholder page in the shared shell even before persona jobs are wired, so later checkpoints do not invent a second layout.

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/gui_server/test_gui_server_plugin.py tests/asky/plugins/gui_server/test_gui_server_auth.py tests/asky/daemon/test_tray_controller.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/gui_server -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The GUI server presents one shared admin shell and requires login for all protected routes.
- Daemon sidecar-only startup remains valid and GUI wording no longer implies XMPP is mandatory.
- A git commit is created with message: `gui: add authenticated daemon-neutral admin shell`

**Stop and Escalate If:**

- NiceGUI cannot support the required auth/session guard without a new dependency.
- Achieving daemon-neutral hosting would require re-coupling `DaemonService` to a specific transport.

### [x] Checkpoint 2: Daemon-Core SQLite Job Queue From Minimal Pinion Subset

**Goal:**

- Add a reusable single-process SQLite queue/worker in daemon core for GUI-submitted workflows.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/daemon/service.py`
- `sed -n '1,260p' src/asky/plugins/hook_types.py`
- `sed -n '1,260p' /home/evren/code/_vendored/Pinion/pinion/sqlite_storage.py`
- `sed -n '1,260p' /home/evren/code/_vendored/Pinion/pinion/worker.py`
- `sed -n '1,220p' /home/evren/code/_vendored/Pinion/LICENSE`

**Scope & Blast Radius:**

- May create/modify:
- `src/asky/daemon/job_queue.py`
- `src/asky/plugins/gui_server/plugin.py`
- `src/asky/plugins/gui_server/server.py`
- `src/asky/plugins/hook_types.py`
- queue tests under `tests/asky/daemon/`
- Must not touch:
- any external dependency manifest
- `_vendored/Pinion/`
- Constraints:
- single module or tightly scoped module pair only
- include attribution to `https://github.com/Nouman64-cat/Pinion` in module docstring
- SQLite backend only
- one in-process worker thread only
- no generic task decorator, no CLI, no in-memory backend

**Steps:**

- [ ] Step 1: Vendor only the SQLite queue, retry, heartbeat, stale reaping, and worker-loop ideas needed for asky into daemon core.
- [ ] Step 2: Define explicit queued job types for milestone-6 persona workflows:
- authored-book ingestion
- source ingestion
- web collection start/continue
- browser content preview extraction/staging
- [ ] Step 3: Make handler registration explicit through GUI extension contracts instead of Pinion-style global task decorators.
- [ ] Step 4: Store queue DB path under GUI-owned config/data defaults while keeping the queue implementation daemon-core reusable.
- [ ] Step 5: Add queue status read APIs for GUI use:
- queued/running/success/failed
- timestamps, attempts, last error
- no cancel/retry UI controls in this milestone
- [ ] Step 6: Use no automatic retry for persona workflow jobs in this milestone; surface failures clearly instead of silently replaying long-running LLM jobs.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/daemon/test_job_queue.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/daemon -q -n0`

**Done When:**

- Verification commands pass cleanly.
- GUI-owned workflows can be queued and observed through one reusable daemon-core SQLite queue with a single worker thread.
- A git commit is created with message: `daemon: add sqlite gui workflow queue`

**Stop and Escalate If:**

- The queue would require a second worker process to keep the GUI responsive.
- Vendoring the needed Pinion behavior cleanly would require pulling in most of the project unchanged.

### [x] Checkpoint 3: Persona GUI Service Adapters And Session Binding Admin Contract

**Goal:**

- Add browser-facing service adapters so persona GUI pages stay above durable services, and define admin-only session binding behavior.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/book_service.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/source_service.py`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/web_service.py`
- `sed -n '1,220p' src/asky/plugins/persona_manager/session_binding.py`
- `sed -n '1,220p' src/asky/storage/__init__.py`

**Scope & Blast Radius:**

- May create/modify:
- browser-facing service modules under `src/asky/plugins/manual_persona_creator/`
- browser-facing service modules under `src/asky/plugins/persona_manager/`
- `src/asky/plugins/manual_persona_creator/web_service.py`
- `src/asky/plugins/persona_manager/session_binding.py` only if helper expansion is required
- tests under `tests/asky/plugins/manual_persona_creator/` and `tests/asky/plugins/persona_manager/`
- Must not touch:
- `src/asky/core/**`
- `src/asky/api/**`
- GUI page code in this checkpoint
- Constraints:
- service adapters return typed/dict DTOs for pages and APIs
- no page handler may call CLI command functions
- load/unload must be modeled as session binding admin over existing sessions, not as browser chat state

**Steps:**

- [ ] Step 1: Add manual-persona GUI service adapters for persona list/detail, create, import, export, book preflight/job submission, source submission/review, web collection/review, provenance detail, and job summaries.
- [ ] Step 2: Keep authored-book and manual-source browser inputs path-based in this milestone:
- browser forms accept server-local paths
- no browser file-upload ingestion for books/sources in this handoff
- [ ] Step 3: Add persona-manager GUI service adapters for session listing and persona bind/unbind against existing persisted sessions.
- [ ] Step 4: Extend web services for direct browser-admin intake:
- `POST /api/personas/{persona_name}/intake/url` starts a one-URL review flow with `target_results=1`
- `POST /api/personas/{persona_name}/intake/content` creates a one-page review-ready staged collection from provided URL/title/content and marks provenance as browser-provided content
- [ ] Step 5: Add any missing typed enums/DTO support needed for the new browser-capture staging path without pretending milestone 5 is implemented.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_service.py tests/asky/plugins/persona_manager/test_gui_session_bindings.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator tests/asky/plugins/persona_manager -q -n0`

**Done When:**

- Verification commands pass cleanly.
- Persona browser pages can use stable service adapters and existing-session binding admin is fully specified without any browser chat UI.
- A git commit is created with message: `persona: add gui service adapters and session admin contract`

**Stop and Escalate If:**

- Supporting browser-admin session binding would require inventing a new browser session model instead of using persisted asky sessions.
- Direct content intake cannot be staged as normal review artifacts without breaking existing web-review invariants.

### [x] Checkpoint 4: Persona Review Console Pages, Shared Styling, And Authenticated Intake Endpoints

**Goal:**

- Ship the actual browser review/admin surfaces on the shared GUI shell, using queued workflows where work is long-running.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/plugins/gui_server/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/persona_manager/AGENTS.md`
- `find src/asky/plugins/gui_server -maxdepth 3 -type f | sort`
- `find src/asky/plugins/manual_persona_creator -maxdepth 3 -type f | sort`
- `find src/asky/plugins/persona_manager -maxdepth 3 -type f | sort`

**Scope & Blast Radius:**

- May create/modify:
- GUI registration code in `src/asky/plugins/gui_server/**`
- persona GUI page modules in `src/asky/plugins/manual_persona_creator/**`
- session admin page modules in `src/asky/plugins/persona_manager/**`
- tests under `tests/asky/plugins/gui_server/`, `tests/asky/plugins/manual_persona_creator/`, and `tests/asky/plugins/persona_manager/`
- Must not touch:
- `src/asky/core/**`
- browser-chat or answer-generation surfaces
- per-entry edit/remove flows
- Constraints:
- every page must use the shared admin shell
- read-only screens may stay synchronous
- long-running actions must queue and surface job status
- threshold/tuning controls stay operational-only

**Steps:**

- [ ] Step 1: Register persona admin pages from the owning plugins, not from `gui_server`:
- `manual_persona_creator` owns `/personas` and persona detail/review pages
- `persona_manager` owns `/sessions`
- [ ] Step 2: Implement persona admin pages with shared styling:
- persona list/detail
- create/import/export
- books list/report/submit
- sources list/report/approve/retract/reject
- web collections/review/page-report/approve/retract/reject
- provenance display using existing durable artifacts and service DTOs
- [ ] Step 3: Implement operational-only controls in the UI:
- book topic/viewpoint targets
- source kind
- web target-results
- web approve-as authored/about
- no duplicate-threshold or runtime-top-k controls
- [ ] Step 4: Queue long-running work and surface it in `/jobs` plus persona detail pages:
- authored-book execution
- source ingestion
- web collection start/continue
- browser content preview staging
- [ ] Step 5: Add authenticated intake endpoints for future browser-extension use, protected by the same session auth as the GUI:
- URL intake returns collection/job identifiers
- scraped-content intake returns collection/page/job identifiers
- no separate API token or HTTP Basic mode in this milestone
- [ ] Step 6: Keep import/export/browser-admin flows within the admin-only scope:
- export offers a browser-initiated download and/or resolved output path
- no browser chat/query UI is added anywhere

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/gui_server/test_persona_gui_pages.py tests/asky/plugins/manual_persona_creator/test_gui_review_console.py tests/asky/plugins/persona_manager/test_gui_session_pages.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/gui_server tests/asky/plugins/manual_persona_creator tests/asky/plugins/persona_manager -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The browser UI covers all agreed admin/review surfaces, every page uses the shared shell, and long-running actions are visible through the queue/job UI.
- A git commit is created with message: `persona: add gui review console and intake endpoints`

**Stop and Escalate If:**

- Implementing the pages would require bypassing service-layer boundaries and mutating persona artifacts directly from UI code.
- Supporting the intake endpoints would require milestone-5 browser automation rather than plain URL/text staging.

### [x] Checkpoint 5: Documentation Parity, Architecture Update, And Final Regression

**Goal:**

- Update docs and agent guidance to match shipped milestone-6 behavior only, then run the full VM regression pass.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,320p' ARCHITECTURE.md`
- `sed -n '1,260p' devlog/DEVLOG.md`
- `sed -n '1,240p' docs/plugins.md`
- `sed -n '1,240p' src/asky/plugins/gui_server/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,220p' src/asky/daemon/AGENTS.md`
- `grep -R -n "gui_server\\|persona\\|web gui\\|browser" README.md docs src | head -n 120`

**Scope & Blast Radius:**

- May modify:
- `ARCHITECTURE.md`
- `devlog/DEVLOG.md`
- `docs/plugins.md`
- `src/asky/plugins/gui_server/AGENTS.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/plugins/persona_manager/AGENTS.md`
- `src/asky/daemon/AGENTS.md`
- `tests/AGENTS.md` or `tests/ARCHITECTURE.md` only if new GUI/queue lane guidance is needed
- Must not touch:
- root `AGENTS.md`
- `README.md` unless an existing directly relevant section already exists and needs a factual update
- docs describing milestone-5 browser automation as if implemented
- Constraints:
- docs must describe auth, queue, sidecar-only daemon support, admin-only browser scope, and direct intake endpoints exactly as shipped

**Steps:**

- [ ] Step 1: Update architecture docs for:
- daemon-core reusable queue
- GUI extension contracts
- shared admin shell/auth
- session binding admin
- browser-capture review staging
- [ ] Step 2: Update plugin docs and affected `AGENTS.md` files so future agents know:
- GUI behavior is authenticated and daemon-hosted
- persona GUI pages live in owning plugins
- service-layer boundaries must be preserved
- [ ] Step 3: Update `devlog/DEVLOG.md` with milestone summary, changed behavior, gotchas, and follow-up notes.
- [ ] Step 4: Run the full suite in the VM and compare against the recorded baseline.

**Dependencies:**

- Depends on Checkpoint 4.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/gui_server tests/asky/daemon tests/asky/plugins/manual_persona_creator tests/asky/plugins/persona_manager -q -n0`
- Run non-regression tests: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Docs describe only the implemented milestone-6 behavior and the full suite passes in the VM.
- A git commit is created with message: `docs: document persona gui review console`

**Stop and Escalate If:**

- The shipped behavior cannot be documented accurately without claiming milestone-5 browser automation exists.
- Full regression exposes a disproportionate runtime increase that cannot be explained by the added GUI/queue tests.

## Behavioral Acceptance Tests

- Given `xmpp_daemon` disabled and `gui_server` enabled, starting the daemon still exposes the GUI login page and usable admin pages after authentication.
- Given no configured GUI password and no password env override, GUI startup fails closed with a clear health error while the daemon process keeps running.
- Given any authenticated page under `/settings/general`, `/plugins`, `/jobs`, `/sessions`, or `/personas`, the page uses the same shared shell, navigation, status styling, and layout primitives.
- Given an authored-book submission from the browser with edited extraction targets, the request returns immediately with a job id, the job appears in `/jobs`, and successful completion produces the same book/report artifacts the CLI path expects.
- Given a source-ingestion submission from the browser, the job stages/approves according to existing source rules and the resulting source bundle is visible on the persona detail page.
- Given URL intake through the authenticated API, the system stages a normal review flow backed by existing web collection artifacts rather than directly approving knowledge.
- Given scraped-content intake through the authenticated API, the system creates a one-page review-ready staged artifact with browser-capture provenance and can later approve/reject it through the existing review UI.
- Given the browser admin is used to bind or unbind a persona to an existing session, the persisted session binding changes and later CLI/XMPP turns observe that binding.
- Given a failed long-running persona job, the job list shows the terminal error state and the persona data remains in a consistent pre-approval state.
- Given any browser interaction in this milestone, no page offers persona chat/query answer generation and no UI offers per-entry edit/remove controls.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| GUI is daemon-hosted but transport-agnostic | `uv run pytest tests/asky/plugins/gui_server/test_gui_server_auth.py tests/asky/daemon/test_tray_controller.py -q -n0` |
| Shared shell/layout is reused across pages | `uv run pytest tests/asky/plugins/gui_server/test_persona_gui_pages.py -q -n0` |
| All protected routes require login | `uv run pytest tests/asky/plugins/gui_server/test_gui_server_auth.py -q -n0` |
| Missing password fails closed | `uv run pytest tests/asky/plugins/gui_server/test_gui_server_auth.py -q -n0 -k missing_password` |
| Queue is vendored minimally with attribution | `rg -n "Nouman64-cat/Pinion|github.com/Nouman64-cat/Pinion" src/asky/daemon/job_queue.py` |
| Queue stays single-process and SQLite-backed | `uv run pytest tests/asky/daemon/test_job_queue.py -q -n0` |
| Persona GUI uses service adapters instead of CLI handlers | `rg -n "handle_persona_|console\\.print|run_cli" src/asky/plugins/gui_server src/asky/plugins/manual_persona_creator src/asky/plugins/persona_manager` |
| Session binding admin uses existing persisted sessions | `uv run pytest tests/asky/plugins/persona_manager/test_gui_session_bindings.py -q -n0` |
| URL/content intake stages review artifacts | `uv run pytest tests/asky/plugins/manual_persona_creator/test_gui_review_console.py -q -n0 -k "intake"` |
| Admin-only scope is preserved | `rg -n "Answer:|Grounding:|Current Context:|chat ui|query ui" src/asky/plugins/gui_server src/asky/plugins/manual_persona_creator src/asky/plugins/persona_manager` |
| Docs updated to shipped behavior only | `rg -n "browser-assisted|milestone 5|no dedicated persona GUI page yet" ARCHITECTURE.md docs/plugins.md src/asky/plugins/*/AGENTS.md` |
| Final regression and runtime check | `uv run pytest -q` |

## Assumptions And Defaults

- Milestone 5 remains intentionally skipped. This handoff may add browser-friendly intake endpoints, but it must not implement authenticated browser automation, Playwright session reuse, or site-specific scraping flows.
- GUI auth uses form login plus cookie-backed session only. No HTTP Basic, no API token, and no per-user account system are added.
- GUI password resolution follows the XMPP-style pattern: config value plus env override, with env preferred when both exist.
- Auth is required for all non-login routes; if no effective password exists, the GUI refuses to serve instead of running insecurely.
- Long-running jobs are queued; read-only/admin list views remain synchronous.
- Persona book/source browser forms use server-local path input in this milestone. Browser upload for books/sources is intentionally deferred.
- URL intake accepts one URL per request and starts a review flow with `target_results=1`.
- Scraped-content intake accepts one page payload per request and stages it as a one-page review-ready collection/page with browser-capture provenance.
- Session binding admin is a browser UI over existing persisted asky sessions. It is not a new browser conversation/session system.
- Operational-only tuning means:
- book extraction targets are editable in the browser
- source kind is selectable at submission time
- web target results are editable
- web approval can choose authored/about for uncertain pages
- duplicate similarity thresholds and runtime retrieval thresholds stay config-only

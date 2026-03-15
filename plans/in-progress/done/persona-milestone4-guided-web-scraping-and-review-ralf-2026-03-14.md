# RALF Handoff Plan: Persona Milestone 4, Guided Web Scraping And Source Review

## Summary

Implement roadmap milestone 4 as a **review-first web collection system** for personas. This handoff must add a separate `web-*` persona command family, collect public web pages into durable review batches, pause only after a requested batch of distinct pages has been accumulated, and require **per-page approval** before any scraped knowledge is promoted into canonical persona artifacts.

This milestone stays **public-web only**. It must not require authenticated/browser-assisted retrieval, and it must not depend on Playwright or session login state. The handoff must still leave a clean extension seam so milestone 5 can later route the same fetch path through browser-assisted acquisition.

The default mode is a bounded **seed-domain** crawl. A broader **expansion** mode is also included, but only as a later checkpoint after the seed-domain workflow is complete and verified. Broad expansion must still be review-first, must require a user-supplied page-count target, and must support two distinct input submodes:

- seed URLs/domains or URL files
- free-form search queries

Approved pages must join the existing milestone-3 source pipeline. They must become normal source bundles and flow into `sources`, `source-report`, `viewpoints`, `facts`, `timeline`, `conflicts`, export/import, and runtime retrieval without inventing a second canonical knowledge path.

## Public Interfaces

- New persona CLI entrypoints:
  - `asky persona web-collect <persona> --target-results N (--url URL ... | --url-file FILE)`
  - `asky persona web-expand <persona> --target-results N (--query QUERY | --url URL ... | --url-file FILE)`
  - `asky persona web-collections <persona> [--status STATUS] [--limit N]`
  - `asky persona web-review <persona> <collection_id> [--status STATUS] [--limit N]`
  - `asky persona web-page-report <persona> <collection_id> <page_id>`
  - `asky persona web-continue <persona> <collection_id>`
  - `asky persona web-approve-page <persona> <collection_id> <page_id> [--as authored|about]`
  - `asky persona web-reject-page <persona> <collection_id> <page_id>`
- New durable review storage under each persona:
  - `web_collections/<collection_id>/collection.toml`
  - `web_collections/<collection_id>/frontier.json`
  - `web_collections/<collection_id>/pages/<page_id>/page.toml`
  - `web_collections/<collection_id>/pages/<page_id>/content.md`
  - `web_collections/<collection_id>/pages/<page_id>/links.json`
  - `web_collections/<collection_id>/pages/<page_id>/preview.json`
  - `web_collections/<collection_id>/pages/<page_id>/report.json`
- New typed interfaces are required for:
  - `WebCollectionMode = seed_domain | broad_expand`
  - `WebCollectionInputMode = seed_urls | search_query`
  - `WebCollectionStatus = collecting | review_ready | completed | exhausted | failed`
  - `WebPageStatus = review_ready | approved | rejected | duplicate_filtered | fetch_failed`
  - `WebPageClassification = authored_by_persona | about_persona | uncertain | irrelevant`
- Approved scraped pages must project into ordinary source bundles with:
  - `source_class = scraped_web`
  - `trust_class = authored_primary` when the page is approved as `authored`
  - `trust_class = third_party_secondary` when the page is approved as `about`
  - `uncertain` pages may not be approved unless the reviewer supplies `--as authored|about`

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `708606e85436c96315e76e1bdb1b599c95618bcf`
- Last Reviewed HEAD: `approved+squashed (finalized 2026-03-15)`
- Review Log:
  - `2026-03-14`: reviewed `708606e85436c96315e76e1bdb1b599c95618bcf..594ae9166bfe5f422c357b3515384d17694f516c`, outcome `changes-requested`, follow-up fix plans created for milestone-4 corrections
  - `2026-03-15`: reviewed `594ae9166bfe5f422c357b3515384d17694f516c..f05f762dcd2437c3fc80b1032828637ceca598a3` and `f05f762dcd2437c3fc80b1032828637ceca598a3..88518c8256960f7a13069efc690d09e08575f0fd`, outcome `approved+squashed`, finalized accumulated handoff from `708606e85436c96315e76e1bdb1b599c95618bcf`

## Done Means

- Public-web persona collection is exposed through the exact `web-*` CLI family above, and `ingest-source` / `source-*` are not overloaded to mean crawling.
- `web-collect` is the default bounded workflow:
  - accepts public seed URLs, bare domains, or a UTF-8 URL file
  - normalizes bare domains to `https://<domain>`
  - stays within the original seed domains only
  - never performs open-web search expansion
  - stops only when either:
    - `N` distinct review-ready pages have been accumulated, or
    - the bounded frontier is exhausted
- `web-expand` is the broader public-web workflow:
  - requires `--target-results N`
  - supports exactly one input submode per run:
    - `--query QUERY`
    - `--url URL ...`
    - `--url-file FILE`
  - may cross domains
  - accumulates review-ready pages in batches, not one-at-a-time
  - overcollects raw candidates up to `ceil(N * 1.3)` before final distinctness filtering
- The system fetches page content, extracts links, classifies each page, generates a review preview, and persists all review data **before** asking the user to review.
- Review is **per page**:
  - the user can inspect page details before approval
  - approving one page does not auto-approve the rest of the collection
  - the user can continue collection after reviewing a batch
- Pending, rejected, duplicate-filtered, and failed pages never affect:
  - `persona_knowledge/**`
  - `chunks.json`
  - `embeddings.json`
  - `persona_knowledge/runtime_index.json`
  - persona answer packets
- Approved pages join the existing source pipeline:
  - each approval creates or refreshes one ordinary `ingested_sources/<source_id>/...` bundle
  - those bundles appear in existing `sources`, `source-report`, `viewpoints`, `facts`, `timeline`, and `conflicts`
  - runtime retrieval can use approved scraped viewpoints after projection
- Classification and trust are preserved end to end:
  - every page stores whether it looks authored by the persona, about the persona, uncertain, or irrelevant
  - approval fixes trust according to the classification policy above
  - authored books still outrank approved scraped pages when relevance is otherwise comparable
- Export/import preserves pending and reviewed web collections under `web_collections/**`, while keeping runtime artifacts derived and rebuildable.
- The implementation uses only existing public-web retrieval/search paths and existing embedding infrastructure. No new dependency may be added.
- Docs and affected subdirectory `AGENTS.md` files are updated only for shipped milestone-4 behavior.
- Final regression passes in `/home/evren/code/asky`, and runtime growth is investigated if it exceeds `max(3.0s, 20%)` over the current baseline:
  - `1559 passed in 17.85s`
  - `real 18.14`

## Critical Invariants

- `ingest-source` and milestone-3 `source-*` commands remain the local/manual source family. Web collection must stay on the new `web-*` family.
- `source_class = scraped_web` is the canonical class for approved milestone-4 pages. Do not relabel approved web pages as `manual_source` or `third_party_commentary`.
- Review state is file-backed inside the persona package. Global `research_cache` and SQLite may be used as helpers, but they must not become the canonical store for collection state, previews, or approval status.
- Per-page review is mandatory for all scraped pages. There is no auto-approval path for milestone 4, including pages classified as authored by the persona.
- The reviewer must not be forced to sit in front of the machine while the crawler finds pages. Collection must batch work first and pause only when a review-ready batch is accumulated or the frontier is exhausted.
- `--target-results N` is required for both `web-collect` and `web-expand`.
- Default seed-domain mode must remain bounded:
  - same-domain only
  - no search expansion
  - no cross-domain jumps
- Broad expansion must remain review-first and public-web only:
  - no authenticated scraping
  - no Playwright/browser requirement
  - no private session/cookie dependence
- Distinctness filtering must err on recall:
  - exact duplicates must collapse
  - near-duplicates may still surface if the system cannot safely prove they are redundant
  - meaningfully different pages should not be discarded aggressively
- Approved pages must reuse the existing canonical projection path so runtime and CLI query surfaces stay unified.
- Existing user worktree changes must not be reverted, including the current modification to `plans/in-progress/persona-roadmap.md`.
- Root `AGENTS.md` must not be modified.
- README stays untouched unless an already relevant persona web-collection section exists at implementation time. In this checkout, no such section exists, so README should remain untouched.

## Forbidden Implementations

- Do not overload `asky persona ingest-source` to accept URLs, domains, or crawl modes.
- Do not keep pending or approved web-review state only in SQLite, only in `research_cache`, or only in memory.
- Do not auto-promote scraped pages into canonical persona knowledge without explicit per-page approval.
- Do not require Playwright, browser login, daemon state, or authenticated site sessions in this milestone.
- Do not make `web-collect` perform open search expansion or leave seed domains.
- Do not make `web-expand` run without a user-supplied `--target-results`.
- Do not let `uncertain` or `irrelevant` classifications silently map to `authored_primary`.
- Do not duplicate milestone-3 projection logic in a second incompatible code path. Factor or reuse the current source-bundle projection helpers instead.
- Do not store raw HTML as the canonical review artifact. Persist normalized content snapshots and provenance instead.
- Do not describe milestone-5 browser-assisted behavior, GUI review pages, or future autonomous internet-wide research as implemented.

## Checkpoints

### [x] Checkpoint 1: Web Collection Storage And Portability Contract

**Goal:**

- Add the durable persona-owned storage contract for web collections, pages, review state, and export/import portability before any crawling behavior is implemented.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short`
- `sed -n '1,240p' src/asky/plugins/AGENTS.md`
- `sed -n '1,260p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,220p' src/asky/cli/AGENTS.md`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/storage.py`
- `sed -n '1,220p' src/asky/plugins/manual_persona_creator/exporter.py`
- `sed -n '1,220p' src/asky/plugins/persona_manager/importer.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/web_types.py`
- `tests/asky/plugins/manual_persona_creator/test_web_storage.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/storage.py`
- `src/asky/plugins/manual_persona_creator/exporter.py`
- `src/asky/plugins/persona_manager/importer.py`
- `tests/asky/plugins/persona_manager/test_authored_book_import.py`
- Must not touch:
- `src/asky/cli/**`
- `src/asky/core/**`
- `src/asky/api/**`
- `src/asky/plugins/playwright_browser/**`
- Constraints:
- keep existing authored-book and milestone-3 source storage untouched
- keep import/export backward compatible
- keep `web_collections/**` separate from `ingested_sources/**`

**Steps:**

- [ ] Step 1: Add typed models for collection mode, input mode, collection status, page status, page classification, collection manifest, page manifest, and review-preview metadata.
- [ ] Step 2: Extend storage helpers with exact canonical paths:
  - `web_collections/<collection_id>/collection.toml`
  - `web_collections/<collection_id>/frontier.json`
  - `web_collections/<collection_id>/pages/<page_id>/page.toml`
  - `web_collections/<collection_id>/pages/<page_id>/content.md`
  - `web_collections/<collection_id>/pages/<page_id>/links.json`
  - `web_collections/<collection_id>/pages/<page_id>/preview.json`
  - `web_collections/<collection_id>/pages/<page_id>/report.json`
- [ ] Step 3: Lock the identity rules:
  - `collection_id = "web_<UTCSTAMP>_<uuid8>"`
  - `page_id = "page:<sha256(normalized_final_url)[:16]>"`
  - promoted `source_id = "source:web:<sha256(normalized_final_url + \"\\n\" + content_fingerprint)[:16]>"`
- [ ] Step 4: Persist exact provenance fields per page:
  - requested URL
  - final URL
  - page title
  - normalized final URL
  - discovered-from URL or query mode marker
  - content fingerprint
  - classification
  - candidate trust recommendation
  - similarity/duplicate metadata
- [ ] Step 5: Extend exporter/importer so persona packages include `web_collections/**` and still rebuild derived runtime artifacts after import.
- [ ] Step 6: Keep review collections portable without exporting raw HTML or any browser/session-only artifacts.
- [ ] Step 7: Add storage/import/export tests for:
  - web-collection round-trip
  - page artifact round-trip
  - no absolute-path leakage
  - legacy authored-book and milestone-3 source imports still rebuild

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_storage.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_source_storage.py tests/asky/plugins/manual_persona_creator/test_authored_book_storage.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- A persona archive can preserve pending or reviewed web collections without breaking existing authored-book or milestone-3 portability.
- A git commit is created with message: `persona: add web collection storage contract`

**Stop and Escalate If:**

- Portability would require making SQLite or `research_cache` the source of truth for review state.
- Review portability would require exporting raw HTML or browser session artifacts.

### [x] Checkpoint 2: Seed-Domain Collection Backend And Review Staging

**Goal:**

- Implement the default bounded public-web collection backend that fetches pages, stages review-ready page artifacts, and pauses only after a requested distinct-results batch is ready.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/retrieval.py`
- `sed -n '1,260p' src/asky/research/cache.py`
- `sed -n '1,260p' src/asky/research/shortlist_collect.py`
- `sed -n '1,260p' src/asky/research/source_shortlist.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/storage.py`
- `find tests/asky/plugins/manual_persona_creator -maxdepth 1 -type f | sort`

**Scope & Blast Radius:**

- May create:
- `src/asky/plugins/manual_persona_creator/web_service.py`
- `src/asky/plugins/manual_persona_creator/web_job.py`
- `src/asky/plugins/manual_persona_creator/web_prompts.py`
- `tests/asky/plugins/manual_persona_creator/test_web_job.py`
- `tests/asky/plugins/manual_persona_creator/test_web_review.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/storage.py`
- Must not touch:
- `src/asky/cli/**`
- `src/asky/plugins/playwright_browser/**`
- `src/asky/core/**`
- `src/asky/api/**`
- Constraints:
- default mode is seed-domain only
- use public `fetch_url_document()` path only
- no search expansion in this checkpoint
- no approval/projection in this checkpoint

**Steps:**

- [ ] Step 1: Add reusable service entrypoints for:
  - `start_seed_domain_collection(...)`
  - `list_web_collections(...)`
  - `get_collection_review_pages(...)`
  - `get_page_report(...)`
  - `continue_collection(...)`
- [ ] Step 2: Accept seed inputs as repeated `--url` values or a UTF-8 `--url-file`, normalize bare domains to `https://<domain>`, and persist the chosen input mode in `collection.toml`.
- [ ] Step 3: Fetch each page through `fetch_url_document()` with milestone-4-specific trace context, persist normalized markdown/text to `content.md`, and persist discovered links to `links.json`.
- [ ] Step 4: Reuse existing public-web link extraction and URL normalization rules to build the frontier, but constrain all follow-up fetches to the original seed domains only.
- [ ] Step 5: Run page classification plus preview extraction before review. Persist per-page preview content that includes:
  - short summary
  - candidate viewpoints
  - candidate facts
  - candidate timeline events
  - conflict candidates
  - recommended classification and trust
- [ ] Step 6: Apply duplicate handling before counting toward the review target:
  - exact duplicate by normalized final URL or identical content fingerprint -> `duplicate_filtered`
  - near-duplicate by embedding similarity `>= 0.92` and same extracted dominant topic -> `duplicate_filtered`
  - otherwise keep both pages to err on recall
- [ ] Step 7: Transition collection status to:
  - `review_ready` when `N` distinct review-ready pages exist
  - `exhausted` when the frontier ends before `N`
- [ ] Step 8: Ensure `continue_collection(...)` resumes from `frontier.json`, never re-fetches approved/rejected/duplicate/failed pages, and returns the next review batch instead of prompting per fetch.
- [ ] Step 9: Add tests for:
  - same-domain frontier filtering
  - URL-file intake
  - review-ready batch stopping
  - duplicate filtering
  - collection resume after review
  - no canonical projection while pages are only staged for review

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_job.py tests/asky/plugins/manual_persona_creator/test_web_review.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/research/test_source_shortlist.py tests/asky/plugins/manual_persona_creator/test_source_review.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- `web-collect` backend can produce a review-ready page batch without promoting anything into canonical persona knowledge.
- A git commit is created with message: `persona: add seed-domain web collection backend`

**Stop and Escalate If:**

- The public-web fetch path cannot collect the required pages without browser-authenticated access.
- Same-domain collection would require open-web search expansion to be useful at all.

### [x] Checkpoint 3: CLI Web Family And Per-Page Promotion Into Source Pipeline

**Goal:**

- Expose the seed-domain workflow through the new `web-*` CLI family and make per-page approval/rejection project cleanly into the existing milestone-3 source pipeline.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1600,1860p' src/asky/cli/main.py`
- `grep -n 'handle_persona_ingest_source\\|handle_persona_sources\\|handle_persona_source_report' -n src/asky/cli/persona_commands.py`
- `sed -n '360,720p' src/asky/cli/persona_commands.py`
- `sed -n '1,420p' src/asky/plugins/manual_persona_creator/source_service.py`
- `sed -n '1,260p' tests/asky/cli/test_persona_source_commands.py`
- `sed -n '1,220p' tests/integration/cli_recorded/test_cli_persona_recorded.py`

**Scope & Blast Radius:**

- May create:
- `tests/asky/cli/test_persona_web_commands.py`
- May modify:
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- `src/asky/plugins/manual_persona_creator/web_service.py`
- `src/asky/plugins/manual_persona_creator/source_service.py`
- `src/asky/plugins/manual_persona_creator/runtime_index.py`
- `tests/asky/plugins/persona_manager/test_source_runtime.py`
- `tests/integration/cli_recorded/test_cli_persona_recorded.py`
- `tests/integration/cli_recorded/cli_surface.py`
- Must not touch:
- `src/asky/plugins/playwright_browser/**`
- `src/asky/core/**`
- `src/asky/api/**`
- Constraints:
- add only the exact `web-*` CLI surface defined above
- approved pages must reuse the existing source projection path
- existing `source-*` and authored-book commands must keep their current behavior

**Steps:**

- [ ] Step 1: Add the exact `web-*` subcommands and arguments to `src/asky/cli/main.py`.
- [ ] Step 2: Implement CLI handlers that render:
  - collection preflight
  - collection list/status
  - review-ready page tables
  - detailed per-page preview reports
  - continue/approve/reject confirmations
- [ ] Step 3: Refactor or extend `source_service.py` so web-page approval can reuse a shared projector instead of duplicating milestone-3 bundle projection logic.
- [ ] Step 4: On approval, materialize one ordinary `ingested_sources/<source_id>/...` bundle from the saved page preview and content snapshot, then project it into:
  - `persona_knowledge/sources.json`
  - `persona_knowledge/entries.json`
  - `persona_knowledge/conflict_groups.json` when present
  - compatibility `chunks.json`
  - derived `embeddings.json`
  - derived `persona_knowledge/runtime_index.json`
- [ ] Step 5: Apply trust/classification rules exactly:
  - `authored_by_persona` -> approve as `authored_primary`
  - `about_persona` -> approve as `third_party_secondary`
  - `uncertain` -> require `--as authored|about`
  - `irrelevant` -> cannot be approved
- [ ] Step 6: Make approval idempotent. Re-approving the same page must refresh the same promoted source record instead of duplicating entries.
- [ ] Step 7: Keep rejected pages inside `web_collections/**` only. Rejection must not create an `ingested_sources` bundle and must not affect canonical artifacts.
- [ ] Step 8: Add tests for:
  - CLI argument parsing and command dispatch
  - review/report rendering behavior
  - approval classification override
  - approved-page visibility in `sources`, `viewpoints`, `facts`, `timeline`, and runtime retrieval
  - pending/rejected page exclusion from runtime

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_persona_web_commands.py tests/asky/plugins/manual_persona_creator/test_web_review.py tests/asky/plugins/persona_manager/test_source_runtime.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_persona_source_commands.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Done When:**

- Verification commands pass cleanly.
- A user can collect a review batch, inspect pages one by one, approve selected pages, and see those approvals flow through the existing persona source/runtime surfaces.
- A git commit is created with message: `persona: add web review cli and source projection`

**Stop and Escalate If:**

- Approved web pages cannot join the current source/query/runtime path without inventing a second canonical projection model.
- The CLI surface would need to remove or redefine existing milestone-3 commands to make room for the new workflow.

### [x] Checkpoint 4: Broad Expansion Mode With Distinct-Results Batching

**Goal:**

- Add the later checkpoint broad expansion mode, still public-web only, with query or seed inputs, review-first batching, and overcollection for distinctness.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' src/asky/research/AGENTS.md`
- `sed -n '1,260p' src/asky/research/shortlist_collect.py`
- `sed -n '1,320p' src/asky/research/source_shortlist.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/web_service.py`
- `sed -n '1,360p' src/asky/plugins/manual_persona_creator/web_job.py`
- `find tests/asky/plugins/manual_persona_creator -maxdepth 1 -type f | sort`

**Scope & Blast Radius:**

- May create:
- `tests/asky/plugins/manual_persona_creator/test_web_expand.py`
- May modify:
- `src/asky/plugins/manual_persona_creator/web_service.py`
- `src/asky/plugins/manual_persona_creator/web_job.py`
- `src/asky/cli/main.py`
- `src/asky/cli/persona_commands.py`
- `src/asky/research/shortlist_collect.py`
- `tests/asky/cli/test_persona_web_commands.py`
- Must not touch:
- `src/asky/plugins/playwright_browser/**`
- `src/asky/core/**`
- `src/asky/api/**`
- Constraints:
- no authenticated browsing
- no Playwright dependency
- keep broad mode a later slice on top of the verified seed-domain path

**Steps:**

- [ ] Step 1: Add `web-expand` with exactly one input submode per run:
  - `--query QUERY`
  - repeated `--url URL`
  - `--url-file FILE`
- [ ] Step 2: Require `--target-results N` for every broad run and store that target in `collection.toml`.
- [ ] Step 3: Reuse the existing shortlist/search collection path for query-mode candidate discovery. Do not add a new search provider or new dependency.
- [ ] Step 4: For URL/file input mode, allow cross-domain discovery from the collected pages' outbound links. Do not silently switch to free-form search if the user did not request query mode.
- [ ] Step 5: Overcollect raw candidates up to `ceil(target_results * 1.3)` before final distinctness filtering, then stop and stage exactly the next distinct review batch unless the frontier exhausts first.
- [ ] Step 6: Keep collection and preview processing overlapping:
  - fetch, classify, and preview pages in parallel
  - persist stable discovery order in the collection artifacts
  - do not present partially processed pages for review
- [ ] Step 7: Ensure `web-continue` works for broad collections exactly like seed-domain collections and never revisits already terminal pages.
- [ ] Step 8: Add tests for:
  - query-mode expansion using existing search-executor wiring
  - cross-domain URL expansion
  - required `--target-results`
  - `1.3x` overcollection stop rule
  - distinct-results batch sizing
  - continue after first review batch

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_expand.py tests/asky/cli/test_persona_web_commands.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/research/test_source_shortlist.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Done When:**

- Verification commands pass cleanly.
- Broad expansion can stage a distinct review batch from either query or URL/file inputs without requiring browser-assisted retrieval.
- A git commit is created with message: `persona: add broad web expansion mode`

**Stop and Escalate If:**

- Query-mode expansion would require adding a new search provider instead of reusing the existing shortlist/search path.
- Broad expansion becomes unusable without authenticated/browser-assisted retrieval, which belongs to milestone 5 instead.

### [x] Checkpoint 5: Documentation Parity, Devlog, And Full Regression

**Goal:**

- Bring docs, local agent guidance, and regression coverage into parity with the shipped milestone-4 behavior.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,260p' ARCHITECTURE.md`
- `sed -n '1,220p' docs/plugins.md`
- `sed -n '1,220p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,220p' src/asky/cli/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/persona_manager/AGENTS.md`
- `sed -n '1,220p' devlog/DEVLOG.md`
- `grep -n 'persona' README.md docs/plugins.md ARCHITECTURE.md | sed -n '1,220p'`

**Scope & Blast Radius:**

- May modify:
- `ARCHITECTURE.md`
- `docs/plugins.md`
- `devlog/DEVLOG.md`
- `src/asky/plugins/manual_persona_creator/AGENTS.md`
- `src/asky/cli/AGENTS.md`
- `src/asky/plugins/persona_manager/AGENTS.md`
- `src/asky/research/AGENTS.md` only if checkpoint 4 changed research helpers
- Must not touch:
- `AGENTS.md`
- `README.md` unless an already relevant persona web-collection section is found
- Constraints:
- document only shipped milestone-4 behavior
- do not describe browser-assisted collection as implemented

**Steps:**

- [ ] Step 1: Update `ARCHITECTURE.md` for:
  - web collection storage under persona packages
  - review-first collection flow
  - per-page approval into canonical source projection
  - broad public-web expansion as part of milestone 4
- [ ] Step 2: Update `docs/plugins.md` with the exact `web-*` command family and milestone-4 behavior boundaries.
- [ ] Step 3: Update affected subdirectory `AGENTS.md` files only where the new behavior changes local implementation guidance.
- [ ] Step 4: Update `devlog/DEVLOG.md` with summary, behavior changes, gotchas, and verification timings.
- [ ] Step 5: Search for an already relevant README persona-web section. If none exists, leave `README.md` untouched and note that explicitly in the devlog/docs review.
- [ ] Step 6: Run final regression and compare runtime against the current baseline.

**Dependencies:**

- Depends on Checkpoint 4.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_storage.py tests/asky/plugins/manual_persona_creator/test_web_job.py tests/asky/plugins/manual_persona_creator/test_web_review.py tests/asky/plugins/manual_persona_creator/test_web_expand.py tests/asky/cli/test_persona_web_commands.py tests/asky/plugins/persona_manager/test_source_runtime.py -q -n0`
- Run recorded CLI regression: `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'`
- Run full suite: `time -p uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Documentation matches the actual milestone-4 behavior and excludes milestone-5 browser-assisted behavior.
- A git commit is created with message: `docs: finalize persona web collection milestone`

**Stop and Escalate If:**

- Documentation parity would require describing behavior that is still only planned for milestone 5.
- Full-suite runtime grows beyond `max(3.0s, 20%)` over `real 18.14` without a defensible explanation.

## Behavioral Acceptance Tests

- Given `asky persona web-collect arendt --target-results 10 --url https://example.com/arendt`, the system fetches only the seed domain, stages up to 10 distinct review-ready pages, writes them under `web_collections/<collection_id>/`, and does not create or update `ingested_sources/**` until a page is approved.
- Given a review-ready collection, `asky persona web-review arendt <collection_id>` shows page IDs, titles, final URLs, classification, status, and preview counts, and `asky persona web-page-report arendt <collection_id> <page_id>` shows the stored preview knowledge for that one page.
- Given a page classified `authored_by_persona`, `asky persona web-approve-page arendt <collection_id> <page_id>` creates a normal scraped-web source bundle, projects it into canonical knowledge, and makes its viewpoints visible through `asky persona sources`, `asky persona viewpoints`, and runtime retrieval.
- Given a page classified `about_persona`, approval projects it with `trust_class = third_party_secondary`, and it can be queried through existing source surfaces without outranking authored-book viewpoints when relevance is otherwise comparable.
- Given a page classified `uncertain`, plain approval is rejected; `asky persona web-approve-page ... --as authored` or `--as about` is required to set trust explicitly.
- Given a first review batch has been processed, `asky persona web-continue arendt <collection_id>` resumes from the saved frontier and returns the next distinct batch without reprocessing already terminal pages.
- Given `asky persona web-expand arendt --target-results 50 --query "Hannah Arendt interview freedom"`, the system may overcollect up to `65` raw candidates, filters for distinctness, stages the next review-ready batch, and pauses before any promotion.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Separate `web-*` CLI family exists and `source-*` is unchanged | `uv run pytest tests/asky/cli/test_persona_web_commands.py tests/asky/cli/test_persona_source_commands.py -q -n0` |
| Pending/rejected/duplicate/failed web pages never affect canonical/runtime artifacts | `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_review.py tests/asky/plugins/persona_manager/test_source_runtime.py -q -n0` |
| Approved pages join the existing source/query/runtime pipeline | `uv run pytest tests/asky/plugins/persona_manager/test_source_runtime.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Seed-domain mode stays bounded to the original domains | `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_job.py -q -n0` |
| Broad expansion supports query and URL/file inputs with required targets | `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_expand.py -q -n0` |
| Distinct-results batching uses overcollection before review | `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_expand.py::test_broad_expand_overcollects_before_batch_cutoff -q -n0` |
| Web collections are portable across export/import | `uv run pytest tests/asky/plugins/manual_persona_creator/test_web_storage.py tests/asky/plugins/persona_manager/test_authored_book_import.py -q -n0` |
| Docs reflect shipped milestone-4 behavior only | `grep -n 'web-collect\\|web-expand\\|web-approve-page\\|browser-assisted' ARCHITECTURE.md docs/plugins.md src/asky/plugins/manual_persona_creator/AGENTS.md src/asky/cli/AGENTS.md src/asky/plugins/persona_manager/AGENTS.md` |
| Final regression remains healthy | `time -p uv run pytest -q` |

## Assumptions And Defaults

- Milestone 4 is public-web only. Authenticated/browser-assisted acquisition remains milestone 5 work.
- The seed-domain workflow is the default and recommended user path.
- The broader expansion mode is included in this handoff, but only after the seed-domain workflow is complete and stable.
- Review happens per page after batched accumulation, not interactively during crawling.
- Approved scraped pages become ordinary source bundles and reuse the existing milestone-3 source/query/runtime path.
- Search-query and URL/domain broad inputs are both supported, but they are distinct input submodes under `web-expand`, not a single mixed run.
- `--target-results` is required for both collection modes.
- Broad expansion overcollects by a fixed factor of `1.3`; exact and near-duplicate filtering are applied before the review batch is cut.
- Distinctness uses the existing embedding toolkit. No new vector store or third-party dependency may be introduced.
- If query-mode expansion cannot be implemented cleanly through the existing shortlist/search executor path, stop and escalate instead of adding a new search stack.
- The current dirty worktree file `plans/in-progress/persona-roadmap.md` is user-owned and must be left alone by implementation.

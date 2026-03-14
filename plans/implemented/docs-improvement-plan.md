# asky Documentation Improvement Plan — User-Facing Onboarding Audit

## Purpose

This plan defines a structured, multi-phase improvement to asky's user-facing documentation. The audit was conducted by reading all linked documentation from `README.md` as an emulated end user with no prior project knowledge.

**End state:** A first-time user can install asky, run a query against a real LLM, understand what features they are missing, and find a clear next step — all within 10 minutes, using only the docs.

---

## Problem Summary

Current docs are high-quality *reference* material for users who already understand the system. What is missing is *onboarding* documentation. The gap between "I just installed this" and "I'm using it successfully" is too wide.

**Root causes:**
- No minimum viable setup guide (users don't know what prerequisites they need)
- Features are listed but not demonstrated in context
- XMPP/daemon mode assumes protocol knowledge
- No troubleshooting path for when things go wrong
- Developer-facing docs mixed into the user docs index
- The one live demo in README uses an unexplained shortcut (`/wh`)

---

## Ownership Split

Each phase is owned by either the developer (Claude) or the user, based on what requires
live terminal captures, screenshots, or actual runtime observation.

| Owner | Meaning |
|-------|---------|
| **Dev** | Written entirely from source code and docs; no live run needed |
| **Dev + CAPTURE** | Dev writes the full frame; user fills `<!-- CAPTURE: ... -->` placeholders with real terminal output |
| **User** | Requires screenshots or live app interaction that dev cannot produce |

Placeholder format used throughout docs:

```
<!-- CAPTURE: run `<exact command>` and paste the terminal output here -->
<!-- SCREENSHOT: <description of what to capture> -->
```

## Phase Overview

| # | Phase | Output | Owner | Priority |
|---|-------|--------|-------|----------|
| 1 | First-Run Onboarding Guide | `docs/quickstart.md` | Dev + CAPTURE | Critical |
| 2 | README Rewrite | Updated `README.md` | Dev | Critical |
| 3 | XMPP Daemon Approachability | Updated `docs/xmpp_daemon.md` | Dev + SCREENSHOT | High |
| 4 | Document Q&A Tutorial | `docs/document_qa.md` | Dev + CAPTURE | High |
| 5 | Troubleshooting & FAQ | `docs/troubleshooting.md` | Dev | Medium |
| 6 | Memory System Walkthrough | Updated `docs/elephant_mode.md` | Dev + CAPTURE | Medium |
| 7 | Docs Index Restructure | Updated `README.md` docs index | Dev | Low |

---

## Phase 1 — First-Run Onboarding Guide

### Done When

A user who has never heard of asky can follow `docs/quickstart.md` from top to bottom and end with a working query. The guide covers exactly one path (no branching) and takes under 10 minutes.

### File to Create

- `docs/quickstart.md` (new)

### Content Requirements

The guide must cover these steps in strict sequence:

**Step 1 — Prerequisites checklist**
List exactly what the user needs before running any command:
- Python 3.10+ or uv installed
- One LLM API key (Gemini free tier recommended as lowest-friction entry point — confirm this assumption against current model defaults)
- One search provider: Serper (paid, 2500 free requests) or SearXNG (self-hosted, free). State clearly that web search will not work without this.
- Note: if user skips search setup, basic queries still work; tool-call searches will fail silently or with error

**Step 2 — Install**
Single recommended path only:
```bash
uv tool install asky-cli
```
Do not show alternatives here (pip, editable). Those belong in configuration.md.

**Step 3 — First run and config auto-creation**
Explain exactly what happens when the user runs `asky hello` for the first time:
- Config directory is created at `~/.config/asky/`
- Default config files are written
- The query will fail if no API key is configured — show the expected error
- Show how to open/edit `~/.config/asky/api.toml` to add the API key

**Step 4 — Add an API key**
Show the minimal api.toml edit. Pick one provider (Gemini or OpenAI) and show it completely. Link to configuration.md for other providers.

**Step 5 — Add a model alias**
Show `asky --config model add` and explain that model aliases (like `gf`) come from this step. Explain that the default model is set in `general.toml` under `default_model`.

**Step 6 — First successful query (no search)**
```bash
asky "What is the capital of France?"
```
Show expected terminal output. Annotate the output lines (what is "Query completed in X seconds").

**Step 7 — Enable web search (optional but recommended)**
Show the Serper path (add `SERPER_API_KEY` env var) as the lower-effort option. Show the one config line needed in `general.toml`. Show a query that uses search:
```bash
asky "What is the current weather in London?"
```
Show expected output including tool dispatch lines.

**Step 8 — What next?**
Point to three docs only (not the full index):
- `docs/configuration.md` — for full setup
- `docs/research_mode.md` — for document and deep web research
- `docs/xmpp_daemon.md` — for remote access from any device

### Constraints

- No branching ("if you use X, do Y; if you use Z, do W"). Pick one path.
- No mention of XMPP, daemon, voice, plugins, personas. Those come later.
- Do not mention `pip install` — users should use `uv`.
- All code blocks must be copy-pasteable without modification (no `<your-key-here>` style placeholders without explanation).

### Verification

After writing, verify by tracing each step against actual CLI behavior:
```bash
# Confirm default config is created on first run
# Confirm error message when no API key is set
# Confirm --config model add works interactively
# Confirm basic query works after api.toml edit
```

---

## Phase 2 — README Rewrite

### Done When

The README answers "what is this, what do I need, and how do I start" in the first screen-height (no scrolling). The feature list still exists but is secondary to the onboarding story.

### File to Modify

- `README.md`

### Changes Required

**1. Add prerequisites callout immediately after the feature list**

Before the current Installation section, insert a Prerequisites block:

```markdown
## Prerequisites

Before installing, you need:
- **One LLM API key** — Gemini, OpenAI, or any OpenAI-compatible endpoint.
- **One search provider** — [Serper](https://serper.dev) (2500 free requests) or a local [SearXNG](https://searxng.github.io/searxng/) instance. Web search features require this.

See [Quick Start](./docs/quickstart.md) for step-by-step setup.
```

**2. Add Quick Start link prominently**

After the Prerequisites block, before the current installation section:
```markdown
**New to asky?** → [Quick Start Guide](./docs/quickstart.md)
```

**3. Explain the `/wh delft` example**

The current console demo shows `asky /wh delft` which uses an unexplained preset. Either:
- Replace the example with a plain query that needs no explanation: `asky "What is the weather in Delft?"`
- Or add one sentence: `# /wh is a built-in preset shorthand — see Command Presets in configuration.md`

Recommendation: replace with plain query to remove friction.

**4. Explain model alias in the Basic Usage section**

The line `asky -m gf "Explain quantum entanglement"` uses `gf` without explanation.
Change to:
```bash
# Use a specific model alias (defined in your models.toml)
asky -m gf "Explain quantum entanglement"
```

**5. Reframe the XMPP daemon feature benefit**

Current: "Run asky as an XMPP client daemon"
Proposed: "**Remote Access from Any Device**: Run `asky --daemon` to expose asky over XMPP chat, so you can query it from any XMPP-capable device (phone, tablet, desktop app)."

**6. Add a "Document Q&A" usage example**

In the Basic Usage section, add:
```bash
# Ask questions about local documents
asky -r ~/docs/my-report.pdf "What are the key conclusions?"
```

### Constraints

- Do not remove any existing feature descriptions — only reorganize and clarify.
- Do not add a "comparison with alternatives" section (out of scope).
- Keep the README under 150 lines; move detail to linked docs.

---

## Phase 3 — XMPP Daemon Approachability

### Done When

A user who does not know what XMPP is can read `docs/xmpp_daemon.md` and understand: (a) what they get from this feature, (b) what they need to set it up, (c) how to get an XMPP account.

### File to Modify

- `docs/xmpp_daemon.md`

### Changes Required

**1. Add a "What is XMPP?" intro paragraph at the top**

Insert before "Install Optional Dependencies":
```
## What This Feature Does

XMPP daemon mode lets you talk to asky from any messaging app that supports XMPP (also known as Jabber) — including apps on your phone, tablet, or another computer. You set asky up once on your machine, and then you can query it remotely over chat, send voice messages, or even share documents for analysis.

XMPP is an open messaging protocol. You need one XMPP account (the "bot" account that asky logs into) and another account for yourself to send messages from. Free XMPP accounts are available at providers like [jabber.at](https://jabber.at) or [conversations.im](https://account.conversations.im/register/).

Recommended XMPP client apps:
- Android: [Conversations](https://conversations.im/) or [Cheogram](https://cheogram.com/)
- iOS: [Monal](https://monal-im.org/) or [Siskin IM](https://siskin.im/)
- Desktop: [Gajim](https://gajim.org/) (all platforms), [Beagle IM](https://beagle.im/) (macOS)
```

**2. Explain "JID" on first use**

After the callout, when `allowed_jids` is first mentioned in the config block, add a comment:
```toml
# JID = Jabber ID — your XMPP address, like an email address (user@server.com)
allowed_jids = ["alice@jabber.at"]
```

**3. Add a "Minimal Setup Checklist" at the top of the Configure section**

```markdown
Before configuring, you need:
1. A "bot" XMPP account for asky to log into (e.g., `myasky-bot@jabber.at`)
2. Your own XMPP account to send messages from (e.g., `me@jabber.at`)
3. An XMPP client app installed on your phone or other device
```

**4. Add a "What it looks like" section with an example chat exchange**

After the Run Daemon section, add a sample conversation:
```
You (from phone): What's the latest news about fusion energy?
asky: [Dispatching web_search...] Here is a summary of recent fusion energy developments...

You: /asky history list 5
asky: Recent queries: ...
```

### Constraints

- Do not add XMPP protocol detail beyond what's needed to set up the feature.
- Do not recommend specific XMPP servers as "best" — list 2-3 options with no ranking.
- Keep the existing technical reference sections intact.

---

## Phase 4 — Document Q&A Tutorial

### Done When

A user can follow `docs/document_qa.md` from top to bottom and successfully ask questions about a local PDF or folder of documents.

### File to Create

- `docs/document_qa.md` (new)

### Content Requirements

This addresses the README's headline feature "Talk with your documents" which has no dedicated doc.

**Step 1 — What this does**
Plain-language description: asky can read local files (PDF, EPUB, Markdown, plain text), index their content, and let you ask questions about them using natural language. All processing is local; your documents are not uploaded anywhere.

**Step 2 — Supported file types**
List exactly: `.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`, `.pdf`, `.epub`

**Step 3 — Ask a question about a single file**
```bash
asky -r path/to/document.pdf "What are the main conclusions?"
```
Explain what `-r` does here: ingests the file locally, indexes it, then uses the indexed content to answer.

**Step 4 — Ask about a folder of documents**
```bash
asky -r path/to/my-docs/ "Summarize the security policies across all documents"
```

**Step 5 — Configure a persistent document root**
Show how to set `research.local_document_roots` in `general.toml` so users can reference documents by relative path:
```bash
asky -r security/policies "List all MFA requirements"
```

**Step 6 — Continue the conversation**
Show that sessions persist:
```bash
asky -r mydoc.pdf -ss "Doc Review" "What does section 3 say about authentication?"
# Later:
asky -c "~1" "How does that compare to section 5?"
```

**Step 7 — Via XMPP (bonus)**
One paragraph: if daemon mode is enabled, attach a document as a file in your XMPP client. asky will automatically index it and allow questions.

**Step 8 — Advanced: browse sections**
```bash
asky -r mybook.epub --summarize-section
# Lists all sections
asky -r mybook.epub --summarize-section "Chapter 3"
```

### Constraints

- Do not explain research mode internals (shortlist, ChromaDB, etc.) — link to `research_mode.md` for those.
- All examples must use relative-path-style document references (no hardcoded `/Users/evren/...`).
- Make it clear that documents are not uploaded anywhere.

---

## Phase 5 — Troubleshooting & FAQ

### Done When

`docs/troubleshooting.md` exists and covers the top failure modes a new user will encounter.

### File to Create

- `docs/troubleshooting.md` (new)

### Content Requirements

Cover these failure scenarios in Q&A format:

**Setup issues**
- "I ran `asky hello` and got an error about API key" → show which file to edit and what key to add
- "I added an API key but still get connection errors" → check the model alias exists in `models.toml`, check the base URL
- "Web search returns nothing / search-related tool errors" → confirm `SERPER_API_KEY` is set or SearXNG is running; show how to test `searxng_url` manually with curl

**Research mode issues**
- "I ran `-r myfile.pdf` and got 'zero local documents ingested'" → check file path, check file type is supported, check `local_document_roots` config
- "Research mode seems slow" → explain background indexing; expected time per MB of documents

**Memory issues**
- "How do I know if memory recall is working?" → run `asky --list-memories`; explain what the preload log shows in verbose mode (`-v`)
- "Memory from session A is leaking into session B" → explain session-scoped vs global memory distinction

**XMPP daemon issues**
- "Daemon says 'already running' but I can't find it in the menubar" → macOS single-instance check; how to kill and restart
- "My XMPP messages are ignored with no response" → check `allowed_jids`; check JID format (bare vs full)
- "Voice messages are not being transcribed" → check `voice_enabled = true`; check mlx-whisper is installed; check macOS-only limitation

**General**
- "Where are logs?" → `~/.config/asky/asky.log`; how to set `log_level = "DEBUG"`
- "How do I reset everything?" → list config files and their purpose; explain which to delete vs which to edit

### Constraints

- Each answer must include a concrete diagnostic command or config location — no vague advice.
- Do not document internal implementation details; keep all advice at the config/CLI level.

---

## Phase 6 — Memory System Walkthrough

### Done When

`docs/elephant_mode.md` includes at least one end-to-end example showing two separate terminal sessions where a fact from session 1 is recalled in session 2.

### File to Modify

- `docs/elephant_mode.md`

### Changes Required

**Add a "Concrete Example" section** between "How Memory is Recalled" and "Managing Memories":

Show a two-session terminal transcript:

```
# Session 1
$ asky -ss "Work Setup" "I use Python 3.12 and prefer type hints everywhere"
[asky responds; save_memory tool is called with "User uses Python 3.12 with type hints"]
Memory saved: "User uses Python 3.12 with type hints"

# Later — new terminal, no session flag
$ asky "How should I annotate this function?"
## User Memory
- User uses Python 3.12 with type hints
[asky uses this context in its answer]
```

Add note: global memories appear in `## User Memory` block in verbose mode. Use `-v` to see when memory is being recalled.

**Clarify the trigger phrase behavior**

Add a note that "remember globally:" and "global memory:" are detected as prefixes, not keywords anywhere in the message. Example:
```bash
# Works (prefix):
asky "remember globally: I always deploy to Kubernetes"
# Does NOT work (not a prefix):
asky "Can you remember globally that I use dark mode?"
```

### Constraints

- Do not change the existing conceptual explanation — only add the concrete example section.
- The terminal transcript must show the memory being *recalled* in a separate invocation, not just saved.

---

## Phase 7 — Docs Index Restructure

### Done When

The `README.md` documentation index separates user-facing docs from developer/contributor docs. A new user sees only the docs relevant to them.

### File to Modify

- `README.md` (Documentation Index section)

### Changes Required

Split the current flat list into two sections:

**User Documentation**
- [Quick Start](./docs/quickstart.md) ← new
- [Configuration and Setup](./docs/configuration.md)
- [Document Q&A](./docs/document_qa.md) ← new
- [Deep Research Mode (`-r`)](./docs/research_mode.md)
- [User Memory & Elephant Mode (`-em`)](./docs/elephant_mode.md)
- [XMPP Daemon Mode](./docs/xmpp_daemon.md)
- [Custom Tools](./docs/custom_tools.md)
- [Playwright Browser Plugin](./docs/playwright_browser.md)
- [Plugin Runtime and Built-in Plugins](./docs/plugins.md)
- [Troubleshooting & FAQ](./docs/troubleshooting.md) ← new

**Developer / Advanced**
- [Library Usage Guide](./docs/library_usage.md)
- [Development Guide](./docs/development.md)
- [Research Evaluation](./docs/research_eval.md)

### Constraints

- Do not delete or rename existing doc files.
- Do not reorder within each section — keep alphabetical-ish order for discoverability.

---

## Implementation Order

Phases 1 and 2 are the highest-leverage changes — they affect every new user's first experience.
Phases 3 and 4 address the two most prominent but underexplained features.
Phases 5 and 6 improve retention for users who hit problems.
Phase 7 is cosmetic cleanup.

Recommended execution order: 1 → 2 → 4 → 3 → 5 → 6 → 7

Phase 2 (README) must be done after Phase 1 (quickstart) and Phase 4 (document_qa) because it links to both new files.

---

## Assumptions to Verify Before Writing

Before starting Phase 1 (quickstart):
1. Confirm which LLM provider is the lowest-friction entry point for a new user (Gemini free tier? OpenAI?). Check if there is a `default_model` in the generated `general.toml`.
2. Confirm the exact error message shown when no API key is configured — capture it by running a test install.
3. Confirm `asky --config model add` prompts interactively and creates a model alias — verify this path works end-to-end.
4. Confirm what happens on first run: which config files are auto-created vs which must be created manually.

Before starting Phase 3 (XMPP):
5. Confirm which XMPP client apps support the file upload protocol used by asky (XEP-0363) — do not recommend apps that cannot receive files from asky.

---

## Final Checklist (per phase)

- [ ] All code examples copy-paste without modification (or placeholders are explicitly labeled)
- [ ] All file paths are correct (verified against actual config structure)
- [ ] All CLI commands verified against current `asky --help` output
- [ ] No internal terminology (ChromaDB, slixmpp, stanza, etc.) without explanation or link
- [ ] Each new doc linked from README docs index
- [ ] `quickstart.md` linked from top of `configuration.md` and `xmpp_daemon.md`
- [ ] No developer-only content in user-facing phases
- [ ] Phase 2 README changes do not reduce line count in feature descriptions

# Deep Research Mode

Deep Research Mode (`-r`) is asky’s retrieval-focused workflow for multi-source questions, long documents, and local corpus analysis.

## One-Shot Document Summarization

When you request a summary of a small document set (≤10 documents by default), asky will provide a direct answer without asking clarifying questions.

### Examples

**One-Shot Mode** (direct answer):
```bash
asky -r ./my_docs "Summarize the key points across all documents"
asky -r ./reports "Give me an overview of the main ideas"
```

**Research Mode** (clarification questions):
```bash
asky -r ./large_corpus "Summarize the documents"  # >10 documents
asky -r ./my_docs "tell me about these"  # vague query
```

### Configuration

Control this behavior in `~/.config/asky/research.toml`:

```toml
[query_classification]
enabled = true
one_shot_document_threshold = 10
```

See [Configuration](configuration.md#query-classification) for all available settings.

## Session-Owned Behavior

Research mode is now a **session property**:

- If a session is marked as research, follow-up turns in that session keep research mode even when `-r` is omitted.
- Running `-r` on an existing non-research session promotes it to research permanently.
- Session corpus/source settings persist and are reused automatically on follow-up turns.
- Running `-r` with new corpus pointers replaces the session’s stored corpus pointer list.

To leave research mode for a shell, detach/end the session and use a non-research session.

## Enabling Research Mode

```bash
asky -r "Compare OAuth2 device flow vs PKCE for CLI apps"
```

## Corpus Pointer Syntax

`-r` accepts an optional corpus pointer token:

```bash
# Local-only profile
asky -r security/policies "Summarize MFA requirements"

# Multiple local pointers
asky -r "policy.md,controls.pdf" "List SOC2 controls"

# Mixed mode (local + web) using explicit web token
asky -r "policy.md,web" "Compare local policy with current public guidance"

# Web-only research profile
asky -r web "Investigate latest OpenTelemetry collector changes"
```

Notes:

- Local pointers are resolved against `research.local_document_roots`.
- Absolute local paths are allowed only when they are inside configured roots.
- Root-relative corpus paths (for example `/nested/doc.txt`) resolve under configured roots.
- In explicit pointer lists, `web` is the token used to request mixed/web-only source mode.
- Ambiguous single-token `-r` values still fall back to query text when they are not clearly pointers.

## Shortlist Override

Use `--shortlist auto|on|off` to control pre-LLM shortlisting per run:

```bash
asky -r --shortlist off "Quick targeted retrieval from preloaded corpus"
asky -r --shortlist on "Force shortlist even if model override disables it"
```

Precedence is:

1. `--lean` (`-L`) disables shortlist
2. `--shortlist on|off` request override
3. model-level shortlist override
4. global shortlist config

Lean note: `--lean` is broader than shortlist control. It also disables tool calls,
skips memory recall preload, and skips memory-extraction/context-compaction side effects.

## Local Corpus Reliability and Fail-Fast

For research profiles that expect local corpus input (`local_only` or `mixed`):

- asky preloads local documents before the first model call,
- and halts with an actionable error if zero local documents ingest.

This prevents silently falling back to memory-only/web-only behavior when local corpus pointers are invalid or stale.

When corpus preload succeeds, asky now runs one deterministic retrieval bootstrap
before the first model call and injects evidence snippets into preloaded context.
This protects local-corpus runs from dead-ending when research memory is empty.

## Local Ingestion Model

Local loading uses built-in local-source helpers (no custom source-adapter routing):

- Supported file types: `.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`, `.pdf`, `.epub`
- Directory pointers discover supported files and index selected content
- Content is chunked + embedded for retrieval with `get_relevant_content`

Generic URL-oriented research tools still reject local filesystem targets directly; local file access happens through the dedicated local ingestion pipeline.

Internally, preloaded local docs are referenced with safe handles (`corpus://cache/<id>`)
instead of filesystem paths so retrieval tools can operate without exposing raw paths.

## Manual Corpus Query (No Model)

Use `--query-corpus` to test retrieval behavior directly against cached/ingested corpus
without invoking any LLM:

```bash
# Query current cached corpus
asky --query-corpus "learning slog after moore's law"

# Ingest explicit local corpus targets first, then query
asky -r "The Efficiency Paradox What Big Data Cant Do - Edward Tenner.epub" \
  --query-corpus "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW" \
  --query-corpus-max-sources 12 \
  --query-corpus-max-chunks 2
```

This is useful for debugging which query phrasing retrieves strong chunks before running
full model-driven research turns.

## Deterministic Section Summarization (No Main Model)

For local corpus books/documents, use deterministic section commands to inspect
headings and generate deep section-bounded summaries:

```bash
# List sections from the resolved local source
asky -r "The Efficiency Paradox What Big Data Cant Do - Edward Tenner.epub" \
  --summarize-section

# Summarize one section in balanced detail (default)
asky -r "The Efficiency Paradox What Big Data Cant Do - Edward Tenner.epub" \
  --summarize-section "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW"

# Force a specific cached source + max detail profile
asky --summarize-section "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW" \
  --section-source corpus://cache/247 \
  --section-id why-learning-is-still-a-slog-after-fifty-years-o-038 \
  --section-detail max \
  --section-max-chunks 8

# Include TOC/debug rows while listing
asky --summarize-section --section-source corpus://cache/247 --section-include-toc
```

Behavior:

- Matching is strict; low-confidence matches return suggestions instead of guessing.
- `--summarize-section` without a value lists canonical body section IDs/titles by default.
- Use `--section-include-toc` to include TOC/micro heading rows.
- `--section-source` disambiguates source when multiple local docs are cached.
- `--section-id` provides deterministic section selection and bypasses title matching.
- `--section-detail` supports `compact`, `balanced` (default), and `max`.
- Section rows now include `section_ref` in the form `corpus://cache/<id>#section=<section-id>`.
- If a requested section ID points to a tiny TOC/alias slice, summarization auto-promotes
  to the canonical body section when available.
- Tiny resolved sections are rejected with actionable errors instead of being summarized.

### Common Pitfall: `SECTION_QUERY` vs `--section-id`

`--summarize-section` positional text is always interpreted as `SECTION_QUERY` (title-like
strict match), not as a section ID.

This means the following shape is expected to fail when `section-001` is an ID and not a
title:

```bash
asky -r mybook.epub --summarize-section section-001
```

Use one of these instead:

```bash
# Deterministic by exact ID
asky -r mybook.epub --summarize-section --section-id section-001

# By title query (strict title matching)
asky -r mybook.epub --summarize-section "Full Document"
```

Grouped command parity uses the same rule:

```bash
# Interpreted as SECTION_QUERY, not SECTION_ID
asky corpus summarize section-001

# Deterministic ID selection
asky corpus summarize --section-id section-001
```

## Research Toolset

Research mode exposes retrieval-first tools:

- `extract_links`
- `get_link_summaries`
- `get_relevant_content`
- `get_full_content`
- `list_sections` (local-corpus section index only)
- `summarize_section` (local-corpus section summary only)
- `save_finding`
- `query_research_memory`

When corpus is already preloaded, acquisition tools can be restricted so the model focuses on retrieval/synthesis.

Section-tool policy by source mode:

- `web_only`: `list_sections` and `summarize_section` are not exposed.
- `local_only`: section tools are available.
- `mixed`: section tools are available, but they only accept local corpus handles (`corpus://cache/<id>`).

Section scoping contract:

- Preferred: pass explicit `section_ref` or `section_id`.
- Compatibility: legacy source suffixes like `corpus://cache/<id>/<section-id>` are accepted.
- For retrieval/full-content section scope, do not invent path hacks when `section_ref` is available.

## Recommended Tool Call Pattern (Model)

For section-bounded research answers in local corpus:

1. Call `list_sections(source=\"corpus://cache/<id>\")`.
2. Choose one section using returned `section_ref`.
3. Call `summarize_section(source=\"corpus://cache/<id>\", section_ref=\"...\", detail=\"max\")`.
4. If more depth is needed, call `get_relevant_content` or `get_full_content` with the same `section_ref`.

Example retrieval call shapes:

```json
{"query":"arguments and evidence","urls":["corpus://cache/247"],"section_ref":"corpus://cache/247#section=why-learning-is-still-a-slog-after-fifty-years-o-038"}
```

```json
{"urls":["corpus://cache/247/why-learning-is-still-a-slog-after-fifty-years-o-014"],"query":"examples and caveats"}
```

The second shape is legacy compatibility and still supported, but `section_ref` is preferred.

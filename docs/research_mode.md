# Deep Research Mode

Deep Research Mode (`-r`) is asky’s retrieval-focused workflow for multi-source questions, long documents, and local corpus analysis.

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

## Research Toolset

Research mode exposes retrieval-first tools:

- `extract_links`
- `get_link_summaries`
- `get_relevant_content`
- `get_full_content`
- `save_finding`
- `query_research_memory`

When corpus is already preloaded, acquisition tools can be restricted so the model focuses on retrieval/synthesis.

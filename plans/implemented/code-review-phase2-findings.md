# Phase 2 Findings — Research Mode (Web + Local RAG)

## Audit Summary

All code paths were traced from `-r` flag parsing through session resolution, preload pipeline (query expansion → local ingestion → corpus context → shortlist → evidence extraction), tool registry construction (acquisition exclusion), and the `corpus query`/`corpus summarize` CLI commands. Hybrid search (ChromaDB dense + SQLite BM25), root guards, fail-fast behavior, and background summarization drain were verified.

**Overall verdict: Research mode is well-implemented with comprehensive test coverage. Two magic numbers found, one minor documentation gap.**

---

## Findings

### F1. Evidence extraction heuristic uses a magic number (threshold = 3)
**Priority:** P4 (minor inconsistency — violates codebase style rule)
**Verdict:** Fix Now

**Location:** [preload.py:607](src/asky/api/preload.py#L607)

```python
has_good_shortlist = len(preload.shortlist_payload.get("candidates", []) or []) >= 3
```

The CLAUDE.md rules state: "No magic numbers. Define them as global constants. Add a comment when it's clearer." The threshold of 3 is inline with a comment but should be a named constant.

**Not configurable** — the threshold isn't in `research.toml` and isn't exposed in config exports. The comment explains the "why" but users cannot tune this behavior.

**Fix:** Extract to a module-level constant in `preload.py`:
```python
EVIDENCE_EXTRACTION_SHORTLIST_SKIP_THRESHOLD = 3
```

---

### F2. Hybrid search dense/lexical weight ratio (0.75/0.25) not configurable
**Priority:** P4 (minor inconsistency)
**Verdict:** Accept as-is (Document)

**Location:** [vector_store_common.py:10](src/asky/research/vector_store_common.py#L10)

```python
DEFAULT_DENSE_WEIGHT = 0.75
```

This is correctly a named constant (not a magic number), but it is not exposed in `research.toml`. Users cannot tune the dense-vs-lexical balance without code changes.

Given this is an internal implementation detail with a sensible default, this is acceptable for now. But it could be worth adding to `research.toml` in a future pass.

---

### F3. `local_ingestion_flow.py:103-107` uses `print()` instead of logger
**Priority:** P4 (minor inconsistency — violates code standard)
**Verdict:** Fix Now

**Location:** [local_ingestion_flow.py:103-107](src/asky/cli/local_ingestion_flow.py#L103)

When explicit targets exceed `max_targets`, the code uses `print()` for the warning:
```python
if len(targets) > max_targets:
    print(f"Warning: truncating ...")
```

CLAUDE.md rules state: "No silent failures. Log errors via [System Logger], not `print`." This is a library-layer module (not CLI), so it should use `logger.warning()`.

---

### F4. All documented features verified as implemented ✅

| Claim | Status | Evidence |
|-------|--------|----------|
| `-r` without arg → web research mode | ✅ | `main.py:1286-1288` returns `(True, None, None, None, False)` |
| `-r <path>` → local corpus mode (`local_only`) | ✅ | `main.py:1350-1352` infers `local_only` |
| `-r <path>,web` → mixed mode | ✅ | `main.py:1305-1307` detects `web` token, `1353-1354` returns `mixed` |
| Session-owned research profile persists | ✅ | `session.py:60-108` + `sqlite.py:1313-1339` (JSON column UPDATE) |
| Corpus pointer replacement (not append) on existing session | ✅ | `session.py:95-102` uses `requested_paths` directly |
| Root guard enforced | ✅ | `adapters.py:191,204` uses `path.relative_to(root)` |
| Fail-fast on explicit list / path-like tokens | ✅ | `main.py:1341-1345` raises `ValueError` |
| Lenient mode for ambiguous single tokens | ✅ | `main.py:1347-1348` treats as query start |
| Hybrid search: ChromaDB dense + SQLite BM25 | ✅ | `vector_store_chunk_link_ops.py:606-686`, actual FTS5 BM25 SQL at `vector_store.py:197-206` |
| Query expansion: YAKE deterministic + optional LLM | ✅ | `preload.py:462-481` |
| Evidence extraction: post-retrieval LLM (max 10 chunks) | ✅ | `preload.py:616-653` |
| Source shortlisting: pre-LLM ranking | ✅ | `preload.py:544-575` calls shortlist executor |
| `corpus query` works without session or model | ✅ | `research_commands.py:84-145` — uses cached embeddings/BM25 only |
| `corpus summarize` with detail profiles | ✅ | `section_commands.py:296-429` — compact/balanced/max |
| Background summarization drain | ✅ | `cache.py:590-602` + `chat.py:1025-1030` |
| Acquisition tool exclusion when corpus pre-built | ✅ | `tool_registry_factory.py:379-382` excludes `ACQUISITION_TOOL_NAMES` |
| Local-only mode skips web search | ✅ | `preload.py:516-517` sets `skip_web_search=True` |
| Path redaction in model-visible query | ✅ | `client.py:851-864` calls `redact_local_source_targets()` |
| PDF/EPUB via PyMuPDF | ✅ | `adapters.py:264-280`, `pyproject.toml` dep declared |
| File types: txt, md, html, json, csv, pdf, epub | ✅ | `adapters.py:18-34` constants |

---

### F5. Test coverage is strong

| Area | Test file | Test count |
|------|-----------|------------|
| Hybrid search / vector store | `test_research_vector_store.py` | 39 |
| Local ingestion flow | `test_local_ingestion_flow.py` | 5 |
| Adapters + root guards | `test_research_adapters.py` | 10 |
| Corpus pointer resolution | `test_research_corpus_resolution.py` | 7+ |
| Fail-fast (local_only empty corpus) | `test_api_library.py:536` | 1 |
| Evidence extraction | `test_evidence_extraction.py` | ~10 |
| Section commands | `test_section_commands.py` (if exists) | TBD |

**Gap:** No test for the evidence extraction shortlist-skip heuristic (`>= 3` sources → skip). This is a behavioral decision that should have at least one boundary test.

---

### F6. Cross-phase check: `trace_context` in `research/tools.py._fetch_and_parse()`
**Priority:** — (informational, for Phase 9)
**Verdict:** Already implemented

The Playwright browser plugin plan (Phase 9 cross-check) asked whether `trace_context={"tool_name": "research"}` was added to `_fetch_and_parse`. **It is present** at `tools.py:706`. The Playwright plugin can intercept research fetches.

---

## Action Items

| # | Finding | Action | File |
|---|---------|--------|------|
| 1 | F1: Evidence extraction magic number `3` | Extract to named constant | `src/asky/api/preload.py` |
| 2 | F3: `print()` in library module | Replace with `logger.warning()` | `src/asky/cli/local_ingestion_flow.py` |
| 3 | F5 gap: No test for evidence skip heuristic | Add boundary test (2 sources → run, 3 sources → skip) | `tests/test_evidence_extraction.py` or `tests/test_api_preload.py` |

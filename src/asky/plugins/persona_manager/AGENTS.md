# Persona Manager Plugin (`plugins/persona_manager/`)

Hardened runtime orchestration for grounded persona behavior.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint + hook handlers |
| `runtime_types.py`| Typed runtime models for packets and plan state |
| `runtime_planner.py`| Structured retrieval and multi-level ranking |
| `runtime_grounding.py`| Answer validation and grounded contract (milestone 2) |
| `importer.py` | Persona ZIP import + derived artifact rebuild |
| `knowledge.py` | Legacy embedding build helpers |
| `session_binding.py` | Persistent session-to-persona mappings |

## Milestone-3 Runtime Boundary

Enforces approved-only knowledge usage:
- **Approved Knowledge Only**: Only sources promoted to the canonical catalog are included in the runtime index.
- **Viewpoint Centric**: Primary packets remain limited to `viewpoint` and `raw_chunk`.
- **Query Only**: `persona_fact` and `timeline_event` are available via CLI query but are not injected as primary voice packets.
- **Kind Preservation**: Metadata preserves `source_kind` for formatting and debugging.

## Milestone-2 Grounding Contract

Enforces factual accuracy and citation discipline with separate live-context attribution:
- **Format**: Requires `Answer:`, `Grounding:`, `Evidence:` (for `[P#]`), and `Current Context:` (for `[W#]`).
- **Validation**: Replies that omit required citations, use incorrect grounding labels, or blur persona evidence with live context are replaced with a safe fallback.
- **Fallback**: "I don't have enough grounded persona evidence to answer this reliably." includes a list of available packets.

## Retrieval Strategy

Structured retrieval prioritizes authored-book viewpoints over raw chunks:
1. **Viewpoints**: Worldview claims with automatically hydrated evidence excerpts.
2. **Evidence Excerpts**: Direct supporting quotes.
3. **Raw Chunks**: Fallback knowledge from manual sources.

## Hook Usage

- `SESSION_RESOLVED`: resolve active session and load persisted binding.
- `SYSTEM_PROMPT_EXTEND`: inject behavior prompt and grounding instructions.
- `PRE_PRELOAD`: execute `runtime_planner` to retrieve packets and inject formatted context.
- `POST_TOOL_EXECUTE`: track live current-context sources (web tools) for attribution validation.
- `POST_LLM_RESPONSE`: validate reply against grounding contract, persona packets, and tracked live sources.
- `TURN_COMPLETED`: clear turn-scoped packets and live sources.

## Deterministic Preprocessing

- **@mention**: Syntax `@persona_name` or `@alias` triggers loading before model execution.
- **Mention Removal**: The mention token is stripped from the query text before it reaches the model.

## Invariants

- Schema v3 foundation required for full grounding metadata.
- Automatic catalog rebuild for Schema v1/v2 archives.
- Citation validation ensures cited `[P#]` exist in retrieved context.

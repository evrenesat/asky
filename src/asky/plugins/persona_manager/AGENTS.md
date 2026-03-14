# Persona Manager Plugin (`plugins/persona_manager/`)

Hardened runtime orchestration for grounded persona behavior.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint + hook handlers |
| `runtime_grounding.py`| Answer validation and minimal grounding contract (v3) |
| `importer.py` | Persona ZIP import + legacy catalog rebuild |
| `knowledge.py` | Evidence packet retrieval with full metadata |
| `session_binding.py` | Persistent session-to-persona mappings |

## Minimal Grounding Contract

Enforces factual accuracy and citation discipline:
- **Format**: Requires `Answer:`, `Grounding:`, and `Evidence:` sections.
- **Validation**: Replies that omit required citations or grounding lines are replaced with a safe fallback.
- **Fallback**: "I don't have enough grounded persona evidence to answer this reliably." includes a list of available sources.

## Hook Usage

- `SESSION_RESOLVED`: resolve active session and load persisted binding.
- `SYSTEM_PROMPT_EXTEND`: inject behavior prompt and grounding instructions.
- `PRE_PRELOAD`: retrieve `PersonaEvidencePacket` list and inject formatted context.
- `POST_LLM_RESPONSE`: validate reply against grounding contract and available packets.
- `TURN_COMPLETED`: clear turn-scoped packets.

## Deterministic Preprocessing

- **@mention**: Syntax `@persona_name` or `@alias` triggers loading before model execution.
- **Mention Removal**: The mention token is stripped from the query text before it reaches the model.

## Invariants

- Schema v3 foundation required for full grounding metadata.
- Automatic catalog rebuild for Schema v1/v2 archives.
- Citation validation ensures cited `[P#]` exist in retrieved context.

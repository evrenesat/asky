# Persona Runtime Answering Pipeline (Milestone 2)

This document describes the internal answering pipeline for personas in milestone 2.

## 1. Retrieval Strategy

The runtime uses a structured retrieval planner (`runtime_planner.py`) that reads from the canonical `runtime_index.json`.

### 1.1 Multi-level Priority Ranking
When multiple entries have similar cosine similarity scores, the planner applies these priority rules (lower number = higher priority):

1.  **Entry Kind**:
    *   `viewpoint` (0)
    *   `evidence_excerpt` (1)
    *   `raw_chunk` (2)
2.  **Trust Class**:
    *   `authored_primary` (0)
    *   `user_supplied_unreviewed` (1)
    *   `mixed_attribution` (2)
    *   `third_party_secondary` (3)
    *   `unreviewed_web` (4)
    *   `transcript_unreviewed` (5)
3.  **Source Preference**:
    *   Authored books (0) over Manual sources (1).
4.  **Deterministic ID**:
    *   Alphabetic sort of `entry_id` as a final tie-breaker.

### 1.2 Viewpoint Hydration
Top-ranked `viewpoint` entries are automatically hydrated with their linked `evidence_excerpt` children. The model receives both the high-level claim and the specific supporting quotes in a single packet.

## 2. Grounding Contract

The model is forced to follow a strict reply contract to ensure transparency and reliability.

### 2.1 Format
```text
Answer: <the grounded answer>
Grounding: <direct_evidence | supported_pattern | bounded_inference | insufficient_evidence>
Evidence: <cite [P#] packet ids here>
Current Context: <cite [W#] tool source ids here, only if used>
```

### 2.2 Validation Rules
The runtime validates every persona response before it reaches the user:

*   **Citations Required**: If persona evidence packets were provided, at least one `[P#]` citation must be present in the `Evidence:` section.
*   **Minimum Evidence**: `supported_pattern` requires at least two distinct `[P#]` citations.
*   **Current Context**: If web tools were used during the turn, the model MUST cite them as `[W#]` in the `Current Context:` section.
*   **Synthesis**: `bounded_inference` must be used when both persona packets and live context support the answer.
*   **Insufficiency**: If the model determines it cannot answer based on persona knowledge, it must use `insufficient_evidence` and list the packets it considered.

## 3. Validation Fallback

If a response fails validation, it is replaced with:
`I don't have enough grounded persona evidence to answer this reliably.`

The fallback includes a "Considered Evidence" list so the user can see what information was available to the model and why it might have failed to ground the answer correctly.

## 4. Derived Artifacts

The answering pipeline depends on two rebuildable derived artifacts:
*   `embeddings.json`: Vector store for legacy chunk compatibility.
*   `persona_knowledge/runtime_index.json`: Vector store and structured metadata for the canonical catalog.

Both are excluded from portable persona exports and are automatically rebuilt on import or when knowledge changes.

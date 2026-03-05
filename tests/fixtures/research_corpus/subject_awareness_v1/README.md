# Subject Awareness Corpus v1

This fixture corpus is used by recorded and live research integration tests.

It intentionally contains overlapping references to two subjects:
- Alpha plan: architecture objective and rollout outcomes.
- Beta risk: top operational risk and mitigation.

The tests verify both:
- corpus-grounded retrieval from mixed local sources (`.md`, `.txt`, `.pdf`), and
- follow-up subject awareness (respond to latest user intent without drifting back to prior turn focus).

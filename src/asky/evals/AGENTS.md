# Evals

This directory contains the automated evaluation suites and benchmarking tools for `asky`.

## Responsibilities
- Provides deterministic metrics for tracking regression or improvement across models and prompts.
- Hosts pipeline definitions for specific domains (e.g., the research pipeline).
- Isolates evaluation dependencies from the core library, ensuring test-time behavior does not leak into production code.

## Subdirectories
- `research_pipeline`: Evaluation harness specifically tuned for the multi-step web research mode, evaluating source extraction, summarization, and final synthesis.
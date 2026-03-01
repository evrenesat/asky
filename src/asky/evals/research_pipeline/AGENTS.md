# Research Pipeline Evals

This directory contains the evaluation harnesses specifically focused on `asky`'s research mode.

## Responsibilities
- Defines dataset schemas and assertion logic for testing multi-step web research queries.
- Manages source provider stubs (mocking live HTTP fetch) for deterministic evaluation.
- Implements evaluators to score evidence extraction, relevance, and final synthesis outputs against a ground truth or heuristic rubric.

## Architecture
- `dataset.py`: Defines the evaluation inputs (questions, expected domains, target concepts).
- `evaluator.py`: Orchestrates the run of a query against the standard research flow, capturing intermediate tool calls and outputs.
- `assertions.py`: Contains the logic to score a pipeline run (e.g., did the shortlist contain the target concept?).
- `source_providers.py`: Adapters to inject static or cached content into the Playwright/HTTP fetching layers.
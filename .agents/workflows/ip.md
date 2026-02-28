---
description: Implement plan
---

Strictly follow and apply the directives given in this plan file:

- ALWAYS create a plan first.
- Even for minor changes, first ask user for confirmation about proceeding without a plan!
- NEVER directly continue to implementation, without user clicks "Proceed" button or sends a "proceed" message explicitly.

## When you are creating an IMPLEMENTATION PLAN

When creating implementation plans for coding agents, follow these rules. Agents are literal executors — every gap is a shortcut opportunity.

### Structure

1. **Define "done"** — Describe the end state, not the change. Include observable behavior (HTTP responses, CLI output, UI state).
2. **List every file** — Name each file to create, modify, or delete. If unknown upfront, specify the search/grep the agent must run first to discover them.
3. **Show before/after** — For each change, describe what exists now and what it should look like after. Don't rely on "add X" without anchoring where and re$
4. **Sequential atomic steps** — Number every step. Each step: one concern, independently verifiable. State dependencies between steps explicitly (e.g., "Ste$
5. **Pin assumptions** — Language version, library versions, algorithms, config values, data shapes. Anything unspecified will be improvised.
6. **Explicit constraints (what NOT to do)** — Anticipate shortcuts: no hardcoded values, no global catches, no skipped error handling, no unlisted dependenc$
7. **Edge cases as requirements** — List them. Unmentioned edge cases will be ignored.
8. **Verification commands** — Per-step and final. Give exact commands: test runs, curl calls, grep checks. No verification = agent assumes it's done.
9. **Final checklist** — Flat binary list: tests pass, no debug artifacts, no commented-out code, type hints present, docs updated, etc.

### Key Principles

- Be specific over concise. A 40-line plan that's unambiguous beats a 15-line plan with gaps.
- Describe boundaries, not just goals. Constraints prevent drift more than instructions drive correctness.
- Treat every omission as implicit permission to skip.

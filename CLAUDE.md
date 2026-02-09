# AI Agent Guidelines

Note: I always use speech-to-text dictation, so beware the mistakes, misunderstandings. When in doubt, ask for clarification, do not assume!


## Before Starting Work/Planning
- Always read `ARCHITECTURE.md` at the start of a new session.
- Update `ARCHITECTURE.md` whenever code structure, data flow, or key components change.
- In subdirectories of the project, if exists, read the AGENTS.md files. 
- Read DEVLOG.md - Understand recent changes and current issues
- Review related code - Understand how components interact
- Run run whole test suite. - So you'd be sure if your changes creates a regression or not.
- When in planning mode, alwasy show me your -revised- plan and wait for me to use the "Proceed" button.

## After Completing Work

- **Update DEVLOG.md** with:
   - Date and summary
   - What was changed and why
   - Any gotchas or follow-up work needed
- **Update documentation** If there is an AGENTS.md file in the subdirectory you have worked in, update the file according to architecture/behavior changes you have made.
- Run run whole test suite.
- **Add/Update unit tests** Add new tests or extend existing test cases to cover the new features you've added.
- Whenever possible handle "manual testing" yourself. Only if it is not possible for you to observe or test the results yourself, if it's really outside of your capabilities then ask user.


## Basic Rules:
- For Python package management, always use `uv`, `uv pip`, never directly use `pip`.
- Crete temporary, reproduction or testing files under "temp" directory or prefix them with "temp_", so they would be automatically gitignored.
- To delete temporary files you've created, you are allowed to use `~/bin/delete-temp-files` command without any argument, if the file name(s) starts with "temp_", they all will be deleted.
- No magic numbers. Define them as global constants. Add a comment when it's clearer.

## Basic Rules:
- For Python package management, always use `uv`, `uv pip`, never directly use `pip`.
- Crete temporary, reproduction or testing files under "temp" directory or prefix them with "temp_", so they would be automatically gitignored.
- To delete temporary files you've created, you are allowed to use `~/bin/delete-temp-files` command without any argument, if the file name(s) starts with "temp_", they all will be deleted.
- No magic numbers. Define them as global constants. Add a comment when it's clearer.

## Core Principles

### Clarity & Autonomy
- **Major Decisions:** Never assume requirements for architectural changes or public APIs. explicitly ask for clarification.
- **Minor Decisions:** For internal implementation details (variable names, small helpers), use best judgment and standard conventions to maintain momentum.

### File Organization
- **Temporary Files:** ALL debug/scratch files go to `temp/`.
- **Tests:** Only modify `tests/` when explicitly requested.
- **New Dependencies:** Ask for permission before adding packages/libraries.

## Code Standards

### Style & Syntax
- **Consistency:** Match the existing coding style (naming conventions, indentation) of the current file.
- **Type Safety:** Use type hints/TypeScript interfaces for all function signatures.
- **Error Handling:** No silent failures. Log errors via [System Logger], not `print`.
- **Readable Functions**: Function/method bodies should be as small as possible. 
  Instead of explaining complex logic with comments, extract a function with a good name and docstring.
- **No magic numbers**: Define them as global constants, add a comment when it makes it clearer.

### Documentation (The "Why")
- **DO:** Explain architectural decisions and complexity (e.g., "Using Set for O(1) lookup").
- **DON'T:** Add chat meta-data (e.g., "User asked for this").

## Workflow

### Implementation Plans
Before writing complex code, propose a plan:
1. **Objective:** What are we solving?
2. **Proposed Changes:** List of files and specific changes.
3. **Verification:** How will we test this?
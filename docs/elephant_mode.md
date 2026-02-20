# User Memory & Elephant Mode

**asky** features a persistent memory system that evolves with your conversations. Instead of starting from scratch every time, asky can remember facts, preferences, and project details across different sessions and terminal invocations.

## Two Types of Memory Concepts

Memory in asky operates on two levels:

1. **Session-Scoped Fact Extraction:** Memories learned in a specific session (e.g., using `--sticky-session "ProjectX"`) are isolated to that session by default. This is perfect for project-specific contexts that you don't want leaking into your general queries.
2. **Global Memory:** Facts that are universally true about you (e.g., "I prefer Python", "My name is Alice") are stored globally and injected into every single conversation you have with asky, regardless of the active session.

## How to Save Memories

There are three main ways asky learns:

### 1. Manual Explicit Prompts (Global)

You can explicitly command asky to remember something globally by using a trigger phrase (like "remember globally:" or "global memory:").

```bash
asky "remember globally: I always prefer clean architecture"
```

The CLI detects this trigger, strips it from the prompt, and extracts the fact directly into your global knowledge base. This guarantees the fact will be available in all future sessions.

### 2. Manual Agent Action (Session or Global)

During any standard conversation, the LLM has access to a `save_memory` tool. If it detects a strong user preference or an important fact during your chat, it can proactively decide to save it. If you are in a session, it saves it to the session scope. If you are not in a session, it saves it globally.

```bash
asky "For this project, we are using Python 3.12."
# The agent might autonomously call `save_memory` with this fact.
```

### 3. Elephant Mode (Auto-Extraction)

Elephant mode (`-em` or `--elephant-mode`) is a background feature that automates memory building. When active, after your conversation turn finishes, asky spins up a background daemon thread. This thread reviews the conversation that just happened and extracts key facts specifically for the current session.

```bash
# Elephant mode requires an active session to be useful
asky -ss "API Rewrite" -em "Let's plan the new endpoint. It should use gRPC."
```

_Note: Because extraction runs in the background, it never blocks you from getting your answer quickly._

## How Memory is Recalled

Every time you send a query, asky searches your saved memories for highly relevant facts using a cosine similarity threshold.

If it finds relevant memories (either Global memories, or memories scoped to your current active session), it invisibly prepends them to the System Prompt under a `## User Memory` section. The LLM then uses this context to tailor its response to you.

_Exception: If you run asky in Lean Mode (`-L`), memory recall is skipped to provide a completely vanilla model response._

## Managing Memories

You can manage your saved memories directly from the CLI:

- **List all memories:** Understand what asky currently knows about you.
  ```bash
  asky --list-memories
  ```
- **Delete a specific memory:** Use the ID provided by the list command.
  ```bash
  asky --delete-memory 5
  ```
- **Clear everything:** Wipe all saved memories entirely.
  ```bash
  asky --clear-memories
  ```

## Technical Details

- **Storage:** Memories are stored as raw text in a local SQLite table (`user_memories`).
- **Indexing:** They are simultaneously indexed into a ChromaDB vector database collection (`asky_user_memories`) for fast semantic retrieval.
- **Deduplication:** When a new memory is saved, asky checks for existing facts with a very high similarity score (>0.90). If a duplicate is found, it updates the existing memory rather than creating redundant entries.

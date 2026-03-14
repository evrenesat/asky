# Persona Feature Set Handoff Summary

## What This Is

This is a product-level summary of the persona feature direction, based on the original feature description plus the later roadmap clarifications. It is meant to travel together with:

- [persona-roadmap.md](persona-roadmap.md)

This summary is not an implementation plan. It explains the intended product behavior, the reasoning behind it, the intended milestone order, and the non-goals that should stay stable across future sessions.

## Core Product Goal

The goal is to build a persona system that can answer as a real thinker, scientist, politician, philosopher, or other public figure in a way that feels deep, grounded, and evidence-based.

The key idea is:

- the persona should not be simulated from a large injected prompt,
- the persona should be grounded in actual artifacts created by or about that person,
- the runtime should retrieve and reason over stored persona knowledge instead of stuffing everything into the model context,
- the system should support both direct retrieval of what the persona actually said and bounded inference about what the persona would likely think about a newer topic.

This is meant to be materially better than the “persona mode” found in many current AI interfaces.

## Why Existing Persona Approaches Are Not Enough

The current common pattern in AI products is to create personas by injecting extra text into the prompt or context window. That is not enough for the intended feature set here.

Main limitations of prompt-injected personas:

- they are constrained by model context size,
- the same context window must also hold the user’s actual question and current topic,
- they do not scale to large bodies of work,
- they encourage shallow style imitation rather than grounded worldview retrieval,
- they make it hard to distinguish evidence from free-form model invention.

The intended system should instead externalize most persona knowledge into a retrievable knowledge layer and only bring in the relevant parts at answer time.

## Target Architecture Direction

The main path is a RAG-based persona system backed by a vector database or equivalent retrievable store.

Important direction:

- the system stays vector-first for now,
- graph DB ideas are acknowledged as potentially useful later, but not required on the critical path,
- raw source material may be temporarily stored for retrieval during ingestion,
- the durable result should be a richer persona knowledge base, not just raw embedded chunks.

The retrieval/runtime model should support:

- entry points into persona knowledge,
- gradual narrowing into relevant topics,
- retrieval of direct supporting passages,
- retrieval of structured worldview or position entries,
- bounded inference when the topic is new and the persona never directly addressed it.

## What The Persona Should Ultimately Be Able To Do

The target user experience is something like:

1. A user creates a persona from real source material.
2. The system extracts that person’s views, concepts, recurring themes, and relevant facts.
3. The user can ask:
   - what this person thought about a known topic,
   - how this person framed a recurring issue,
   - what this person would likely think about a recent event,
   - or conduct a discussion with the persona that remains rooted in the person’s actual body of work.
4. The answer should distinguish:
   - direct evidence,
   - repeated patterns or positions across sources,
   - inferred but bounded extrapolation.

The desired tone is not “roleplay first”. It is “grounded worldview retrieval first, persona voice second”.

## Knowledge Model Expectations

The system should eventually store more than chunks of text.

The intended extracted knowledge includes:

- viewpoints or positions on subjects,
- explicit claims,
- recurring themes,
- definitions or distinctions the persona makes,
- uncertainty or ambiguity markers,
- persona facts when the source type supports them,
- provenance for every extracted item.

Every promoted knowledge item should ideally carry:

- source artifact identity,
- passage or section reference,
- extraction confidence,
- supporting evidence excerpts,
- source trust class,
- enough metadata to reason about contradictions later.

## Runtime Answering Expectations

The runtime should not pretend the persona directly commented on a topic when there is no evidence.

Expected runtime behavior:

- retrieve structured persona knowledge first,
- retrieve supporting raw passages as needed,
- clearly separate direct evidence from interpretation,
- allow bounded inference for recent events or unseen topics,
- say when the evidence is insufficient instead of free-simulating.

For recent-event questions specifically:

- the system should combine current topic context with the persona’s known worldview,
- then produce a cautious, evidence-backed inference,
- not fabricate direct statements from the persona.

Visible evidence or citations should be the normal behavior, not an optional advanced mode.

## Ingestion Philosophy

Ingestion is not meant to be “throw documents into embeddings and call it done”.

The intended ingestion model is source-aware and multi-pass:

- first capture enough source structure for retrieval,
- then perform deeper extraction passes,
- then produce reusable persona knowledge entries,
- then report coverage and quality signals.

The ingestion flow should expose real expectations and tradeoffs to the user:

- how much content is being processed,
- what the system expects to extract,
- whether user-provided expectations should modify those targets,
- where coverage seems weak,
- when the result is incomplete.

CLI-first is acceptable early, but backend logic must be reusable later by a web UI.

## Source Types And Their Intended Handling

### 1. Authored Books, first priority

This is the first and most important ingestion mode.

The user should be able to provide a book written by the persona. The system should ingest it through a relatively slow and potentially expensive process, not a lightweight embedding-only path.

Intended authored-book flow:

- accept a local book file,
- temporarily ingest enough of the book for retrieval,
- run hierarchical summarization and topic discovery,
- run repeated extraction passes over the book,
- produce structured persona knowledge entries,
- report coverage against expected extraction targets.

The book should not just become a pile of searchable chunks. The point is to extract what the persona thinks about the subjects in the book.

### 2. Biographies and autobiographies

These are close to book ingestion, but should not be treated exactly the same way.

Why they differ:

- the whole artifact is about the persona,
- some information is authored by the persona, some is not,
- these sources can contribute both worldview information and facts about the persona,
- attribution needs to stay explicit.

The extraction process should be adjusted accordingly and should preserve source type and trust class.

### 3. Short-form authored material

This includes things like:

- articles,
- essays,
- speeches,
- interviews,
- notes,
- collections of shorter texts,
- the current shorter-source ingestion path once hardened.

These should feed into the same knowledge model as books, even if the pipeline is lighter weight.

### 4. Guided web scraping

The roadmap includes targeted web scraping, but not as an autonomous free-for-all.

Expected flow:

- user provides one or more URLs or a list of URLs,
- the system gathers likely relevant material,
- the system presents findings before final ingestion,
- the user reviews and confirms before promotion into persona knowledge.

This is especially important because web sources vary a lot in trust and attribution.

### 5. YouTube, podcasts, and other audio/video

This is intentionally later.

Expected eventual capabilities:

- download and transcribe relevant video/audio,
- support non-English transcription,
- later support speaker separation and diarization,
- distinguish between:
  - the persona speaking,
  - someone else talking about the persona,
  - mixed conversations involving the persona.

Diarization is considered the most complex and should be late in the roadmap.

## Detailed Expectations For The First Major Ingestion Mode, Authored Books

This is the most specific part of the original description and should stay stable.

The authored-book ingestion pipeline should:

- be slow if necessary,
- use capable models where needed,
- not reduce the process to plain embeddings,
- let the system extract many topic-centered knowledge entries from a single long-form work.

The user also wanted the system to reason about expected yield.

That means the pipeline should estimate things like:

- expected number of topics,
- expected number of knowledge entries,
- whether extraction coverage looks too thin for the book size,
- whether the user wants to tighten or relax those expectations before the run.

The pre-ingestion UX should support:

- system-proposed extraction targets based on book size or structure,
- optional user adjustments,
- optional user expectations about what they care about in the book,
- later richer UX in a web interface,
- but a CLI-first version is acceptable as the first delivery step.

## Review And Governance Expectations

Different source types deserve different levels of trust and review.

Expected policy direction:

- authored books can be more automatic in the first milestone,
- biographies and mixed-attribution sources need more careful extraction policies,
- scraped web material should be review-gated before knowledge promotion,
- later UI should allow source review, provenance inspection, scoring, and removal.

The system should preserve contradictions and disputes rather than flattening them away.

## Milestone Order The Next Session Should Preserve

The intended sequence is:

1. Baseline hardening and persona data foundation
2. Local authored-book ingestion
3. Persona runtime and evidence-backed answering
4. Biographies, autobiographies, and short-form ingestion
5. Guided web scraping and source review
6. Browser-assisted acquisition for restricted sites
7. Persona review console and web-based workflow
8. YouTube, podcasts, multilingual transcription, and diarization

Graph DB work is a research track, not a mainline prerequisite.

## Current Product Priorities To Preserve

The next session should keep these priorities intact:

- local authored-book ingestion is the first major milestone,
- the system must remain reusable for a future web UI,
- persona behavior must be evidence-grounded, not prompt-injected,
- provenance and trust boundaries matter from the start,
- the runtime must support bounded inference, not unconstrained persona simulation,
- graph DB exploration is optional and later.

## Things The Next Session Should Not Accidentally Regress Into

Avoid collapsing this work into:

- “persona = longer system prompt”
- “persona = search raw chunks and answer in a style”
- “just add more embeddings”
- “simulate the persona without showing evidence”
- “treat all source types as equivalent”
- “mix third-party commentary into trusted persona knowledge without review”

Those are explicitly not the intended direction.

## Open Questions That Remain Legitimately Open

These topics were acknowledged but not locked:

- whether a graph DB eventually adds enough value to justify the complexity,
- how exactly the future review UI should look,
- what the final eval harness should measure in detail,
- how aggressive the system should be in extrapolating to current events,
- how sophisticated the later diarization and multilingual audio pipeline should become.

Those remain open, but they should not block the current roadmap.

## Suggested Handoff Use

If another session or another machine is picking this up, the recommended handoff bundle is:

1. This summary
2. [persona-roadmap.md](/Users/evren/.codex/worktrees/63c0/asky/plans/persona-roadmap.md)
3. [persona-milestone1-authored-book-ingestion-ralf.md](/Users/evren/.codex/worktrees/63c0/asky/plans/implemented/persona-milestone1-authored-book-ingestion-ralf.md)

The summary explains the product intent.
The roadmap explains milestone order.
The milestone plan explains the authored-book implementation contract.

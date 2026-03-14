# Persona Roadmap

## Summary

Build a persona system that can answer as a real-world thinker or public figure in a way that is grounded in actual artifacts, not just a long injected prompt. The target end state is an evidence-backed persona runtime that:

- stores persona knowledge outside the main model context,
- uses RAG as the primary retrieval architecture,
- stays vector-first on the main path,
- shows visible evidence/citations in normal replies,
- allows bounded inference when evidence is partial,
- starts with local authored-book ingestion as the first new feature milestone.

This roadmap is intentionally not an implementation plan. Each milestone should later get its own implementation plan.

## Current State

Today’s persona feature is still a thin baseline:

- Persona behavior is mostly system-prompt extension plus top-k chunk retrieval from a local `embeddings.json`.
- Persona knowledge is stored as raw chunks, not as structured positions, facts, themes, or provenance-rich claims.
- There is no persona-specific evaluation harness for groundedness, attribution quality, or inference discipline.
- There is no dedicated review UI for persona knowledge.
- The shipped CLI surface likely needs baseline hardening before new feature work:
  - `persona add-sources` currently imports `asky.research.ingestion`, which does not exist in this checkout.
  - existing recorded CLI tests for persona ingestion only assert command exit status, so they may miss real ingestion failures.
- Docs around persona entrypoints are partly stale and still reference older tool-driven behavior.

## Target Product Goal

The roadmap should converge on a persona system that supports this user experience:

1. A user creates a persona from authored works and other persona-related sources.
2. The ingestion pipeline extracts reusable persona knowledge, not just embeddings of the raw text.
3. The runtime can answer:
   - what this persona explicitly said about a topic,
   - what themes or positions recur across sources,
   - what the persona would likely think about a newer topic, with bounded inference and visible evidence.
4. The system clearly distinguishes:
   - direct evidence,
   - attributed interpretation,
   - speculative extrapolation.
5. Higher-risk sources such as web scraping and third-party commentary remain review-gated before they become trusted persona knowledge.

## Milestones

### Milestone 0: Baseline Hardening And Persona Data Foundation

Purpose: make the current persona surface real and measurable before layering in expensive ingestion.

Outcomes:

- Stabilize current persona ingestion and loading paths.
- Replace “raw chunks + embeddings only” as the implicit product model with an explicit persona knowledge model.
- Add persona-specific evaluation scaffolding for:
  - source grounding,
  - citation presence,
  - incorrect attribution,
  - unsupported inference,
  - answer usefulness.
- Define source classes and trust levels:
  - authored by persona,
  - direct interview/conversation,
  - biography/autobiography,
  - third-party commentary,
  - scraped social/web artifacts,
  - audio/video transcripts.
- Define the canonical distinction between:
  - persona facts,
  - persona viewpoints/positions,
  - evidence snippets,
  - extraction metadata,
  - runtime-generated inferences.

Why this precedes new ingestion:

- The current persona surface is not yet strong enough to serve as the base for book-scale extraction.
- Without evaluation and provenance contracts, later milestones will drift into “better embeddings” rather than a grounded persona system.

### Milestone 1: Local Authored-Book Ingestion

Purpose: ingest a book written by the persona and convert it into structured persona knowledge.

This is the first new feature milestone.

User-facing result:

- A user can provide a local book file and start a persona-book ingestion flow from the CLI.
- The system performs a slow, multi-pass extraction pipeline rather than a simple embedding-only ingest.
- The first release can run automatically for authored books, without mandatory human review before acceptance.

Pipeline goals:

- Accept long-form local inputs using the existing local-source ecosystem where possible.
- Store the raw book content temporarily in the vector/retrieval layer for passage access during extraction.
- Run hierarchical summarization and topic discovery over the book.
- Generate candidate knowledge entries such as:
  - positions on topics,
  - recurring concepts,
  - definitions/distinctions,
  - explicit claims,
  - uncertainty or ambiguity markers.
- Attach provenance to each entry:
  - source artifact,
  - chapter/section or passage handle,
  - extraction confidence,
  - evidence passages.
- Produce ingestion coverage signals such as:
  - expected vs extracted topic count,
  - expected vs extracted knowledge-entry count,
  - low-coverage warnings,
  - unresolved sections.

Non-goals for this milestone:

- No graph DB requirement.
- No review UI requirement.
- No web scraping.
- No diarization.

### Milestone 2: Persona Runtime And Evidence-Backed Answering

Purpose: use the new knowledge model in actual persona conversations.

User-facing result:

- A loaded persona can answer in persona voice with visible evidence/citations by default.
- The runtime can separate:
  - “the persona directly said this,”
  - “this is a pattern supported by multiple sources,”
  - “this is a bounded inference from the persona’s known views.”

Runtime behavior:

- Query planning should retrieve from structured persona knowledge first, then raw evidence passages as needed.
- Retrieval should be topic-aware and support gradual narrowing into relevant subtopics.
- Recent-event questions should trigger a two-part reasoning flow:
  - retrieve persona worldview and relevant source-backed positions,
  - combine that with the current topic/event context to produce a bounded inference.
- When grounding is insufficient, the runtime should say so instead of free-simulating.

Acceptance criteria for the roadmap:

- Persona answers are materially different from simple prompt injection.
- Citation visibility is normal behavior, not an advanced mode.
- Unsupported claims become an explicit failure condition in evals.

### Milestone 3: Biographies, Autobiographies, And Short-Form Manual Ingestion

Purpose: expand beyond authored books while preserving provenance and trust boundaries.

User-facing result:

- Users can ingest:
  - biographies,
  - autobiographies,
  - interviews,
  - essays,
  - articles,
  - speeches,
  - shorter collections of posts or notes.

Key roadmap additions:

- Extraction prompts and schemas must vary by source class.
- Biography-style sources should extract:
  - persona facts,
  - timeline/context,
  - attributed viewpoints,
  - conflicts or disputed claims.
- Short-form authored artifacts should merge into the same knowledge model as books.
- Contradictions across sources should be preserved as first-class information, not flattened away.

Review policy:

- Light manual flows can stay streamlined.
- Higher-risk or mixed-attribution sources should be reviewable before promotion into trusted persona knowledge.

### Milestone 4: Guided Web Scraping And Source Review

Purpose: support targeted web collection without silently polluting persona knowledge.

User-facing result:

- Users can submit one or more URLs or a URL list for persona-related collection.
- The system crawls and summarizes candidate findings before ingestion.
- For scraped sources, user review happens before knowledge promotion.

Roadmap scope:

- Start with guided, targeted scraping, not autonomous internet-wide persona research.
- Add a review stage that shows:
  - what pages were found,
  - how they were classified,
  - whether the page is authored by the persona or merely about them,
  - what candidate knowledge would be extracted.
- Preserve source trust class and provenance through the entire pipeline.

This milestone should likely split into two delivery slices:

- public/static web scraping,
- authenticated/browser-assisted scraping.

### Milestone 5: Browser-Assisted Acquisition For Restricted Sources

Purpose: collect persona material from sites that are not reliably accessible through simple HTTP fetching.

User-facing result:

- Users can use the existing browser-plugin direction to maintain authenticated site state.
- Guided persona scraping can reuse that browser path for supported sites.

Why this is not earlier:

- Browser-assisted scraping adds operational complexity, site brittleness, and maintenance cost.
- It should build on top of the guided review model from Milestone 4, not replace it.

### Milestone 6: Persona Review Console And Web-Based Workflow

Purpose: improve usability and governance once the ingestion model is proven.

User-facing result:

- The GUI server exposes persona-focused pages for:
  - job submission,
  - ingestion status,
  - threshold tuning,
  - source review,
  - entry scoring/removal,
  - provenance inspection.

Roadmap posture:

- CLI-first remains valid for early milestones.
- The web UI becomes important once persona knowledge is structured and reviewable.
- The UI should operate on stable backend ingestion/runtime contracts, not invent separate logic.

### Milestone 7: YouTube, Podcasts, Multilingual Transcription, And Diarization

Purpose: add audio/video persona sources after the core knowledge model is stable.

User-facing result:

- Users can ingest public video or podcast material into persona knowledge workflows.
- The pipeline can eventually distinguish:
  - the persona speaking,
  - other speakers,
  - commentary about the persona.

Delivery order inside this milestone:

- public transcript acquisition and single-speaker transcription,
- multilingual transcription support,
- speaker separation/diarization,
- mixed-speaker attribution logic for conversations and commentary.

This is intentionally late:

- diarization is expensive, error-prone, and architecture-shaping,
- multilingual audio adds model/runtime complexity,
- attribution mistakes here are especially dangerous for persona quality.

### Ongoing Research Track: Graph Augmentation

Purpose: explore whether graph-style storage meaningfully improves persona retrieval and inference.

Main-path decision:

- Do not block the roadmap on graph DB adoption.
- Stay vector-first for the main implementation path.

Research questions:

- Does a graph help enough with topic relationships, contradiction tracking, or source lineage to justify new infra?
- Can graph-style edges be modeled first in relational/vector storage before adopting a dedicated graph database?
- Which runtime problems actually remain unsolved after Milestones 1-4?

Graph work should only move onto the main path if it proves a clear quality advantage.

## Cross-Cutting Requirements

These are not separate milestones. They should shape every milestone.

### Knowledge Model

The roadmap needs one stable persona knowledge contract that can survive across source types. It should support at least:

- source class and trust level,
- authored-vs-third-party distinction,
- evidence snippets and passage handles,
- structured topics/themes,
- direct quote or paraphrase markers,
- contradiction tracking,
- confidence/coverage fields,
- runtime inference status.

### Retrieval And Runtime Policy

- Structured persona knowledge and raw passages should both be retrievable.
- Runtime prompting should enforce bounded inference and visible evidence.
- Retrieval should prefer higher-trust authored material when available.
- Recent-event persona answering requires combining current-event context with persona worldview retrieval, not pretending the persona literally commented on the event.

### Ingestion Operations

- Long-running ingestion must be resumable and inspectable.
- Expensive jobs need explicit cost and progress visibility.
- Thresholds and extraction expectations must be configurable, even if early UX is CLI-based.
- Failed or low-coverage ingests should degrade into inspectable reports, not silent partial success.

### Evaluation

- Persona-specific evals should begin in Milestone 0 and grow with each milestone.
- Evals should measure:
  - citation presence,
  - evidence relevance,
  - attribution correctness,
  - unsupported inference rate,
  - contradiction handling,
  - answer usefulness.

### Packaging And Portability

- Current persona package/export assumptions will likely need revision once personas contain structured knowledge instead of only prompt plus chunks.
- Portability should preserve provenance and structured entries, while avoiding unnecessary storage of transient runtime indexes.

## Major Risks

### Product Risks

- Persona answers may still collapse into style roleplay unless the runtime explicitly distinguishes evidence from inference.
- Book extraction may be expensive without yielding enough reusable knowledge density.
- Newer-topic questions may invite overconfident speculation.
- Third-party sources may contaminate the persona voice if trust boundaries are weak.

### Technical Risks

- The current persona baseline is probably too brittle to serve as-is.
- Storage schema churn is likely if the knowledge model is not locked early.
- Long-running extraction jobs need resumability, backpressure, and failure recovery.
- Retrieval quality may plateau if structured knowledge and raw evidence are not indexed in complementary ways.
- Browser-assisted scraping and diarization both introduce high-maintenance integrations.

### Operational And Safety Risks

- Copyright and licensing constraints differ across books, websites, transcripts, and exported persona packages.
- Persona outputs can misattribute beliefs, especially when biographies or commentary are mixed with authored materials.
- Multilingual transcription and diarization errors can silently create false knowledge.
- Review load can become unmanageable if every ingestion mode requires the same manual process.

## Sequencing Rules

- The first new feature milestone is local authored-book ingestion.
- Persona runtime comes immediately after that, before broadening ingestion channels.
- Web scraping stays review-first.
- Browser-assisted scraping comes after guided scraping, not before it.
- Review UI follows stable backend contracts rather than driving backend design.
- Diarization is a late-stage capability, not a dependency for early persona value.

## Assumptions Locked For This Draft

- “RUG” was intended to mean RAG.
- The main path stays vector-first; graph DB is a research track, not a requirement.
- Persona runtime uses bounded inference, not free simulation.
- Visible evidence/citations are default behavior.
- Authored-book ingestion can be initially automatic.
- Scraped web sources require review before knowledge promotion.
- CLI-first is acceptable for early milestones; GUI is later.
- This roadmap excludes a persona hub or marketplace as a core milestone.

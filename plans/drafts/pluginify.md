Plugin Migration Proposal

  This is a research/design document — no code changes. Candidates rated by value of extraction vs cost of extraction.

  ---
  Framing the question correctly

  "Should X be a plugin?" has two distinct benefits:
  1. Optional loading — users who don't need it don't pay the import tax or library dependency
  2. Encapsulation — even if always enabled, grouping the code makes boundaries explicit and the feature deletable

  Both are valid goals. The plan below separates them.

  ---
  Candidate Tier List

  Tier 1 — High value, low cost (obvious targets)

  Email sending (email_sender.py, 149 LOC)

  What it is: Post-answer SMTP delivery. Only activated when --mail flag is passed.

  Current wiring: One lazy import in cli/chat.py after the answer is produced. No tool registration. No hook involvement. Config comes from general.toml.

  Plugin shape: Registers a POST_TURN_RENDER hook handler (currently defined but never fired — see below). activate() could also register the --mail arg extension, or alternatively
  that stays in core as a pass-through arg that the plugin reads from context.

  Trade-offs:
  - Net LOC change: ~+30 lines (plugin wrapper, activate, hook registration). The feature code itself doesn't change.
  - Performance: zero — already lazy-imported, hook fires only when arg is set
  - Risk: very low

  Verdict: Do it. The only blocker is that POST_TURN_RENDER hook needs to be implemented first (a small addition to api/client.py).

  ---
  Browser HTML rendering (rendering.py, 345 LOC)

  What it is: Writes an HTML archive of answers and optionally opens the browser. Activated by --browser / --open flags.

  Current wiring: Called in cli/chat.py and also in cli/history.py / cli/sessions.py for --open on historical answers. The history/sessions paths are a complication.

  Plugin shape: Hook into POST_TURN_RENDER for the main chat path. The history/sessions path (--open on a past answer) doesn't naturally fit a hook — it would remain a direct import
   there, or the plugin could expose a callable the CLI uses.

  Trade-offs:
  - Net LOC change: ~+40 lines
  - The cli/history.py + cli/sessions.py usage makes this a partial extraction — the rendering function itself moves, but some callers stay
  - No external library deps (stdlib only), so the "I don't want this dep" motivation doesn't apply
  - Still valuable for encapsulation

  Verdict: Good candidate, but POST_TURN_RENDER hook is the prerequisite. The history/sessions usage makes it slightly messier than email.

  ---
  Push data / webhooks (push_data.py, 247 LOC)

  What it is: Sends answers to configured HTTP endpoints. LLM-callable via dynamically registered tools, also triggerable post-turn via --push.

  Current wiring: core/tool_registry_factory.py imports get_enabled_endpoints() eagerly to decide which tools to register. cli/chat.py also calls it post-turn. Config comes from
  general.toml.

  Plugin shape: This is the most "plugin-ready" feature in the codebase. TOOL_REGISTRY_BUILD hook registers the push tools. POST_TURN_RENDER handles the --push path. activate()
  reads endpoint config.

  Trade-offs:
  - Net LOC change: ~+50 lines (plugin wrapper + two hook registrations)
  - The eager import in tool_registry_factory.py (from asky.push_data import get_enabled_endpoints) goes away — small startup improvement
  - Users who don't configure any endpoints get slightly faster startup

  Verdict: Do it. Natural fit, already follows the tool-registration pattern.

  ---
  Tier 2 — High value, moderate cost

  User memory (memory/, 833 LOC)

  What it is: Cross-session embedding-based memory. save_memory tool for the LLM + recall injected into system prompt + optional auto-extraction.

  Current wiring: Three touch points —
  1. api/preload.py: if USER_MEMORY_ENABLED: recall_memories(...) — guarded by a config flag
  2. core/tool_registry_factory.py: registers save_memory tool via lazy import
  3. cli/memory_commands.py: standalone CLI commands (asky memory list, etc.)

  The USER_MEMORY_ENABLED config flag already acts as a kill switch. The preload call is lazy (via call_attr()). The tool registration is lazy.

  Plugin shape:
  - SYSTEM_PROMPT_EXTEND hook: inject recalled memories
  - TOOL_REGISTRY_BUILD hook: register save_memory tool
  - TURN_COMPLETED hook: trigger background auto-extraction (requires implementing TURN_COMPLETED fire in api/client.py)
  - CLI commands (memory_commands.py) could either stay in core (they import storage directly) or move into the plugin

  What gets harder: The USER_MEMORY_ENABLED config-gate in preload.py has to become "plugin not loaded → no recall", which is the same effect but achieved differently. The
  auto_extract.py path currently runs as a background thread started in cli/chat.py — that would need TURN_COMPLETED to be emitted.

  Trade-offs:
  - Net LOC change: ~+60 lines (plugin class, hook registrations) — the memory module itself stays unchanged
  - Performance: no regression — already lazy
  - chromadb + sentence-transformers are heavy deps. If memory is a plugin, a user who never wants memory saves those deps at install time (they'd move to optional extras)
  - Risk: moderate — three call sites need updating

  Verdict: High value, especially for the dep isolation. Should be Tier 1 if you care about installation size. The main work is implementing TURN_COMPLETED emission.

  ---
  Tier 3 — Moderate value, high cost (design work needed)

  Research pipeline (research/, ~8100 LOC)

  This is the most complex analysis, so it gets the longest section.

  What it is: The RAG pipeline — URL fetching/chunking/embedding, vector search, BM25, shortlisting, section indexing, local corpus ingestion. Also includes the evidence extraction
  LLM pass.

  Current wiring — 12 import sites across 7 files:

  ┌───────────────────────────────┬──────────────────────────────────────────────────────┬─────────────────────────┐
  │             File              │                       Imports                        │         Nature          │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ core/tool_registry_factory.py │ ACQUISITION_TOOL_NAMES, RESEARCH_TOOL_SCHEMAS        │ Eager top-level import  │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ api/preload.py                │ run_research_retrieval, run_shortlist_pipeline, etc. │ Lazy via call_attr()    │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ api/client.py                 │ VectorStore (for session research cleanup)           │ Lazy inline import      │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/chat.py                   │ ResearchCache                                        │ Lazy inline import      │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/section_commands.py       │ ResearchCache, sections.*                            │ Eager top-level import  │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/research_commands.py      │ ResearchCache, execute_get_relevant_content          │ Eager top-level import  │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/local_ingestion_flow.py   │ Multiple research imports                            │ Eager top-level imports │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/display.py                │ get_embedding_client                                 │ Lazy inline import      │
  ├───────────────────────────────┼──────────────────────────────────────────────────────┼─────────────────────────┤
  │ cli/main.py                   │ ResearchCache (cache cleanup)                        │ Lazy inline import      │
  └───────────────────────────────┴──────────────────────────────────────────────────────┴─────────────────────────┘

  The key problem: tool_registry_factory.py has an eager top-level import (from asky.research.tools import ACQUISITION_TOOL_NAMES). This means chromadb is always imported whenever a
   tool registry is built, even for non-research turns.

  Would extraction increase total LOC?

  Yes, somewhat. The research module is already a well-bounded package with a clear internal structure. Wrapping it in a plugin adds:
  - Plugin class with activate() / deactivate() (~30 lines)
  - Hook registrations for TOOL_REGISTRY_BUILD (~15 lines)
  - New hook types if needed for shortlist/preload integration (~20 lines)

  But the bigger cost is indirection. Currently api/preload.py has conditionals like:
  if research_mode:
      data = run_shortlist_pipeline(...)
  After extraction, research mode detection must happen through a different mechanism — either a hook that preload fires (PRE_PRELOAD), or a capability query on the runtime. The
  preload pipeline would need restructuring.

  The real coupling: PreloadResolution in api/types.py has shortlist_results, local_corpus_paths, research_data fields baked in. These are used throughout api/client.py and
  api/preload.py. Untangling this from "core" into a plugin would require either:
  - Making PreloadResolution extensible (plugin-contributed fields) — significant API surface change
  - Or keeping PreloadResolution but having the plugin populate it via a hook — doable but awkward

  Startup performance: The eager import of ACQUISITION_TOOL_NAMES from research.tools pulls in chromadb initialization. Moving this behind the hook would eliminate this cost for
  non-research users. This is the most concrete performance win.

  Would this make research slower? No. The hook fires at the same point in the turn cycle. The actual embedding/retrieval/RAG work happens in the same async flow.

  Verdict: Significant reorganization win but high-complexity migration. The right framing is: the first step is fixing the eager import in tool_registry_factory.py (one line
  change, defer ACQUISITION_TOOL_NAMES to inside a conditional or lazy-load it). That gives 80% of the startup benefit with 0.1% of the complexity. The full plugin extraction is a
  larger project.

  ---
  Tier 4 — Low value or not recommended

  Clipboard (pyperclip in cli/utils.py)

  The clipboard read is used in the /cp query expansion — it's ~5 lines inside expand_query_text() in the CLI preprocessing path. It's too tightly woven into prompt text expansion
  to be a plugin hook. The right approach is just guarding with a try/except on pyperclip import (which likely already exists) and making it a soft dep. Not a plugin.

  Shell completion (cli/completion.py, argcomplete)

  argcomplete must integrate at argparse construction time, before any plugin runtime is available. Plugin lifecycle is incompatible with the timing requirements. Not a plugin.

  History / session CLI commands (cli/history.py, cli/sessions.py)

  These are fundamental CLI verbs (asky -h, asky -ss). They depend on the SQLite storage layer directly. Extracting them gives no meaningful opt-out (you always want session
  support) and creates awkward coupling to the storage layer that's already "core". Not a plugin.

  Web search tools (tools.py)

  This is the primary LLM capability. Making it optional would break the main use case. Not a plugin — or at best, so fundamental it should stay always-enabled in the default plugin
   roster.

  ---
  Summary Table

  ┌─────────────────────┬───────┬─────────────────────────────────────────────────────────────┬────────────────────┬────────────────┬───────────────────────────────────────────┐
  │       Feature       │  LOC  │                     Dep isolation gain                      │ Encapsulation gain │ Migration cost │               Recommended?                │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Email sending       │ 149   │ none (stdlib)                                               │ ✓                  │ low            │ Yes                                       │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Push data           │ 247   │ requests (already core)                                     │ ✓✓                 │ low            │ Yes                                       │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Browser rendering   │ 345   │ none (stdlib)                                               │ ✓                  │ low-medium     │ Yes                                       │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ User memory         │ 833   │ chromadb, sentence-transformers                             │ ✓✓                 │ medium         │ Yes — big dep win                         │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Research pipeline   │ ~8100 │ chromadb, sentence-transformers, trafilatura, pymupdf, yake │ ✓✓✓                │ high           │ Fix eager import first; full plugin later │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Clipboard           │ ~5    │ pyperclip                                                   │ —                  │ n/a            │ No (soft dep instead)                     │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ Shell completion    │ 407   │ argcomplete                                                 │ —                  │ incompatible   │ No                                        │
  ├─────────────────────┼───────┼─────────────────────────────────────────────────────────────┼────────────────────┼────────────────┼───────────────────────────────────────────┤
  │ History/session CLI │ ~300  │ none                                                        │ —                  │ high coupling  │ No                                        │
  └─────────────────────┴───────┴─────────────────────────────────────────────────────────────┴────────────────────┴────────────────┴───────────────────────────────────────────┘

  ---
  Prerequisite: Implement POST_TURN_RENDER and TURN_COMPLETED

  Email, push-data, browser rendering, and memory auto-extraction all need hooks that are declared but never fired. Before extracting any of these, api/client.py needs to emit them:

  - TURN_COMPLETED: fire after run_turn() has the final answer, before save_history(). Payload: TurnCompletedContext(request, result) — already defined.
  - POST_TURN_RENDER: fire after all CLI-side post-processing (saving, rendering, email, push). Payload: final answer text + metadata.

  That's roughly 30 lines in api/client.py or cli/chat.py, and it unblocks 4 plugin extractions at once.

  ---
  Recommended migration sequence

  1. Fire TURN_COMPLETED in api/client.py — 30 lines, unblocks everything downstream
  2. Push data plugin — lowest complexity, best example of the full hook pattern (TOOL_REGISTRY_BUILD + POST_TURN_RENDER)
  3. Email plugin — simple, reference implementation
  4. Fix the research eager import in tool_registry_factory.py — one-line fix, immediate startup win
  5. User memory plugin — medium complexity, high dep-isolation value
  6. Browser rendering plugin — after POST_TURN_RENDER is proven stable
  7. Research pipeline plugin — tackle after #2–6 have established the plugin patterns at scale

  The first four items are roughly a day's work. Items 5–7 are multi-session projects. Nothing here makes the code slower. Items 4 and 5 make cold startup measurably faster for
  users who don't use research or memory.
"""Extraction prompts for milestone-3 source ingestion."""

from __future__ import annotations

from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind

SOURCE_EXTRACTION_PROMPTS = {
    PersonaSourceKind.BIOGRAPHY: """
Extract structured knowledge from this biography about {persona_name}.
Focus on:
1. Viewpoints: The persona's stated or inferred beliefs, philosophical stances, and core arguments.
2. Facts: Discrete biographical facts, relationships, and verifiable historical data.
3. Timeline Events: Specific dated events in the persona's life (include the year).
4. Conflict Candidates: Any claims that explicitly contradict other known biographies or the persona's own writings mentioned in the text.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 0.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "...", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}],
  "conflicts": [{{ "topic": "...", "description": "...", "opposing_claims": [...] }}]
}}
""",
    PersonaSourceKind.AUTOBIOGRAPHY: """
Extract structured knowledge from this autobiography by {persona_name}.
Focus on:
1. Viewpoints: The persona's direct statements of belief, intent, and perspective.
2. Facts: Key life facts and context provided by the author.
3. Timeline Events: Chronological milestones described by the author.
4. Conflict Candidates: Any internal contradictions or mentions of where other sources are "wrong."

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 1.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}],
  "conflicts": [{{ "topic": "...", "description": "...", "opposing_claims": [...] }}]
}}
""",
    PersonaSourceKind.INTERVIEW: """
Extract structured knowledge from this interview with {persona_name}.
Focus on:
1. Viewpoints: The persona's answers that express opinions, beliefs, or stances.
2. Facts: New biographical details revealed during the conversation.
Exclude interviewer's commentary or non-persona content.
Every entry must include speaker-role metadata.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 0.9, "evidence": "...", "speaker_role": "interviewee" }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "{persona_name}", "evidence": "...", "speaker_role": "interviewee" }}]
}}
""",
    PersonaSourceKind.ARTICLE: """
Extract structured knowledge from this article by {persona_name}.
Focus on:
1. Viewpoints: Core arguments and perspectives advanced in the piece.
2. Facts: Explicit claims made as part of the argument.
3. Timeline Events: ONLY if the article describes specific historical milestones with clear dates.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 1.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}]
}}
""",
    PersonaSourceKind.ESSAY: """
Extract structured knowledge from this essay by {persona_name}.
Focus on:
1. Viewpoints: The central thesis and supporting philosophical or political stances.
2. Facts: Contextual facts cited by the author.
3. Timeline Events: ONLY if explicitly described with dates.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 1.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}]
}}
""",
    PersonaSourceKind.SPEECH: """
Extract structured knowledge from this speech by {persona_name}.
Focus on:
1. Viewpoints: Key rhetorical points, calls to action, and expressed beliefs.
2. Facts: Occasion-specific facts or anecdotes shared.
3. Timeline Events: Chronological anchors mentioned in the speech.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 1.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}]
}}
""",
    PersonaSourceKind.NOTES: """
Extract structured knowledge from these personal notes by {persona_name}.
Focus on:
1. Viewpoints: Emerging ideas, private reflections, and tentative stances.
2. Facts: Observed details or reminders recorded.
3. Timeline Events: ONLY if notes contain dated entries.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 0.8, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}]
}}
""",
    PersonaSourceKind.POSTS: """
Extract structured knowledge from these short-form posts by {persona_name}.
Focus on:
1. Viewpoints: Quick takes, reactive stances, and condensed perspectives.
2. Facts: Mentioned events or personal updates.
3. Timeline Events: ONLY if posts refer to specific dates or the post itself is dated.

Output format MUST be a single JSON object with:
{{
  "viewpoints": [{{ "claim": "...", "topic": "...", "confidence": 1.0, "evidence": "..." }}],
  "facts": [{{ "text": "...", "topic": "...", "attribution": "Self", "evidence": "..." }}],
  "timeline": [{{ "text": "...", "year": 19xx, "date_label": "...", "topic": "..." }}]
}}
""",
}

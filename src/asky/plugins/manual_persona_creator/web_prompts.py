from __future__ import annotations

WEB_PAGE_CLASSIFICATION_AND_PREVIEW_PROMPT = """
You are an expert researcher analyzing a scraped web page to determine its relevance to a specific persona.

Persona Name: {persona_name}
Persona Description: {persona_description}

Page Title: {page_title}
Page URL: {page_url}
Page Content:
{page_content}

Your task is to:
1. Classify the page into one of these categories:
   - authored_by_persona: The page content was clearly written or spoken by the persona (e.g., an article, speech, interview transcript, or personal blog post).
   - about_persona: The page is about the persona but written by someone else (e.g., a biography, news report, analysis, or review).
   - uncertain: It's not clear if it's by or about the persona, or it's a mix.
   - irrelevant: The page has nothing to do with this persona.

2. Extract a short summary (1-3 sentences) of the page's relevance to the persona.

3. Extract candidate viewpoints, facts, timeline events, and conflicts.
   - Viewpoints: Distinct philosophical, political, or personal stances expressed in the content.
   - Facts: Verifiable claims about the persona or their work.
   - Timeline Events: Specific dated events in the persona's life or career.
   - Conflicts: Areas where the page content contradicts other known facts or presents a controversial stance.

4. Recommend a trust level:
   - authored_primary: If classification is authored_by_persona.
   - third_party_secondary: If classification is about_persona.
   - uncertain: Otherwise.

Respond in the following JSON format:
{{
  "classification": "authored_by_persona" | "about_persona" | "uncertain" | "irrelevant",
  "short_summary": "...",
  "viewpoints": [
    {{ "viewpoint": "...", "evidence": "..." }}
  ],
  "facts": [
    {{ "fact": "...", "evidence": "..." }}
  ],
  "timeline_events": [
    {{ "event": "...", "date": "...", "evidence": "..." }}
  ],
  "conflicts": [
    {{ "conflict": "...", "evidence": "..." }}
  ],
  "recommended_trust": "authored_primary" | "third_party_secondary" | "uncertain"
}}
"""

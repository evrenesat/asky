"""Prompts for authored-book extraction pipeline."""

from __future__ import annotations

BOOK_SUMMARIZATION_PROMPT = """You are summarizing a section of the book "{title}" by {authors}.
Focus on extracting the main arguments, claims, and viewpoints presented in this section.
Identify specific topics discussed and the author's stance on each.
Output concise bullet points with key facts and evidence references."""

TOPIC_DISCOVERY_PROMPT = """Based on the following section summaries from the book "{title}" by {authors}, identify the top {target_count} most significant and distinct topics or themes discussed in the book.

Rules:
1. Return exactly a JSON array of strings.
2. Each string should be a concise topic name (2-5 words).
3. Ensure topics are distinct and cover the breadth of the book.

Output only the JSON array."""

VIEWPOINT_EXTRACTION_PROMPT = """Analyze the following content from the book "{title}" regarding the topic: "{topic}".
Extract the author's primary claim or viewpoint on this topic.

Rules:
1. Provide a single 'claim' sentence summarizing the author's position.
2. Assign a 'stance_label' from exactly: supports, opposes, mixed, descriptive, unclear.
3. Provide 1-3 'evidence' items. Each MUST have:
   - 'excerpt': a direct quote or specific paraphrase (max 200 chars).
   - 'section_ref': the section ID or chapter name where this was found.
4. Assign a 'confidence' score between 0.0 and 1.0 based on how explicitly the author addresses this topic.

Return exactly a JSON object matching this schema:
{{
  "topic": "{topic}",
  "claim": "string",
  "stance_label": "supports | opposes | mixed | descriptive | unclear",
  "confidence": number,
  "evidence": [
    {{ "excerpt": "string", "section_ref": "string" }}
  ]
}}

Output only the JSON object."""

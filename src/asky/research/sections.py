"""Section indexing and deterministic matching for local corpus sources."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

HEADING_MIN_CHARS = 5
HEADING_MAX_CHARS = 220
HEADING_MIN_WORDS = 1
HEADING_MAX_WORDS = 26
HEADING_SCORE_MIN = 0.52

TOC_SCAN_MAX_LINES = 500
TOC_MAX_ENTRIES = 400
TOC_EMPTY_STREAK_LIMIT = 3

STRICT_MATCH_MIN_CONFIDENCE = 0.86
STRICT_MATCH_MARGIN = 0.06
SUGGESTION_MIN_CONFIDENCE = 0.42
MAX_SUGGESTIONS_DEFAULT = 5

SECTION_SLUG_MAX_CHARS = 48
SECTION_SLICE_CHUNK_TARGET_CHARS = 3200
MIN_CANONICAL_BODY_CHARS = 320
MIN_SUMMARIZE_SECTION_CHARS = 240

CANONICAL_ALIAS_SIZE_RATIO = 2.0

CHAPTER_PREFIX_PATTERN = re.compile(
    r"^(chapter|part|section|book)\b", re.IGNORECASE
)
ROMAN_NUMERAL_PATTERN = re.compile(
    r"^[ivxlcdm]+$", re.IGNORECASE
)
WORD_PATTERN = re.compile(r"[a-z0-9]+")
TOC_TITLE_PATTERN = re.compile(
    r"^(contents?|table\s+of\s+contents?)$",
    re.IGNORECASE,
)
TRAILING_PAGE_NUMBER_PATTERN = re.compile(r"\s+(?:\.{2,}\s*)?\d+\s*$")


@dataclass(frozen=True)
class _HeadingCandidate:
    title: str
    normalized_title: str
    start_offset: int
    line_index: int
    score: float


def _normalize_title(text: str) -> str:
    normalized = text.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _tokenize(text: str) -> List[str]:
    return WORD_PATTERN.findall(_normalize_title(text))


def _slugify(text: str) -> str:
    tokens = _tokenize(text)
    if not tokens:
        return "section"
    return "-".join(tokens)[:SECTION_SLUG_MAX_CHARS].strip("-") or "section"


def _line_offsets(content: str) -> List[int]:
    offsets = [0]
    for match in re.finditer(r"\n", content):
        offsets.append(match.end())
    return offsets


def _strip_toc_page_number(line: str) -> str:
    stripped = TRAILING_PAGE_NUMBER_PATTERN.sub("", line).strip(" .-\t")
    return stripped


def _is_probable_prose(line: str) -> bool:
    word_count = len(_tokenize(line))
    if line.strip().endswith(".") and word_count >= 6:
        return True
    if word_count < 18:
        return False
    punctuation_hits = sum(1 for ch in line if ch in ".,;:")
    return punctuation_hits >= 2


def _extract_toc_titles(lines: Sequence[str]) -> Tuple[List[str], int]:
    titles: List[str] = []
    in_toc = False
    toc_end_line = -1
    empty_streak = 0

    for line_index, raw_line in enumerate(lines[:TOC_SCAN_MAX_LINES]):
        line = raw_line.strip()
        if not in_toc:
            if TOC_TITLE_PATTERN.match(line):
                in_toc = True
                toc_end_line = line_index
            continue

        if not line:
            empty_streak += 1
            if empty_streak >= TOC_EMPTY_STREAK_LIMIT and titles:
                toc_end_line = line_index
                break
            continue

        empty_streak = 0
        if len(line) > HEADING_MAX_CHARS:
            if titles:
                toc_end_line = line_index
                break
            continue
        if _is_probable_prose(line):
            if titles:
                toc_end_line = line_index
                break
            continue

        entry = _strip_toc_page_number(line)
        if not entry:
            continue
        if entry.endswith("."):
            if titles:
                toc_end_line = line_index
                break
            continue

        entry_words = _tokenize(entry)
        if len(entry_words) < HEADING_MIN_WORDS or len(entry_words) > HEADING_MAX_WORDS:
            continue
        if not CHAPTER_PREFIX_PATTERN.match(entry):
            uppercase_ratio = _uppercase_ratio(entry)
            titlecase_ratio = _titlecase_ratio(entry)
            if uppercase_ratio < 0.45 and titlecase_ratio < 0.65:
                if titles:
                    toc_end_line = line_index
                    break
                continue

        titles.append(entry)
        toc_end_line = line_index
        if len(titles) >= TOC_MAX_ENTRIES:
            break

    deduped: List[str] = []
    seen = set()
    for title in titles:
        normalized = _normalize_title(title)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(title)
    return deduped, toc_end_line


def _uppercase_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    uppercase = sum(1 for ch in letters if ch.isupper())
    return uppercase / len(letters)


def _titlecase_ratio(text: str) -> float:
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if not tokens:
        return 0.0
    titled = sum(1 for token in tokens if token[0].isupper())
    return titled / len(tokens)


def _looks_like_heading(
    line: str,
    *,
    prev_blank: bool,
    next_blank: bool,
    toc_normalized_titles: set[str],
) -> float:
    text = line.strip()
    if not text:
        return 0.0
    if len(text) < HEADING_MIN_CHARS or len(text) > HEADING_MAX_CHARS:
        return 0.0

    words = _tokenize(text)
    word_count = len(words)
    if word_count < HEADING_MIN_WORDS or word_count > HEADING_MAX_WORDS:
        return 0.0

    if ROMAN_NUMERAL_PATTERN.match(text.replace(" ", "")):
        return 0.0

    score = 0.0
    if CHAPTER_PREFIX_PATTERN.match(text):
        score += 0.45

    uppercase_ratio = _uppercase_ratio(text)
    if uppercase_ratio >= 0.75:
        score += 0.32
    elif uppercase_ratio >= 0.55:
        score += 0.18

    titlecase_ratio = _titlecase_ratio(text)
    if titlecase_ratio >= 0.85:
        score += 0.24
    elif titlecase_ratio >= 0.65:
        score += 0.12

    if prev_blank and next_blank:
        score += 0.2
    elif prev_blank or next_blank:
        score += 0.1

    if _normalize_title(text) in toc_normalized_titles:
        score += 0.2

    return min(score, 1.0)


def _build_candidates(content: str) -> tuple[List[_HeadingCandidate], int, set[str]]:
    lines = content.splitlines()
    if not lines:
        return [], -1, set()

    line_offsets = _line_offsets(content)
    toc_titles, toc_end_line = _extract_toc_titles(lines)
    toc_normalized_titles = {_normalize_title(item) for item in toc_titles}

    candidates: List[_HeadingCandidate] = []
    for idx, raw_line in enumerate(lines):
        if idx <= toc_end_line:
            continue

        line = raw_line.strip()
        prev_blank = idx == 0 or not lines[idx - 1].strip()
        next_blank = idx >= len(lines) - 1 or not lines[idx + 1].strip()
        score = _looks_like_heading(
            line,
            prev_blank=prev_blank,
            next_blank=next_blank,
            toc_normalized_titles=toc_normalized_titles,
        )
        if score < HEADING_SCORE_MIN:
            continue

        normalized = _normalize_title(line)
        if not normalized:
            continue

        candidates.append(
            _HeadingCandidate(
                title=line,
                normalized_title=normalized,
                start_offset=line_offsets[idx],
                line_index=idx,
                score=score,
            )
        )

    return candidates, toc_end_line, toc_normalized_titles


def _dedupe_candidates(candidates: List[_HeadingCandidate]) -> List[_HeadingCandidate]:
    deduped: List[_HeadingCandidate] = []
    seen_titles: Dict[str, int] = {}
    for candidate in sorted(candidates, key=lambda item: item.start_offset):
        previous_offset = seen_titles.get(candidate.normalized_title)
        if previous_offset is not None and abs(candidate.start_offset - previous_offset) < 400:
            continue
        seen_titles[candidate.normalized_title] = candidate.start_offset
        deduped.append(candidate)
    return deduped


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    token = str(value).strip().lower()
    return token in {"1", "true", "yes", "on"}


def _canonicalize_sections(sections: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for section in sections:
        normalized = str(section.get("normalized_title", "") or "")
        grouped.setdefault(normalized or str(section.get("id", "")), []).append(section)

    alias_map: Dict[str, str] = {}
    canonical_ids: set[str] = set()

    for group in grouped.values():
        canonical = max(
            group,
            key=lambda item: (
                int(item.get("char_count", 0) or 0),
                float(item.get("heading_score", 0.0) or 0.0),
                -int(item.get("start_offset", 0) or 0),
            ),
        )
        canonical_id = str(canonical.get("id", ""))
        canonical_size = int(canonical.get("char_count", 0) or 0)
        canonical_ids.add(canonical_id)

        for item in group:
            item_id = str(item.get("id", ""))
            item_size = int(item.get("char_count", 0) or 0)
            explicit_toc = _coerce_bool(item.get("is_toc"))
            alias_ratio = canonical_size / max(1, item_size)
            duplicate_group = len(group) > 1
            is_alias = item_id != canonical_id
            inferred_toc_alias = (
                duplicate_group
                and is_alias
                and (
                    item_size < MIN_CANONICAL_BODY_CHARS
                    or alias_ratio >= CANONICAL_ALIAS_SIZE_RATIO
                )
            )

            is_toc = explicit_toc or inferred_toc_alias
            is_body = not is_toc or item_id == canonical_id

            item["canonical_id"] = canonical_id
            item["is_toc"] = is_toc
            item["is_body"] = is_body
            alias_map[item_id] = canonical_id

    canonical_sections = [
        dict(section)
        for section in sorted(sections, key=lambda item: int(item.get("start_offset", 0) or 0))
        if str(section.get("id", "")) in canonical_ids
    ]

    return canonical_sections, alias_map


def build_section_index(content: str) -> Dict[str, Any]:
    """Build deterministic sections from raw source content."""
    normalized_content = str(content or "")
    if not normalized_content.strip():
        return {
            "sections": [],
            "canonical_sections": [],
            "alias_map": {},
            "stats": {
                "section_count": 0,
                "raw_section_count": 0,
                "canonical_section_count": 0,
                "strategy": "empty",
            },
        }

    candidates, toc_end_line, toc_titles = _build_candidates(normalized_content)
    candidates = _dedupe_candidates(candidates)
    sections: List[Dict[str, Any]] = []

    if not candidates:
        section_id = "section-001"
        section = {
            "id": section_id,
            "title": "Full Document",
            "normalized_title": _normalize_title("Full Document"),
            "start_offset": 0,
            "end_offset": len(normalized_content),
            "char_count": len(normalized_content),
            "heading_score": 0.0,
            "index": 1,
            "line_index": 0,
            "is_toc": False,
            "is_body": True,
            "canonical_id": section_id,
        }
        return {
            "sections": [section],
            "canonical_sections": [dict(section)],
            "alias_map": {section_id: section_id},
            "stats": {
                "section_count": 1,
                "raw_section_count": 1,
                "canonical_section_count": 1,
                "toc_title_count": 0,
                "toc_end_line": -1,
                "strategy": "fallback_full_document",
            },
        }

    toc_title_set = set(toc_titles)
    for idx, candidate in enumerate(candidates):
        end_offset = (
            candidates[idx + 1].start_offset if idx + 1 < len(candidates) else len(normalized_content)
        )
        char_count = max(0, end_offset - candidate.start_offset)
        section_id = f"{_slugify(candidate.title)}-{idx + 1:03d}"
        sections.append(
            {
                "id": section_id,
                "title": candidate.title,
                "normalized_title": candidate.normalized_title,
                "start_offset": candidate.start_offset,
                "end_offset": end_offset,
                "char_count": char_count,
                "heading_score": round(candidate.score, 3),
                "index": idx + 1,
                "line_index": candidate.line_index,
                "is_toc": (
                    candidate.line_index <= toc_end_line
                    or candidate.normalized_title in toc_title_set
                ),
                "is_body": True,
                "canonical_id": section_id,
            }
        )

    canonical_sections, alias_map = _canonicalize_sections(sections)

    return {
        "sections": sections,
        "canonical_sections": canonical_sections,
        "alias_map": alias_map,
        "stats": {
            "section_count": len(canonical_sections),
            "raw_section_count": len(sections),
            "canonical_section_count": len(canonical_sections),
            "toc_title_count": len(toc_title_set),
            "toc_end_line": toc_end_line,
            "strategy": "heading_index",
        },
    }


def get_listable_sections(
    section_index: Dict[str, Any],
    *,
    include_toc: bool = False,
) -> List[Dict[str, Any]]:
    """Return deterministic section rows for external listing."""
    if include_toc:
        source_sections = list(section_index.get("sections") or [])
        return sorted(
            [dict(section) for section in source_sections],
            key=lambda item: int(item.get("start_offset", 0) or 0),
        )

    canonical_sections = list(section_index.get("canonical_sections") or [])
    if canonical_sections:
        return sorted(
            [dict(section) for section in canonical_sections],
            key=lambda item: int(item.get("start_offset", 0) or 0),
        )

    fallback_sections = list(section_index.get("sections") or [])
    return sorted(
        [dict(section) for section in fallback_sections],
        key=lambda item: int(item.get("start_offset", 0) or 0),
    )


def resolve_section_alias(
    section_index: Dict[str, Any],
    section_id: str,
) -> tuple[Optional[str], bool]:
    """Resolve section aliases to canonical IDs."""
    requested = str(section_id or "").strip()
    if not requested:
        return None, False

    alias_map = dict(section_index.get("alias_map") or {})
    resolved = str(alias_map.get(requested, requested))
    return resolved, resolved != requested


def get_section_by_id(
    section_index: Dict[str, Any],
    section_id: str,
) -> Optional[Dict[str, Any]]:
    """Return section row by ID from full parsed section set."""
    target_id = str(section_id or "").strip()
    if not target_id:
        return None
    sections = list(section_index.get("sections") or [])
    return next(
        (dict(section) for section in sections if str(section.get("id", "")) == target_id),
        None,
    )


def _match_score(query: str, section_title: str) -> float:
    query_normalized = _normalize_title(query)
    title_normalized = _normalize_title(section_title)
    if not query_normalized or not title_normalized:
        return 0.0

    if query_normalized == title_normalized:
        return 1.0

    if query_normalized in title_normalized or title_normalized in query_normalized:
        contains_bonus = 0.2
    else:
        contains_bonus = 0.0

    sequence_similarity = difflib.SequenceMatcher(
        None, query_normalized, title_normalized
    ).ratio()

    query_tokens = set(_tokenize(query_normalized))
    title_tokens = set(_tokenize(title_normalized))
    if not query_tokens:
        token_overlap = 0.0
    else:
        token_overlap = len(query_tokens & title_tokens) / len(query_tokens)

    raw_score = (0.56 * sequence_similarity) + (0.32 * token_overlap) + contains_bonus
    return min(raw_score, 1.0)


def match_section_strict(
    section_query: str,
    section_index: Dict[str, Any],
    *,
    max_suggestions: int = MAX_SUGGESTIONS_DEFAULT,
    include_toc: bool = False,
) -> Dict[str, Any]:
    """Strictly match a user query to a section title with suggestions."""
    query = str(section_query or "").strip()
    sections = get_listable_sections(section_index, include_toc=include_toc)
    if not query:
        return {
            "matched": False,
            "confidence": 0.0,
            "section": None,
            "reason": "empty_query",
            "suggestions": [],
        }
    if not sections:
        return {
            "matched": False,
            "confidence": 0.0,
            "section": None,
            "reason": "no_sections",
            "suggestions": [],
        }

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for section in sections:
        score = _match_score(query, str(section.get("title", "")))
        scored.append((score, section))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_section = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = top_score - second_score

    suggestions = [
        {
            "id": item[1].get("id"),
            "title": item[1].get("title"),
            "confidence": round(item[0], 3),
        }
        for item in scored
        if item[0] >= SUGGESTION_MIN_CONFIDENCE
    ][: max(1, int(max_suggestions))]

    if top_score >= STRICT_MATCH_MIN_CONFIDENCE and margin >= STRICT_MATCH_MARGIN:
        return {
            "matched": True,
            "confidence": round(top_score, 3),
            "section": top_section,
            "reason": "strict_match",
            "suggestions": suggestions,
        }

    return {
        "matched": False,
        "confidence": round(top_score, 3),
        "section": None,
        "reason": "low_confidence" if top_score >= SUGGESTION_MIN_CONFIDENCE else "no_match",
        "suggestions": suggestions,
    }


def _slice_by_chunk_limit(text: str, max_chunks: Optional[int]) -> Tuple[str, bool, int]:
    if max_chunks is None:
        return text, False, 1

    safe_max_chunks = max(1, int(max_chunks))
    if not text.strip():
        return text, False, 0

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return text, False, 1

    chunks: List[str] = []
    current: List[str] = []
    current_size = 0

    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        separator_len = 2 if current else 0
        projected = current_size + separator_len + paragraph_len
        if current and projected > SECTION_SLICE_CHUNK_TARGET_CHARS:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_size = paragraph_len
            continue
        current.append(paragraph)
        current_size = projected

    if current:
        chunks.append("\n\n".join(current))

    if len(chunks) <= safe_max_chunks:
        return text, False, len(chunks)

    sliced = "\n\n".join(chunks[:safe_max_chunks]).strip()
    return sliced, True, len(chunks)


def slice_section_content(
    content: str,
    section_index: Dict[str, Any],
    section_id: str,
    *,
    max_chunks: Optional[int] = None,
    resolve_alias_to_canonical: bool = True,
) -> Dict[str, Any]:
    """Slice section-bounded content and optionally clamp by chunk count."""
    requested_section_id = str(section_id or "").strip()
    if not requested_section_id:
        return {
            "error": "Unknown section id: ",
            "section": None,
            "content": "",
            "truncated": False,
            "available_chunks": 0,
            "requested_section_id": "",
            "resolved_section_id": "",
            "auto_promoted": False,
        }

    resolved_section_id = requested_section_id
    auto_promoted = False
    if resolve_alias_to_canonical:
        resolved_section_id, auto_promoted = resolve_section_alias(
            section_index,
            requested_section_id,
        )
        if resolved_section_id is None:
            resolved_section_id = requested_section_id

    target = get_section_by_id(section_index, resolved_section_id)
    if target is None:
        return {
            "error": f"Unknown section id: {requested_section_id}",
            "section": None,
            "content": "",
            "truncated": False,
            "available_chunks": 0,
            "requested_section_id": requested_section_id,
            "resolved_section_id": resolved_section_id,
            "auto_promoted": auto_promoted,
        }

    start = int(target.get("start_offset", 0) or 0)
    end = int(target.get("end_offset", len(content)) or len(content))
    start = max(0, min(start, len(content)))
    end = max(start, min(end, len(content)))

    section_text = str(content[start:end]).strip()
    sliced_text, truncated, available_chunks = _slice_by_chunk_limit(
        section_text,
        max_chunks,
    )

    return {
        "section": target,
        "content": sliced_text,
        "truncated": truncated,
        "available_chunks": available_chunks,
        "requested_section_id": requested_section_id,
        "resolved_section_id": resolved_section_id,
        "auto_promoted": auto_promoted,
    }

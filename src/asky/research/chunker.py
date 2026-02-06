"""Text chunking utilities for RAG."""

import re
from typing import List, Tuple

from asky.config import RESEARCH_CHUNK_SIZE, RESEARCH_CHUNK_OVERLAP

SENTENCE_BOUNDARY_SEARCH_FRACTION = 0.8
SENTENCE_BOUNDARY_LOOKAHEAD_CHARS = 50


def chunk_text(
    text: str,
    chunk_size: int = None,
    overlap: int = None,
) -> List[Tuple[int, str]]:
    """Split text into overlapping chunks.

    Args:
        text: The text to chunk.
        chunk_size: Maximum size of each chunk in characters.
        overlap: Number of characters to overlap between chunks.

    Returns:
        List of (chunk_index, chunk_text) tuples.
    """
    chunk_size = chunk_size or RESEARCH_CHUNK_SIZE
    overlap = overlap or RESEARCH_CHUNK_OVERLAP

    if not text:
        return []

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Return empty if only whitespace
    if not text:
        return []

    if len(text) <= chunk_size:
        return [(0, text)]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence end near chunk boundary
            # Search in the last 20% of the chunk
            search_start = start + int(chunk_size * SENTENCE_BOUNDARY_SEARCH_FRACTION)
            search_end = min(end + SENTENCE_BOUNDARY_LOOKAHEAD_CHARS, len(text))

            # Try to find a good break point (period, question mark, exclamation)
            break_point = -1
            for punct in [". ", "? ", "! ", ".\n", "?\n", "!\n"]:
                pos = text.rfind(punct, search_start, search_end)
                if pos > break_point:
                    break_point = pos + 1  # Include the punctuation

            if break_point > start:
                end = break_point

        chunk = text[start:end].strip()
        if chunk:
            chunks.append((chunk_index, chunk))
            chunk_index += 1

        # Move start with overlap
        next_start = end - overlap
        if next_start <= start:
            # Guarantee progress even with pathological overlap values
            next_start = end
        start = next_start

    return chunks


def chunk_by_paragraphs(
    text: str,
    max_chunk_size: int = None,
) -> List[Tuple[int, str]]:
    """Split text by paragraphs, merging small ones.

    Better for preserving semantic boundaries.

    Args:
        text: The text to chunk.
        max_chunk_size: Maximum size of each chunk in characters.

    Returns:
        List of (chunk_index, chunk_text) tuples.
    """
    max_chunk_size = max_chunk_size or RESEARCH_CHUNK_SIZE * 1.5

    if not text:
        return []

    # Split on double newlines (paragraph boundaries)
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks = []
    current_chunk: List[str] = []
    current_size = 0
    chunk_index = 0

    for para in paragraphs:
        para_size = len(para)

        # If adding this paragraph would exceed limit, save current chunk
        if current_size + para_size > max_chunk_size and current_chunk:
            chunks.append((chunk_index, "\n\n".join(current_chunk)))
            chunk_index += 1
            current_chunk = []
            current_size = 0

        # If single paragraph exceeds limit, chunk it further
        if para_size > max_chunk_size:
            # Save any pending chunk first
            if current_chunk:
                chunks.append((chunk_index, "\n\n".join(current_chunk)))
                chunk_index += 1
                current_chunk = []
                current_size = 0

            # Chunk the large paragraph
            sub_chunks = chunk_text(para, int(max_chunk_size))
            for _, sub_text in sub_chunks:
                chunks.append((chunk_index, sub_text))
                chunk_index += 1
        else:
            current_chunk.append(para)
            current_size += para_size + 2  # +2 for \n\n separator

    # Don't forget the last chunk
    if current_chunk:
        chunks.append((chunk_index, "\n\n".join(current_chunk)))

    return chunks


def chunk_by_sentences(
    text: str,
    target_chunk_size: int = None,
) -> List[Tuple[int, str]]:
    """Split text by sentences, grouping to target size.

    Good for Q&A style content.

    Args:
        text: The text to chunk.
        target_chunk_size: Target size for each chunk in characters.

    Returns:
        List of (chunk_index, chunk_text) tuples.
    """
    target_chunk_size = target_chunk_size or RESEARCH_CHUNK_SIZE

    if not text:
        return []

    # Simple sentence splitting (handles common cases)
    # Split on period/question/exclamation followed by space and capital letter
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return []

    chunks = []
    current_chunk: List[str] = []
    current_size = 0
    chunk_index = 0

    for sentence in sentences:
        sentence_size = len(sentence)

        if current_size + sentence_size > target_chunk_size and current_chunk:
            chunks.append((chunk_index, " ".join(current_chunk)))
            chunk_index += 1
            current_chunk = []
            current_size = 0

        current_chunk.append(sentence)
        current_size += sentence_size + 1  # +1 for space

    if current_chunk:
        chunks.append((chunk_index, " ".join(current_chunk)))

    return chunks

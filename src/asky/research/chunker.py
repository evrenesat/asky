"""Text chunking utilities for RAG."""

import logging
import re
from typing import Any, List, Optional, Tuple

from asky.config import RESEARCH_CHUNK_SIZE, RESEARCH_CHUNK_OVERLAP
from asky.research.embeddings import get_embedding_client

SENTENCE_BOUNDARY_SEARCH_FRACTION = 0.8
SENTENCE_BOUNDARY_LOOKAHEAD_CHARS = 50
MIN_CHUNK_SIZE_TOKENS = 8
TOKENIZER_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """Collapse whitespace so chunk windows are deterministic."""
    return re.sub(r"\s+", " ", text).strip()


def _resolve_chunking_values(
    chunk_size: Optional[int],
    overlap: Optional[int],
) -> Tuple[int, int]:
    """Resolve chunk-size defaults safely."""
    resolved_chunk_size = chunk_size if chunk_size is not None else RESEARCH_CHUNK_SIZE
    resolved_overlap = overlap if overlap is not None else RESEARCH_CHUNK_OVERLAP
    resolved_chunk_size = max(MIN_CHUNK_SIZE_TOKENS, int(resolved_chunk_size))
    resolved_overlap = max(0, int(resolved_overlap))
    if resolved_overlap >= resolved_chunk_size:
        resolved_overlap = resolved_chunk_size - 1
    return resolved_chunk_size, resolved_overlap


def _chunk_text_by_char_boundaries(
    text: str,
    chunk_size: int,
    overlap: int,
) -> List[Tuple[int, str]]:
    """Legacy character chunking fallback when tokenizer is unavailable."""
    if len(text) <= chunk_size:
        return [(0, text)]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        if end < len(text):
            search_start = start + int(chunk_size * SENTENCE_BOUNDARY_SEARCH_FRACTION)
            search_end = min(end + SENTENCE_BOUNDARY_LOOKAHEAD_CHARS, len(text))

            break_point = -1
            for punct in [". ", "? ", "! ", ".\n", "?\n", "!\n"]:
                pos = text.rfind(punct, search_start, search_end)
                if pos > break_point:
                    break_point = pos + 1

            if break_point > start:
                end = break_point

        chunk = text[start:end].strip()
        if chunk:
            chunks.append((chunk_index, chunk))
            chunk_index += 1

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _get_embedding_tokenizer() -> Tuple[Optional[Any], int]:
    """Return embedding tokenizer and max sequence length if available."""
    try:
        client = get_embedding_client()
        return client.get_tokenizer(), client.max_seq_length
    except Exception as exc:
        logger.debug("Tokenizer unavailable for token-aware chunking: %s", exc)
        return None, 0


def _encode_tokens(tokenizer: Any, text: str) -> List[int]:
    """Encode text to token IDs across tokenizer implementations."""
    try:
        return tokenizer.encode(text, add_special_tokens=False, verbose=False)
    except TypeError:
        try:
            return tokenizer.encode(text, add_special_tokens=False)
        except TypeError:
            return tokenizer.encode(text)


def _decode_tokens(tokenizer: Any, token_ids: List[int]) -> str:
    """Decode token IDs back to text."""
    try:
        return tokenizer.decode(token_ids, skip_special_tokens=True).strip()
    except TypeError:
        return tokenizer.decode(token_ids).strip()


def _split_sentences(text: str) -> List[str]:
    """Split text to sentence-like units for semantic chunking."""
    pieces = TOKENIZER_SENTENCE_SPLIT_PATTERN.split(text)
    return [piece.strip() for piece in pieces if piece and piece.strip()]


def _chunk_long_sentence(
    tokenizer: Any,
    sentence_tokens: List[int],
    chunk_size: int,
    overlap: int,
) -> List[str]:
    """Chunk a single sentence that exceeds the target token window."""
    chunks: List[str] = []
    start = 0

    while start < len(sentence_tokens):
        end = min(start + chunk_size, len(sentence_tokens))
        chunk_text = _decode_tokens(tokenizer, sentence_tokens[start:end])
        if chunk_text:
            chunks.append(chunk_text)

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _chunk_text_by_tokens(
    text: str,
    chunk_size: int,
    overlap: int,
    tokenizer: Any,
) -> List[Tuple[int, str]]:
    """Create sentence-aware chunks bounded by token counts."""
    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    sentence_tokens = [_encode_tokens(tokenizer, sentence) for sentence in sentences]

    chunks: List[Tuple[int, str]] = []
    chunk_index = 0
    start_idx = 0

    while start_idx < len(sentences):
        end_idx = start_idx
        window_tokens = 0
        long_sentence_split = False

        while end_idx < len(sentences):
            token_len = len(sentence_tokens[end_idx])

            if token_len > chunk_size and end_idx == start_idx:
                for part in _chunk_long_sentence(
                    tokenizer=tokenizer,
                    sentence_tokens=sentence_tokens[end_idx],
                    chunk_size=chunk_size,
                    overlap=overlap,
                ):
                    chunks.append((chunk_index, part))
                    chunk_index += 1
                end_idx += 1
                long_sentence_split = True
                break

            if window_tokens + token_len > chunk_size and end_idx > start_idx:
                break

            window_tokens += token_len
            end_idx += 1

        if end_idx > start_idx and not long_sentence_split:
            chunk_text = " ".join(sentences[start_idx:end_idx]).strip()
            if chunk_text:
                chunks.append((chunk_index, chunk_text))
                chunk_index += 1

        if end_idx >= len(sentences):
            break

        if overlap == 0:
            next_start = end_idx
        else:
            overlap_tokens = 0
            next_start = end_idx
            while next_start > start_idx and overlap_tokens < overlap:
                next_start -= 1
                overlap_tokens += len(sentence_tokens[next_start])

        if next_start <= start_idx:
            next_start = start_idx + 1
        start_idx = next_start

    return chunks


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
    if not text:
        return []

    chunk_size, overlap = _resolve_chunking_values(chunk_size, overlap)
    text = _normalize_text(text)
    if not text:
        return []

    tokenizer, model_max_seq_length = _get_embedding_tokenizer()
    if tokenizer is not None:
        if model_max_seq_length > 0:
            chunk_size = min(chunk_size, model_max_seq_length)
            overlap = min(overlap, max(0, chunk_size - 1))
        return _chunk_text_by_tokens(
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
            tokenizer=tokenizer,
        )

    return _chunk_text_by_char_boundaries(
        text=text,
        chunk_size=chunk_size,
        overlap=overlap,
    )


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
    max_chunk_size = max_chunk_size or int(RESEARCH_CHUNK_SIZE * 1.5)

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
            sub_chunks = chunk_text(para, int(max_chunk_size), overlap=0)
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

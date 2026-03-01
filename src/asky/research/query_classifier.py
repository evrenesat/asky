"""Query classification for detecting one-shot summarization requests.

This module provides functionality to analyze user queries and determine whether
they represent one-shot summarization requests (direct answer) or complex research
workflows (clarification needed).

The classification system uses a 6-step decision tree that considers:
- Configuration overrides (force_research_mode)
- Corpus size (empty, small, or large)
- Query characteristics (vague vs. specific)
- Summarization keywords (primary and secondary)

Classification Results:
- "one_shot": Direct summarization without clarification questions
- "research": Complex workflow requiring clarification

The classifier returns a QueryClassification object containing:
- mode: The classification decision
- confidence: Score from 0.0 to 1.0 indicating certainty
- reasoning: Human-readable explanation
- Detection factors: Boolean flags for various checks

Example Usage:
    from asky.research.query_classifier import classify_query

    result = classify_query(
        query_text="Summarize the key points across all documents",
        corpus_document_count=5,
        document_threshold=10
    )

    if result.mode == "one_shot":
        # Provide direct summary
        pass
    else:
        # Ask clarifying questions
        pass
"""

import re
from dataclasses import dataclass


@dataclass
class QueryClassification:
    """Result of query classification analysis.

    This dataclass holds the results of analyzing a user query to determine
    whether it should be handled as a one-shot summarization (direct answer)
    or as a research-mode query (clarification questions).

    Attributes:
        mode: Classification mode, either "one_shot" or "research"
        confidence: Confidence score from 0.0 to 1.0
        reasoning: Human-readable explanation of the classification decision
        has_summarization_keywords: Whether query contains summarization keywords
        is_small_corpus: Whether corpus size is within one-shot threshold
        is_vague_query: Whether query is too vague for direct answering
        corpus_document_count: Number of documents in the corpus
        document_threshold: Threshold used for corpus size classification
        aggressive_mode: Whether aggressive mode was enabled

    Examples:
        One-shot classification:
        >>> result = QueryClassification(
        ...     mode="one_shot",
        ...     confidence=0.9,
        ...     reasoning="summarization request with small corpus (5 documents)",
        ...     has_summarization_keywords=True,
        ...     is_small_corpus=True,
        ...     is_vague_query=False,
        ...     corpus_document_count=5,
        ...     document_threshold=10,
        ...     aggressive_mode=False
        ... )
        >>> result.mode
        'one_shot'

        Research mode classification:
        >>> result = QueryClassification(
        ...     mode="research",
        ...     confidence=0.8,
        ...     reasoning="query is too vague for direct answering",
        ...     has_summarization_keywords=False,
        ...     is_small_corpus=True,
        ...     is_vague_query=True,
        ...     corpus_document_count=5,
        ...     document_threshold=10,
        ...     aggressive_mode=False
        ... )
        >>> result.mode
        'research'
    """

    mode: str
    confidence: float
    reasoning: str
    has_summarization_keywords: bool
    is_small_corpus: bool
    is_vague_query: bool
    corpus_document_count: int
    document_threshold: int
    aggressive_mode: bool


def _has_summarization_keywords(query_text: str) -> bool:
    """Check if query contains summarization keywords.

    Detects both primary and secondary summarization keywords using
    case-insensitive word boundary matching.

    Primary keywords: summarize, summary, overview
    Secondary keywords: key points, main ideas, highlights, brief, tldr, tl;dr

    Args:
        query_text: The user's query string

    Returns:
        True if any summarization keyword is found, False otherwise

    Examples:
        >>> _has_summarization_keywords("Summarize the key points")
        True
        >>> _has_summarization_keywords("Give me a summary")
        True
        >>> _has_summarization_keywords("What are the main ideas?")
        True
        >>> _has_summarization_keywords("Tell me about these documents")
        False
        >>> _has_summarization_keywords("TLDR please")
        True

    Note:
        Uses word boundary matching to ensure we catch variations like
        'summarize', 'summarized', 'summarizing', and 'summarization'.
    """
    # Primary keywords (catch variations like summarize, summarized, summarization)
    primary_keywords = [
        r"\bsummariz",
        r"\bsummary\b",
        r"\boverview\b",
    ]

    # Secondary keywords (may be multi-word phrases)
    secondary_keywords = [
        r"\bkey\s+points\b",
        r"\bmain\s+ideas\b",
        r"\bhighlights\b",
        r"\bbrief\b",
        r"\btldr\b",
        r"\btl;dr\b",
    ]

    # Combine all keywords
    all_keywords = primary_keywords + secondary_keywords

    # Check each keyword pattern (case-insensitive)
    query_lower = query_text.lower()
    for pattern in all_keywords:
        if re.search(pattern, query_lower):
            return True

    return False


def _is_vague_query(query_text: str) -> bool:
    """Check if query is too vague for direct answering.

    Detects vague queries that lack specific intent and should trigger
    research mode with clarification questions.

    Detection criteria:
    - Very short queries (< 10 characters)
    - Generic phrases: "tell me about", "what is this", "explain these", "info on"
    - Questions without specific intent: "what's here", "show me"

    Args:
        query_text: The user's query string

    Returns:
        True if query is vague, False otherwise

    Examples:
        >>> _is_vague_query("hi")
        True
        >>> _is_vague_query("tell me about these")
        True
        >>> _is_vague_query("what is this")
        True
        >>> _is_vague_query("Summarize the key points across all documents")
        False
        >>> _is_vague_query("What are the main themes in the research papers?")
        False

    Note:
        Short queries are considered vague because they typically lack enough
        context to determine user intent. A 10-character threshold allows for
        queries like "summarize" (9 chars) to pass through while catching
        very short queries like "hi", "help", "info", etc.
    """
    # Strip whitespace for accurate length check
    query_stripped = query_text.strip()

    # Check for very short queries (< 10 chars)
    if len(query_stripped) < 10:
        return True

    # Generic/vague phrase patterns (case-insensitive)
    vague_patterns = [
        r"\btell\s+me\s+about\b",
        r"\bwhat\s+is\s+this\b",
        r"\bexplain\s+these\b",
        r"\binfo\s+on\b",
        r"\bwhat\'?s\s+here\b",
        r"\bshow\s+me\b",
    ]

    # Check each vague pattern
    query_lower = query_text.lower()
    for pattern in vague_patterns:
        if re.search(pattern, query_lower):
            return True

    return False


def _calculate_confidence(
    *,
    mode: str,
    has_summarization_keywords: bool,
    is_small_corpus: bool,
    corpus_document_count: int,
    effective_threshold: int,
    is_forced: bool = False,
) -> float:
    """Calculate confidence score based on detection factors.

    Confidence Scoring Rationale:

    The confidence score reflects how certain the classifier is about its decision,
    based on the strength and number of supporting factors:

    - 1.0: Absolute certainty (configuration overrides, empty corpus)
    - 0.85-0.95: Very high confidence (clear signals, multiple supporting factors)
    - 0.75-0.85: High confidence (single strong signal)
    - 0.65-0.75: Moderate confidence (weak signals or conflicting factors)

    One-Shot Mode Confidence:
    - Base: 0.85 (has keywords + small corpus)
    - +0.05 for very small corpus (1-3 docs) - stronger signal
    - +0.05 when both keywords and small corpus present - multiple factors
    - Capped at 0.95 (never absolute certainty for heuristic decisions)

    Research Mode Confidence:
    - Large corpus: 0.85-0.95 based on distance from threshold
      * Slightly over threshold (11 docs): ~0.86
      * Far over threshold (30 docs): ~0.95
    - Vague query: 0.8 (set explicitly in caller)
    - Default fallback: 0.7 (no clear signals, safe default)

    Args:
        mode: Classification mode ("one_shot" or "research")
        has_summarization_keywords: Whether summarization keywords detected
        is_small_corpus: Whether corpus is within threshold
        corpus_document_count: Number of documents in corpus
        effective_threshold: Threshold used for classification
        is_forced: Whether this is a forced classification (config override)

    Returns:
        Confidence score between 0.0 and 1.0

    Examples:
        Forced classification (config override):
        >>> _calculate_confidence(
        ...     mode="research",
        ...     has_summarization_keywords=True,
        ...     is_small_corpus=True,
        ...     corpus_document_count=5,
        ...     effective_threshold=10,
        ...     is_forced=True
        ... )
        1.0

        One-shot with very small corpus:
        >>> _calculate_confidence(
        ...     mode="one_shot",
        ...     has_summarization_keywords=True,
        ...     is_small_corpus=True,
        ...     corpus_document_count=2,
        ...     effective_threshold=10
        ... )
        0.95

        Research mode with large corpus:
        >>> _calculate_confidence(
        ...     mode="research",
        ...     has_summarization_keywords=False,
        ...     is_small_corpus=False,
        ...     corpus_document_count=30,
        ...     effective_threshold=10
        ... )
        0.95
    """
    if is_forced:
        return 1.0

    if mode == "one_shot":
        base_confidence = 0.85

        if corpus_document_count <= 3:
            base_confidence += 0.05

        if has_summarization_keywords and is_small_corpus:
            base_confidence += 0.05

        return min(base_confidence, 0.95)

    else:  # research mode
        if not is_small_corpus:
            excess_ratio = (
                corpus_document_count - effective_threshold
            ) / effective_threshold
            confidence = 0.85 + min(excess_ratio * 0.1, 0.1)
            return min(confidence, 0.95)

        return 0.7


def classify_query(
    *,
    query_text: str,
    corpus_document_count: int,
    document_threshold: int = 10,
    aggressive_threshold: int = 20,
    aggressive_mode: bool = False,
    force_research_mode: bool = False,
) -> QueryClassification:
    """Classify a query as one-shot summarization or research mode.

    This function implements a 6-step decision tree to determine whether a query
    should be handled as a one-shot summarization (direct answer) or as a
    research-mode query (clarification questions).

    Decision Tree:
    1. If force_research_mode → research (confidence: 1.0)
    2. If corpus empty → research (confidence: 1.0)
    3. If query is vague → research (confidence: 0.8)
    4. If corpus > threshold → research (confidence: 0.85-0.95, based on corpus size)
    5. If has summarization keywords AND corpus ≤ threshold → one_shot (confidence: 0.85-0.95)
    6. Otherwise → research (confidence: 0.7, safe default)

    Confidence Scoring:
    - Scores reflect certainty based on detection factors
    - Multiple supporting factors increase confidence
    - Stronger signals (hard thresholds) have higher confidence
    - Default fallback has lower confidence due to uncertainty

    Args:
        query_text: The user's query string
        corpus_document_count: Number of documents in the corpus
        document_threshold: Maximum documents for one-shot mode (default: 10)
        aggressive_threshold: Threshold when aggressive_mode is enabled (default: 20)
        aggressive_mode: Whether to use higher threshold (default: False)
        force_research_mode: Force research mode regardless of other factors (default: False)

    Returns:
        QueryClassification object with mode, confidence, reasoning, and detection factors

    Examples:
        Basic one-shot classification:
        >>> result = classify_query(
        ...     query_text="Summarize the key points",
        ...     corpus_document_count=5,
        ...     document_threshold=10
        ... )
        >>> result.mode
        'one_shot'
        >>> result.has_summarization_keywords
        True
        >>> result.is_small_corpus
        True

        Vague query triggers research mode:
        >>> result = classify_query(
        ...     query_text="tell me about these",
        ...     corpus_document_count=5,
        ...     document_threshold=10
        ... )
        >>> result.mode
        'research'
        >>> result.is_vague_query
        True

        Large corpus triggers research mode:
        >>> result = classify_query(
        ...     query_text="Summarize the documents",
        ...     corpus_document_count=15,
        ...     document_threshold=10
        ... )
        >>> result.mode
        'research'
        >>> result.is_small_corpus
        False

        Aggressive mode with higher threshold:
        >>> result = classify_query(
        ...     query_text="Give me an overview",
        ...     corpus_document_count=15,
        ...     document_threshold=10,
        ...     aggressive_threshold=20,
        ...     aggressive_mode=True
        ... )
        >>> result.mode
        'one_shot'
        >>> result.document_threshold
        20

        Configuration override:
        >>> result = classify_query(
        ...     query_text="Summarize everything",
        ...     corpus_document_count=5,
        ...     force_research_mode=True
        ... )
        >>> result.mode
        'research'
        >>> result.confidence
        1.0

        Empty corpus:
        >>> result = classify_query(
        ...     query_text="Summarize the documents",
        ...     corpus_document_count=0
        ... )
        >>> result.mode
        'research'
        >>> result.reasoning
        'empty corpus (no documents found)'

        No clear intent (default fallback):
        >>> result = classify_query(
        ...     query_text="What can you tell me?",
        ...     corpus_document_count=5
        ... )
        >>> result.mode
        'research'
        >>> result.confidence
        0.7

    Note:
        The function is deterministic - given the same inputs, it will always
        return the same classification result. This is important for testing
        and debugging.
    """
    # Determine effective threshold based on aggressive mode
    effective_threshold = (
        aggressive_threshold if aggressive_mode else document_threshold
    )

    # Initialize detection factors
    # Detect summarization keywords early so they're available in all return paths
    has_summarization_keywords = _has_summarization_keywords(query_text)
    is_small_corpus = corpus_document_count <= effective_threshold
    is_vague_query = _is_vague_query(query_text)

    # Step 1: Force research mode override
    if force_research_mode:
        return QueryClassification(
            mode="research",
            confidence=1.0,  # Absolute certainty - configuration override
            reasoning="force_research_mode configuration enabled",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            is_vague_query=is_vague_query,
            corpus_document_count=corpus_document_count,
            document_threshold=effective_threshold,
            aggressive_mode=aggressive_mode,
        )

    # Step 2: Empty corpus check
    if corpus_document_count == 0:
        return QueryClassification(
            mode="research",
            confidence=1.0,  # Absolute certainty - no documents to summarize
            reasoning="empty corpus (no documents found)",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            is_vague_query=is_vague_query,
            corpus_document_count=corpus_document_count,
            document_threshold=effective_threshold,
            aggressive_mode=aggressive_mode,
        )

    # Step 3: Vague query detection
    if is_vague_query:
        return QueryClassification(
            mode="research",
            confidence=0.8,  # High confidence - clear signal of ambiguity
            reasoning="query is too vague for direct answering",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            is_vague_query=is_vague_query,
            corpus_document_count=corpus_document_count,
            document_threshold=effective_threshold,
            aggressive_mode=aggressive_mode,
        )

    # Step 4: Large corpus check
    if not is_small_corpus:
        confidence = _calculate_confidence(
            mode="research",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            corpus_document_count=corpus_document_count,
            effective_threshold=effective_threshold,
        )
        return QueryClassification(
            mode="research",
            confidence=confidence,  # 0.85-0.95 based on how far corpus exceeds threshold
            reasoning=f"corpus size ({corpus_document_count}) exceeds threshold ({effective_threshold})",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            is_vague_query=is_vague_query,
            corpus_document_count=corpus_document_count,
            document_threshold=effective_threshold,
            aggressive_mode=aggressive_mode,
        )

    # Step 5: Check for summarization keywords with small corpus
    if has_summarization_keywords and is_small_corpus:
        confidence = _calculate_confidence(
            mode="one_shot",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            corpus_document_count=corpus_document_count,
            effective_threshold=effective_threshold,
        )
        return QueryClassification(
            mode="one_shot",
            confidence=confidence,  # 0.85-0.95 based on corpus size and factors
            reasoning=f"summarization request with small corpus ({corpus_document_count} documents)",
            has_summarization_keywords=has_summarization_keywords,
            is_small_corpus=is_small_corpus,
            is_vague_query=is_vague_query,
            corpus_document_count=corpus_document_count,
            document_threshold=effective_threshold,
            aggressive_mode=aggressive_mode,
        )

    # Step 6: Default to research mode (safe default)
    return QueryClassification(
        mode="research",
        confidence=0.7,  # Moderate confidence - no clear signals, safe default
        reasoning="no clear summarization intent detected, defaulting to research mode",
        has_summarization_keywords=has_summarization_keywords,
        is_small_corpus=is_small_corpus,
        is_vague_query=is_vague_query,
        corpus_document_count=corpus_document_count,
        document_threshold=effective_threshold,
        aggressive_mode=aggressive_mode,
    )

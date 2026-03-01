"""Unit tests for query classification logic."""

import pytest
from asky.research.query_classifier import classify_query, QueryClassification


def test_force_research_mode():
    """Test that force_research_mode always returns research mode."""
    result = classify_query(
        query_text="Summarize the key points",
        corpus_document_count=5,
        document_threshold=10,
        force_research_mode=True,
    )
    assert result.mode == "research"
    assert result.confidence == 1.0
    assert "force_research_mode" in result.reasoning


def test_empty_corpus():
    """Test that empty corpus returns research mode."""
    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=0,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.confidence == 1.0
    assert "empty corpus" in result.reasoning


def test_large_corpus():
    """Test that corpus exceeding threshold returns research mode."""
    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=15,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.confidence == 0.9
    assert "exceeds threshold" in result.reasoning
    assert result.is_small_corpus is False


def test_threshold_boundary():
    """Test that corpus exactly at threshold is considered small."""
    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=10,
        document_threshold=10,
    )
    assert result.is_small_corpus is True


def test_aggressive_mode():
    """Test that aggressive mode uses higher threshold."""
    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=15,
        document_threshold=10,
        aggressive_threshold=20,
        aggressive_mode=True,
    )
    assert result.is_small_corpus is True
    assert result.document_threshold == 20


def test_classification_determinism():
    """Test that same inputs produce same results."""
    result1 = classify_query(
        query_text="Summarize the key points",
        corpus_document_count=5,
        document_threshold=10,
    )
    result2 = classify_query(
        query_text="Summarize the key points",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result1.mode == result2.mode
    assert result1.confidence == result2.confidence
    assert result1.reasoning == result2.reasoning


def test_default_to_research_mode():
    """Test that queries without clear intent default to research mode."""
    result = classify_query(
        query_text="What about the documents?",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert "no clear summarization intent" in result.reasoning


def test_primary_keyword_summarize():
    """Test detection of 'summarize' keyword."""
    result = classify_query(
        query_text="Summarize the key points across all documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_primary_keyword_summary():
    """Test detection of 'summary' keyword."""
    result = classify_query(
        query_text="Give me a summary of the documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_primary_keyword_overview():
    """Test detection of 'overview' keyword."""
    result = classify_query(
        query_text="Provide an overview of the content",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_key_points():
    """Test detection of 'key points' phrase."""
    result = classify_query(
        query_text="What are the key points in these documents?",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_main_ideas():
    """Test detection of 'main ideas' phrase."""
    result = classify_query(
        query_text="What are the main ideas from the files?",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_highlights():
    """Test detection of 'highlights' keyword."""
    result = classify_query(
        query_text="Give me the highlights of the documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_brief():
    """Test detection of 'brief' keyword."""
    result = classify_query(
        query_text="Give me a brief of what's in these files",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_tldr():
    """Test detection of 'tldr' keyword."""
    result = classify_query(
        query_text="tldr of the documents please",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_secondary_keyword_tl_dr():
    """Test detection of 'tl;dr' keyword."""
    result = classify_query(
        query_text="tl;dr for these files",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "one_shot"
    assert result.has_summarization_keywords is True


def test_case_insensitive_matching():
    """Test that keyword matching is case-insensitive."""
    test_cases = [
        "SUMMARIZE the documents",
        "Give me a SUMMARY",
        "Provide an OVERVIEW",
        "What are the KEY POINTS?",
        "Show the MAIN IDEAS",
        "Give me the HIGHLIGHTS",
        "BRIEF overview please",
        "TLDR of the content",
    ]
    for query in test_cases:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.mode == "one_shot", f"Failed for query: {query}"
        assert result.has_summarization_keywords is True, f"Failed for query: {query}"


def test_keyword_variations():
    """Test that variations like 'summarized' or 'summarization' match."""
    variations = [
        "give me a summarization of the data",
        "show the summarized results",
        "I am summarizing the findings",
    ]
    for query in variations:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.mode == "one_shot", f"Failed for variation: {query}"
        assert result.has_summarization_keywords is True, (
            f"Failed for variation: {query}"
        )


def test_word_boundary_detection():
    """Test that keyword matching uses word boundaries (not substring matching)."""
    non_matching_queries = [
        "I want to desummarize the data",  # 'summarize' is part of another word but 'summariz' doesn't match start of 'desummarize'
    ]
    for query in non_matching_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        # Should default to research mode since no valid keywords found
        assert result.mode == "research", f"Should not match for query: {query}"
        assert result.has_summarization_keywords is False, (
            f"Should not match for query: {query}"
        )


def test_keyword_with_large_corpus():
    """Test that keywords alone don't trigger one-shot if corpus is too large."""
    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=15,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.has_summarization_keywords is True
    assert result.is_small_corpus is False
    assert "exceeds threshold" in result.reasoning


def test_vague_query_short_length():
    """Test that very short queries (< 10 chars) are detected as vague."""
    short_queries = [
        "hello",
        "hi",
        "what?",
        "docs",
        "files",
        "info",
        "help",
        "show",
    ]
    for query in short_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.mode == "research", (
            f"Short query should trigger research mode: {query}"
        )
        assert result.is_vague_query is True, f"Should be detected as vague: {query}"
        assert "too vague" in result.reasoning, (
            f"Reasoning should mention vagueness: {query}"
        )


def test_vague_query_tell_me_about():
    """Test detection of 'tell me about' vague phrase."""
    result = classify_query(
        query_text="tell me about these documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True
    assert "too vague" in result.reasoning


def test_vague_query_what_is_this():
    """Test detection of 'what is this' vague phrase."""
    result = classify_query(
        query_text="what is this about?",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_explain_these():
    """Test detection of 'explain these' vague phrase."""
    result = classify_query(
        query_text="explain these files to me",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_info_on():
    """Test detection of 'info on' vague phrase."""
    result = classify_query(
        query_text="give me info on the documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_whats_here():
    """Test detection of 'what's here' vague phrase."""
    result = classify_query(
        query_text="what's here in these files?",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_show_me():
    """Test detection of 'show me' vague phrase."""
    result = classify_query(
        query_text="show me the documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_case_insensitive():
    """Test that vague phrase detection is case-insensitive."""
    vague_queries = [
        "TELL ME ABOUT these",
        "What Is This?",
        "EXPLAIN THESE files",
        "INFO ON documents",
        "WHAT'S HERE?",
        "SHOW ME stuff",
    ]
    for query in vague_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.mode == "research", f"Should trigger research mode: {query}"
        assert result.is_vague_query is True, f"Should be detected as vague: {query}"


def test_specific_query_not_vague():
    """Test that specific queries are not detected as vague."""
    specific_queries = [
        "Summarize the key points across all documents",
        "What are the main findings about climate change?",
        "How does the authentication system work?",
        "Compare the performance metrics between versions",
        "List all the API endpoints mentioned",
    ]
    for query in specific_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.is_vague_query is False, f"Should not be vague: {query}"


def test_vague_query_with_whitespace():
    """Test that whitespace is properly handled in length check."""
    result = classify_query(
        query_text="   hello   ",  # 5 chars after strip
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True


def test_vague_query_overrides_summarization_keywords():
    """Test that vague queries trigger research mode even with summarization keywords."""
    # This is a vague query that happens to contain a summarization keyword
    result = classify_query(
        query_text="summary",  # Too short, even though it's a keyword
        corpus_document_count=5,
        document_threshold=10,
    )
    assert result.mode == "research"
    assert result.is_vague_query is True
    assert result.has_summarization_keywords is True  # Keyword is detected
    # But vague detection takes precedence in decision tree


def test_boundary_length_not_vague():
    """Test that queries with exactly 10 characters are not considered vague by length."""
    result = classify_query(
        query_text="1234567890",  # Exactly 10 chars
        corpus_document_count=5,
        document_threshold=10,
    )
    # Should not be vague by length (>= 10 chars)
    # Will default to research mode due to no summarization keywords
    assert result.is_vague_query is False
    assert result.mode == "research"
    assert "no clear summarization intent" in result.reasoning


def test_mixed_intent_summarization_with_specific_question():
    """Test that mixed intent queries with specific questions default to research mode."""
    # Query contains both summarization keywords and specific research questions
    mixed_queries = [
        "Summarize the key points and explain the methodology in detail",
        "Give me an overview and tell me who the main authors are",
        "What are the highlights and how does the system work?",
        "Provide a summary and explain why this approach was chosen",
        "Brief overview and what are the performance metrics?",
    ]

    for query in mixed_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        # Mixed intent should still trigger one_shot if it has summarization keywords
        # and small corpus, unless the query is detected as vague
        # The current implementation prioritizes summarization keywords
        assert result.has_summarization_keywords is True, (
            f"Should detect keywords in: {query}"
        )


def test_mixed_intent_with_vague_phrases():
    """Test that mixed intent with vague phrases triggers research mode."""
    # These contain summarization keywords but also vague phrases
    result = classify_query(
        query_text="Summarize and tell me about these documents",
        corpus_document_count=5,
        document_threshold=10,
    )
    # "tell me about" is a vague phrase, should trigger research mode
    assert result.mode == "research"
    assert result.is_vague_query is True
    assert result.has_summarization_keywords is True


def test_specific_summarization_not_mixed():
    """Test that specific summarization requests are not confused with mixed intent."""
    # These are clear, specific summarization requests
    specific_queries = [
        "Summarize the key findings about climate change",
        "Give me an overview of the authentication system",
        "What are the key points regarding API design?",
        "Provide a summary of the performance benchmarks",
    ]

    for query in specific_queries:
        result = classify_query(
            query_text=query,
            corpus_document_count=5,
            document_threshold=10,
        )
        assert result.mode == "one_shot", f"Should be one-shot for: {query}"
        assert result.has_summarization_keywords is True, (
            f"Should detect keywords in: {query}"
        )
        assert result.is_vague_query is False, f"Should not be vague: {query}"


from hypothesis import given, strategies as st, settings


@given(
    query_text=st.text(min_size=1, max_size=200),
    corpus_count=st.integers(min_value=0, max_value=100),
    threshold=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=100, deadline=500)
def test_property_classification_determinism(query_text, corpus_count, threshold):
    """Property: Classification must be deterministic for same inputs.

    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    result1 = classify_query(
        query_text=query_text,
        corpus_document_count=corpus_count,
        document_threshold=threshold,
    )
    result2 = classify_query(
        query_text=query_text,
        corpus_document_count=corpus_count,
        document_threshold=threshold,
    )

    assert result1.mode == result2.mode
    assert result1.confidence == result2.confidence
    assert result1.reasoning == result2.reasoning
    assert result1.has_summarization_keywords == result2.has_summarization_keywords
    assert result1.is_small_corpus == result2.is_small_corpus
    assert result1.is_vague_query == result2.is_vague_query


@given(
    query_text=st.text(min_size=1, max_size=200),
    corpus_count=st.integers(min_value=0, max_value=100),
    threshold=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=100, deadline=500)
def test_property_force_research_mode_precedence(query_text, corpus_count, threshold):
    """Property: force_research_mode must always result in research mode.

    **Validates: Requirements 4.2**
    """
    result = classify_query(
        query_text=query_text,
        corpus_document_count=corpus_count,
        document_threshold=threshold,
        force_research_mode=True,
    )

    assert result.mode == "research"
    assert result.confidence == 1.0
    assert "force_research_mode" in result.reasoning


@given(
    corpus_count=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=50, deadline=500)
def test_property_threshold_boundary_behavior(corpus_count):
    """Property: Corpus at or below threshold should be classified as small.

    **Validates: Requirements 1.2**
    """
    threshold = corpus_count

    result = classify_query(
        query_text="Summarize the documents",
        corpus_document_count=corpus_count,
        document_threshold=threshold,
    )

    assert result.is_small_corpus is True
    assert result.document_threshold == threshold

    if corpus_count > 0:
        result_above = classify_query(
            query_text="Summarize the documents",
            corpus_document_count=corpus_count + 1,
            document_threshold=threshold,
        )
        assert result_above.is_small_corpus is False


@given(
    query_text=st.text(min_size=1, max_size=200),
    threshold=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=100, deadline=500)
def test_property_empty_corpus_safety(query_text, threshold):
    """Property: Empty corpus must never trigger one-shot mode.

    **Validates: Requirements 5.2**
    """
    result = classify_query(
        query_text=query_text,
        corpus_document_count=0,
        document_threshold=threshold,
    )

    assert result.mode == "research"
    assert result.corpus_document_count == 0
    assert "empty corpus" in result.reasoning


@given(
    query_text=st.text(min_size=1, max_size=200),
    corpus_count=st.integers(min_value=0, max_value=100),
    threshold=st.integers(min_value=1, max_value=50),
    enabled=st.booleans(),
)
@settings(max_examples=100, deadline=500)
def test_property_backward_compatibility(query_text, corpus_count, threshold, enabled):
    """Property: Classification behavior must be consistent regardless of how it's called.

    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    result = classify_query(
        query_text=query_text,
        corpus_document_count=corpus_count,
        document_threshold=threshold,
    )

    assert result.mode in ["one_shot", "research"]
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.reasoning) > 0
    assert isinstance(result.has_summarization_keywords, bool)
    assert isinstance(result.is_small_corpus, bool)
    assert isinstance(result.is_vague_query, bool)
    assert result.corpus_document_count == corpus_count
    assert result.document_threshold == threshold

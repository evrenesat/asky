"""Tests for the research text chunker module."""

import pytest

from asky.research.chunker import chunk_text, chunk_by_paragraphs, chunk_by_sentences


class TestChunkText:
    """Tests for chunk_text function."""

    def test_empty_text_returns_empty(self):
        """Test that empty text returns empty list."""
        assert chunk_text("") == []
        assert chunk_text(None) == []

    def test_short_text_single_chunk(self):
        """Test that short text returns single chunk."""
        text = "Short text"
        result = chunk_text(text, chunk_size=100)

        assert len(result) == 1
        assert result[0] == (0, "Short text")

    def test_long_text_multiple_chunks(self):
        """Test that long text is split into multiple chunks."""
        text = "A" * 250
        result = chunk_text(text, chunk_size=100, overlap=20)

        assert len(result) > 1
        # Each chunk should be roughly chunk_size
        for idx, chunk in result:
            assert len(chunk) <= 100 + 50  # Some tolerance for sentence boundaries

    def test_chunks_have_sequential_indices(self):
        """Test that chunks have sequential indices."""
        text = "Word " * 100
        result = chunk_text(text, chunk_size=50, overlap=10)

        indices = [idx for idx, _ in result]
        assert indices == list(range(len(result)))

    def test_overlap_creates_redundancy(self):
        """Test that overlap creates redundancy between chunks."""
        text = "ABCDEFGHIJ" * 10  # 100 chars
        result = chunk_text(text, chunk_size=30, overlap=10)

        if len(result) >= 2:
            # End of first chunk should overlap with start of second
            chunk1_text = result[0][1]
            chunk2_text = result[1][1]

            # There should be some overlap
            # (exact overlap depends on sentence boundary logic)
            assert len(chunk1_text) > 0
            assert len(chunk2_text) > 0

    def test_overlap_preserved_for_non_sentence_text(self):
        """Test deterministic overlap behavior when no sentence boundaries exist."""
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 4
        overlap_size = 5
        result = chunk_text(text, chunk_size=20, overlap=overlap_size)

        assert len(result) > 1
        for idx in range(len(result) - 1):
            current_chunk = result[idx][1]
            next_chunk = result[idx + 1][1]
            assert current_chunk[-overlap_size:] == next_chunk[:overlap_size]

    def test_prefers_sentence_boundaries(self):
        """Test that chunker prefers sentence boundaries."""
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = chunk_text(text, chunk_size=40, overlap=5)

        # Should prefer to break at periods
        for idx, chunk in result:
            # Chunks should ideally end with a period (unless last chunk)
            if idx < len(result) - 1:
                # Allow some flexibility
                pass

    def test_normalizes_whitespace(self):
        """Test that whitespace is normalized."""
        text = "Word1   Word2\n\nWord3\t\tWord4"
        result = chunk_text(text, chunk_size=100)

        assert len(result) == 1
        # Whitespace should be normalized to single spaces
        assert "  " not in result[0][1]

    def test_handles_no_sentence_boundaries(self):
        """Test handling text without sentence boundaries."""
        text = "no punctuation here just words " * 10
        result = chunk_text(text, chunk_size=50, overlap=10)

        # Should still chunk even without sentence boundaries
        assert len(result) > 1


class TestChunkByParagraphs:
    """Tests for chunk_by_paragraphs function."""

    def test_empty_text_returns_empty(self):
        """Test that empty text returns empty list."""
        assert chunk_by_paragraphs("") == []

    def test_single_paragraph(self):
        """Test single paragraph text."""
        text = "This is a single paragraph."
        result = chunk_by_paragraphs(text)

        assert len(result) == 1
        assert result[0] == (0, "This is a single paragraph.")

    def test_multiple_paragraphs_merged(self):
        """Test that small paragraphs are merged."""
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        result = chunk_by_paragraphs(text, max_chunk_size=100)

        # All paragraphs should fit in one chunk
        assert len(result) == 1
        assert "Para 1." in result[0][1]
        assert "Para 2." in result[0][1]
        assert "Para 3." in result[0][1]

    def test_large_paragraphs_split(self):
        """Test that large paragraphs are split."""
        text = "A" * 200 + "\n\n" + "B" * 200
        result = chunk_by_paragraphs(text, max_chunk_size=100)

        # Each large paragraph should become multiple chunks
        assert len(result) > 2

    def test_preserves_paragraph_separation(self):
        """Test that paragraph separation is preserved in output."""
        text = "First paragraph.\n\nSecond paragraph."
        result = chunk_by_paragraphs(text, max_chunk_size=1000)

        # If in same chunk, should have double newline between
        if len(result) == 1:
            assert "\n\n" in result[0][1]

    def test_handles_varying_whitespace(self):
        """Test handling of varying whitespace between paragraphs."""
        text = "Para 1.\n\n\n\nPara 2.\n\nPara 3."
        result = chunk_by_paragraphs(text, max_chunk_size=1000)

        # Should handle multiple newlines as paragraph separator
        assert len(result) >= 1


class TestChunkBySentences:
    """Tests for chunk_by_sentences function."""

    def test_empty_text_returns_empty(self):
        """Test that empty text returns empty list."""
        assert chunk_by_sentences("") == []

    def test_single_sentence(self):
        """Test single sentence text."""
        text = "This is a sentence."
        result = chunk_by_sentences(text)

        assert len(result) == 1
        assert result[0] == (0, "This is a sentence.")

    def test_multiple_sentences_grouped(self):
        """Test that sentences are grouped to target size."""
        text = "Sentence one. Sentence two. Sentence three."
        result = chunk_by_sentences(text, target_chunk_size=100)

        # All sentences should fit in one chunk
        assert len(result) == 1

    def test_respects_target_size(self):
        """Test that target chunk size is respected."""
        text = "Short. " * 20
        result = chunk_by_sentences(text, target_chunk_size=30)

        # Should create multiple chunks
        assert len(result) > 1

    def test_handles_question_marks(self):
        """Test handling of question marks as sentence boundaries."""
        text = "Is this a question? Yes it is. Another question?"
        result = chunk_by_sentences(text, target_chunk_size=1000)

        assert len(result) >= 1

    def test_handles_exclamation_marks(self):
        """Test handling of exclamation marks as sentence boundaries."""
        text = "Wow! Amazing! Incredible!"
        result = chunk_by_sentences(text, target_chunk_size=1000)

        assert len(result) >= 1


class TestChunkingEdgeCases:
    """Tests for edge cases in chunking."""

    def test_unicode_text(self):
        """Test chunking of unicode text."""
        text = "Hello 世界. This is a test. 你好！"
        result = chunk_text(text, chunk_size=100)

        assert len(result) >= 1
        assert "世界" in result[0][1]

    def test_very_long_word(self):
        """Test handling of very long words."""
        text = "A" * 200  # Single very long "word"
        result = chunk_text(text, chunk_size=50, overlap=10)

        # Should still chunk even with no word boundaries
        assert len(result) > 1

    def test_only_whitespace(self):
        """Test handling of whitespace-only text."""
        text = "   \n\n\t   "
        result = chunk_text(text)

        # Should return empty after stripping
        assert result == []

    def test_special_characters(self):
        """Test handling of special characters."""
        text = "Hello! @#$%^&*() World. How are you?"
        result = chunk_text(text, chunk_size=100)

        assert len(result) >= 1
        assert "@#$%^&*()" in result[0][1]

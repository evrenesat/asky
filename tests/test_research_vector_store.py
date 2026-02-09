"""Tests for the research vector store module."""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from asky.research.vector_store import cosine_similarity, VectorStore


class TestCosineSimilarity:
    """Tests for cosine_similarity function."""

    def test_identical_vectors(self):
        """Test that identical vectors have similarity 1.0."""
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]

        result = cosine_similarity(a, b)
        assert abs(result - 1.0) < 0.0001

    def test_orthogonal_vectors(self):
        """Test that orthogonal vectors have similarity 0.0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]

        result = cosine_similarity(a, b)
        assert abs(result - 0.0) < 0.0001

    def test_opposite_vectors(self):
        """Test that opposite vectors have similarity -1.0."""
        a = [1.0, 2.0, 3.0]
        b = [-1.0, -2.0, -3.0]

        result = cosine_similarity(a, b)
        assert abs(result - (-1.0)) < 0.0001

    def test_empty_vectors(self):
        """Test that empty vectors return 0.0."""
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([1.0], []) == 0.0
        assert cosine_similarity([], [1.0]) == 0.0

    def test_different_length_vectors(self):
        """Test that different length vectors return 0.0."""
        a = [1.0, 2.0]
        b = [1.0, 2.0, 3.0]

        result = cosine_similarity(a, b)
        assert result == 0.0

    def test_zero_vector(self):
        """Test that zero vectors return 0.0."""
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]

        result = cosine_similarity(a, b)
        assert result == 0.0

    def test_similar_vectors(self):
        """Test that similar vectors have high similarity."""
        a = [1.0, 2.0, 3.0]
        b = [1.1, 2.1, 3.1]

        result = cosine_similarity(a, b)
        assert result > 0.99  # Very similar

    def test_dissimilar_vectors(self):
        """Test that dissimilar vectors have lower similarity."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 0.0, 1.0]

        result = cosine_similarity(a, b)
        assert result == 0.0


class TestVectorStore:
    """Tests for VectorStore class."""

    @pytest.fixture
    def mock_embedding_client(self):
        """Create a mock embedding client."""
        client = MagicMock()
        client.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        client.embed_single.return_value = [0.1, 0.2, 0.3]
        client.model = "test-model"
        return client

    @pytest.fixture
    def vector_store(self, tmp_path, mock_embedding_client):
        """Create a VectorStore instance for testing."""
        # Reset singleton
        VectorStore._instance = None

        db_path = str(tmp_path / "test_vectors.db")

        # Initialize the research cache tables first
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS research_cache (
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                url_hash TEXT,
                content TEXT,
                title TEXT,
                summary TEXT,
                summary_status TEXT,
                links_json TEXT,
                fetch_timestamp TEXT,
                expires_at TEXT,
                content_hash TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS content_chunks (
                id INTEGER PRIMARY KEY,
                cache_id INTEGER,
                chunk_index INTEGER,
                chunk_text TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS link_embeddings (
                id INTEGER PRIMARY KEY,
                cache_id INTEGER,
                link_text TEXT,
                link_url TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT
            )
        """
        )

        # Insert a test cache entry
        c.execute(
            """
            INSERT INTO research_cache (id, url, url_hash, content, created_at, updated_at)
            VALUES (1, 'http://test.com', 'abc123', 'Test content', '2024-01-01', '2024-01-01')
        """
        )

        conn.commit()
        conn.close()

        store = VectorStore(db_path=db_path, embedding_client=mock_embedding_client)
        return store

    def test_store_chunk_embeddings(self, vector_store, mock_embedding_client):
        """Test storing chunk embeddings."""
        chunks = [(0, "First chunk"), (1, "Second chunk")]

        stored = vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        assert stored == 2
        assert vector_store.has_chunk_embeddings(1)

    def test_store_chunk_embeddings_empty(self, vector_store):
        """Test storing empty chunks returns 0."""
        stored = vector_store.store_chunk_embeddings(cache_id=1, chunks=[])
        assert stored == 0

    def test_store_link_embeddings(self, vector_store, mock_embedding_client):
        """Test storing link embeddings."""
        links = [
            {"text": "Link 1", "href": "http://link1.com"},
            {"text": "Link 2", "href": "http://link2.com"},
        ]

        stored = vector_store.store_link_embeddings(cache_id=1, links=links)

        assert stored == 2
        assert vector_store.has_link_embeddings(1)

    def test_store_link_embeddings_empty(self, vector_store):
        """Test storing empty links returns 0."""
        stored = vector_store.store_link_embeddings(cache_id=1, links=[])
        assert stored == 0

    def test_search_chunks(self, vector_store, mock_embedding_client):
        """Test searching chunks by query."""
        from asky.research.embeddings import EmbeddingClient

        # Store some chunks first
        chunks = [(0, "Machine learning"), (1, "Deep learning")]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        # Mock the search embedding
        mock_embedding_client.embed_single.return_value = [0.1, 0.2, 0.3]

        results = vector_store.search_chunks(cache_id=1, query="AI learning", top_k=2)

        assert len(results) == 2
        # Results should be (chunk_text, similarity_score) tuples
        for text, score in results:
            assert isinstance(text, str)
            assert isinstance(score, float)

    def test_search_chunks_empty_query(self, vector_store):
        """Test that empty query returns empty results."""
        results = vector_store.search_chunks(cache_id=1, query="")
        assert results == []

    def test_rank_links_by_relevance(self, vector_store, mock_embedding_client):
        """Test ranking links by relevance."""
        # Store some links first
        links = [
            {"text": "AI News", "href": "http://ai.com"},
            {"text": "Weather", "href": "http://weather.com"},
        ]
        vector_store.store_link_embeddings(cache_id=1, links=links)

        # Mock the search embedding
        mock_embedding_client.embed_single.return_value = [0.1, 0.2, 0.3]

        results = vector_store.rank_links_by_relevance(
            cache_id=1, query="artificial intelligence", top_k=2
        )

        assert len(results) == 2
        # Results should be (link_dict, similarity_score) tuples
        for link, score in results:
            assert "text" in link
            assert "href" in link
            assert isinstance(score, float)

    def test_rank_links_empty_query(self, vector_store):
        """Test that empty query returns empty results."""
        results = vector_store.rank_links_by_relevance(cache_id=1, query="")
        assert results == []

    def test_has_chunk_embeddings_false(self, vector_store):
        """Test has_chunk_embeddings returns False when none exist."""
        # cache_id 999 doesn't have any chunks
        assert not vector_store.has_chunk_embeddings(999)

    def test_has_link_embeddings_false(self, vector_store):
        """Test has_link_embeddings returns False when none exist."""
        # cache_id 999 doesn't have any link embeddings
        assert not vector_store.has_link_embeddings(999)

    def test_has_chunk_embeddings_for_model(self, vector_store):
        """Test model-aware chunk embedding freshness checks."""
        chunks = [(0, "First chunk"), (1, "Second chunk")]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        assert vector_store.has_chunk_embeddings_for_model(1, "test-model") is True
        assert vector_store.has_chunk_embeddings_for_model(1, "other-model") is False

    def test_has_link_embeddings_for_model(self, vector_store):
        """Test model-aware link embedding freshness checks."""
        links = [
            {"text": "Link 1", "href": "http://link1.com"},
            {"text": "Link 2", "href": "http://link2.com"},
        ]
        vector_store.store_link_embeddings(cache_id=1, links=links)

        assert vector_store.has_link_embeddings_for_model(1, "test-model") is True
        assert vector_store.has_link_embeddings_for_model(1, "other-model") is False

    def test_store_chunk_embeddings_upserts_to_chroma(self, vector_store):
        """Test that chunk embeddings are also written to Chroma when available."""
        fake_collection = MagicMock()
        with patch.object(
            vector_store,
            "_get_chroma_collection",
            return_value=fake_collection,
        ):
            stored = vector_store.store_chunk_embeddings(
                cache_id=1,
                chunks=[(0, "Chunk A"), (1, "Chunk B")],
            )

        assert stored == 2
        fake_collection.delete.assert_called_once_with(where={"cache_id": 1})
        fake_collection.add.assert_called_once()
        add_kwargs = fake_collection.add.call_args.kwargs
        assert add_kwargs["ids"] == ["chunk:1:0", "chunk:1:1"]
        assert add_kwargs["documents"] == ["Chunk A", "Chunk B"]

    def test_search_chunks_prefers_chroma_results(self, vector_store):
        """Test that non-empty Chroma query results short-circuit SQLite fallback."""
        with patch.object(
            vector_store,
            "_search_chunks_with_chroma",
            return_value=[("From Chroma", 0.91)],
        ):
            with patch.object(vector_store, "_search_chunks_with_sqlite") as sqlite_mock:
                results = vector_store.search_chunks(
                    cache_id=1,
                    query="test query",
                    top_k=1,
                )

        assert results == [("From Chroma", 0.91)]
        sqlite_mock.assert_not_called()

    def test_search_chunks_with_chroma_uses_and_metadata_filter(self, vector_store):
        """Chroma query should use single-operator metadata filter for compatibility."""
        fake_collection = MagicMock()
        fake_collection.query.return_value = {
            "documents": [["From Chroma"]],
            "distances": [[0.1]],
        }

        with patch.object(
            vector_store,
            "_get_chroma_collection",
            return_value=fake_collection,
        ):
            _ = vector_store._search_chunks_with_chroma(
                cache_id=1,
                query_embedding=[0.1, 0.2, 0.3],
                top_k=1,
            )

        where_filter = fake_collection.query.call_args.kwargs["where"]
        assert where_filter == {
            "$and": [
                {"cache_id": 1},
                {"embedding_model": "test-model"},
            ]
        }

    def test_search_chunks_hybrid_returns_ranked_dicts(self, vector_store):
        """Test hybrid chunk search returns score-rich dictionaries."""
        chunks = [
            (0, "machine learning design notes"),
            (1, "deployment checklist and operations"),
        ]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        results = vector_store.search_chunks_hybrid(
            cache_id=1,
            query="machine learning operations",
            top_k=2,
            dense_weight=0.7,
            min_score=0.0,
        )

        assert len(results) == 2
        assert "text" in results[0]
        assert "score" in results[0]
        assert "dense_score" in results[0]
        assert "lexical_score" in results[0]

    def test_bm25_scores_available_when_fts_present(self, vector_store):
        """Test BM25 lexical scoring returns results when FTS index exists."""
        conn = sqlite3.connect(vector_store.db_path)
        c = conn.cursor()
        try:
            c.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS content_chunks_fts
                USING fts5(
                    chunk_text,
                    content='content_chunks',
                    content_rowid='id'
                )
                """
            )
            c.execute(
                """
                CREATE TRIGGER IF NOT EXISTS content_chunks_ai
                AFTER INSERT ON content_chunks
                BEGIN
                    INSERT INTO content_chunks_fts(rowid, chunk_text)
                    VALUES (new.id, new.chunk_text);
                END
                """
            )
            c.execute(
                """
                CREATE TRIGGER IF NOT EXISTS content_chunks_ad
                AFTER DELETE ON content_chunks
                BEGIN
                    INSERT INTO content_chunks_fts(content_chunks_fts, rowid, chunk_text)
                    VALUES('delete', old.id, old.chunk_text);
                END
                """
            )
            c.execute(
                """
                CREATE TRIGGER IF NOT EXISTS content_chunks_au
                AFTER UPDATE ON content_chunks
                BEGIN
                    INSERT INTO content_chunks_fts(content_chunks_fts, rowid, chunk_text)
                    VALUES('delete', old.id, old.chunk_text);
                    INSERT INTO content_chunks_fts(rowid, chunk_text)
                    VALUES (new.id, new.chunk_text);
                END
                """
            )
            c.execute(
                "INSERT INTO content_chunks_fts(content_chunks_fts) VALUES('rebuild')"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            pytest.skip(f"SQLite FTS5 unavailable in this environment: {exc}")
        finally:
            conn.close()

        chunks = [
            (0, "machine learning model architecture"),
            (1, "sports weather and travel notes"),
        ]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        scores = vector_store._get_bm25_scores(
            cache_id=1,
            query="machine learning architecture",
            limit=10,
        )

        assert scores
        assert 0 in scores

    def test_search_returns_sorted_results(self, vector_store, mock_embedding_client):
        """Test that search results are sorted by similarity descending."""
        chunks = [(0, "First"), (1, "Second"), (2, "Third")]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        results = vector_store.search_chunks(cache_id=1, query="test", top_k=3)

        # Results should be sorted by score descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_limits_results(self, vector_store, mock_embedding_client):
        """Test that top_k limits the number of results."""
        # Add more chunks
        mock_embedding_client.embed.return_value = [[0.1] * 3 for _ in range(5)]
        chunks = [(i, f"Chunk {i}") for i in range(5)]
        vector_store.store_chunk_embeddings(cache_id=1, chunks=chunks)

        results = vector_store.search_chunks(cache_id=1, query="test", top_k=2)

        assert len(results) == 2


class TestGetVectorStore:
    """Tests for the get_vector_store helper."""

    def test_get_vector_store_returns_singleton(self, tmp_path):
        """Test that get_vector_store returns singleton."""
        from asky.research.vector_store import VectorStore, get_vector_store

        VectorStore._instance = None

        store1 = get_vector_store()
        store2 = get_vector_store()

        assert store1 is store2


class TestVectorStoreFindingsMethods:
    """Tests for VectorStore finding embedding methods."""

    @pytest.fixture
    def mock_embedding_client(self):
        """Create a mock embedding client."""
        client = MagicMock()
        client.embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        client.embed_single.return_value = [0.1, 0.2, 0.3]
        client.model = "test-model"
        return client

    @pytest.fixture
    def vector_store_with_findings(self, tmp_path, mock_embedding_client):
        """Create a VectorStore instance with research_findings table."""
        # Reset singleton
        VectorStore._instance = None

        db_path = str(tmp_path / "test_findings_vectors.db")

        # Initialize the research_findings table
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS research_findings (
                id INTEGER PRIMARY KEY,
                finding_text TEXT NOT NULL,
                source_url TEXT,
                source_title TEXT,
                tags TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                session_id TEXT
            )
        """
        )

        # Insert some test findings
        c.execute(
            """
            INSERT INTO research_findings (id, finding_text, source_url, source_title, tags, created_at, session_id)
            VALUES (1, 'Machine learning is transforming healthcare', 'http://health.com', 'Health News', '["ml", "health"]', '2024-01-01', 'session_a')
        """
        )
        c.execute(
            """
            INSERT INTO research_findings (id, finding_text, source_url, source_title, tags, created_at, session_id)
            VALUES (2, 'Climate change affects agriculture', 'http://env.com', 'Environment', '["climate", "agriculture"]', '2024-01-02', 'session_b')
        """
        )

        conn.commit()
        conn.close()

        store = VectorStore(db_path=db_path, embedding_client=mock_embedding_client)
        return store

    def test_store_finding_embedding(self, vector_store_with_findings, mock_embedding_client):
        """Test storing embedding for a finding."""
        result = vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="Machine learning is transforming healthcare"
        )

        assert result is True
        assert vector_store_with_findings.has_finding_embedding(1)

    def test_store_finding_embedding_empty_text(self, vector_store_with_findings):
        """Test that empty text returns False."""
        result = vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text=""
        )

        assert result is False

    def test_store_finding_embedding_whitespace_text(self, vector_store_with_findings):
        """Test that whitespace-only text returns False."""
        result = vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="   \n\t  "
        )

        assert result is False

    def test_search_findings_no_embeddings(self, vector_store_with_findings, mock_embedding_client):
        """Test searching findings when none have embeddings."""
        results = vector_store_with_findings.search_findings(query="healthcare")

        assert results == []

    def test_search_findings_with_embeddings(self, vector_store_with_findings, mock_embedding_client):
        """Test searching findings after embedding them."""
        from asky.research.embeddings import EmbeddingClient

        # Store embeddings for both findings
        vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="Machine learning is transforming healthcare"
        )
        vector_store_with_findings.store_finding_embedding(
            finding_id=2,
            finding_text="Climate change affects agriculture"
        )

        results = vector_store_with_findings.search_findings(query="medical AI")

        assert len(results) == 2
        # Results should be (finding_dict, similarity_score) tuples
        for finding, score in results:
            assert "finding_text" in finding
            assert "source_url" in finding
            assert "tags" in finding
            assert isinstance(score, float)

    def test_search_findings_empty_query(self, vector_store_with_findings):
        """Test that empty query returns empty results."""
        results = vector_store_with_findings.search_findings(query="")

        assert results == []

    def test_search_findings_respects_top_k(self, vector_store_with_findings, mock_embedding_client):
        """Test that top_k limits results."""
        # Add embeddings
        vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="Machine learning is transforming healthcare"
        )
        vector_store_with_findings.store_finding_embedding(
            finding_id=2,
            finding_text="Climate change affects agriculture"
        )

        results = vector_store_with_findings.search_findings(query="test", top_k=1)

        assert len(results) == 1

    def test_search_findings_filters_by_session_id(
        self, vector_store_with_findings, mock_embedding_client
    ):
        """Test that finding retrieval can be scoped to a specific session."""
        vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="Machine learning is transforming healthcare",
        )
        vector_store_with_findings.store_finding_embedding(
            finding_id=2,
            finding_text="Climate change affects agriculture",
        )

        scoped_results = vector_store_with_findings.search_findings(
            query="test",
            session_id="session_a",
        )

        assert len(scoped_results) == 1
        assert scoped_results[0][0]["session_id"] == "session_a"

    def test_search_findings_returns_sorted(self, vector_store_with_findings, mock_embedding_client):
        """Test that results are sorted by similarity descending."""
        # Add embeddings
        vector_store_with_findings.store_finding_embedding(
            finding_id=1,
            finding_text="Machine learning is transforming healthcare"
        )
        vector_store_with_findings.store_finding_embedding(
            finding_id=2,
            finding_text="Climate change affects agriculture"
        )

        results = vector_store_with_findings.search_findings(query="test")

        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_has_finding_embedding_false(self, vector_store_with_findings):
        """Test has_finding_embedding returns False when no embedding."""
        assert not vector_store_with_findings.has_finding_embedding(1)

    def test_has_finding_embedding_nonexistent(self, vector_store_with_findings):
        """Test has_finding_embedding returns False for nonexistent finding."""
        assert not vector_store_with_findings.has_finding_embedding(99999)

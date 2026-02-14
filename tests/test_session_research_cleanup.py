import pytest
import argparse
from unittest.mock import MagicMock, patch
from datetime import datetime

from asky.research.cache import ResearchCache
from asky.research.vector_store import VectorStore
from asky.api import AskyClient, AskyConfig
from asky.cli.sessions import handle_clean_session_research_command
from asky.config import MODELS, DEFAULT_MODEL


class TestSessionResearchCleanup:
    @pytest.fixture(autouse=True)
    def reset_singletons(self):
        ResearchCache._instance = None
        VectorStore._instance = None
        yield
        ResearchCache._instance = None
        VectorStore._instance = None

    @pytest.fixture
    def cache(self, tmp_path):
        db_path = tmp_path / "test_research.db"
        cache = ResearchCache(str(db_path))
        cache._initialized = False
        cache.__init__(str(db_path))
        return cache

    @pytest.fixture
    def vector_store(self, tmp_path):
        db_path = tmp_path / "test_research.db"
        persist_dir = tmp_path / "chroma"
        mock_embedding = MagicMock()
        mock_embedding.model = "test-model"

        with patch(
            "asky.research.vector_store.get_embedding_client",
            return_value=mock_embedding,
        ):
            rc = ResearchCache(db_path=str(db_path))
            rc._initialized = False
            rc.__init__(db_path=str(db_path))

            store = VectorStore(
                db_path=str(db_path), chroma_persist_directory=str(persist_dir)
            )
            store._initialized = False
            store.__init__(db_path=str(db_path))
            return store

    def test_vector_store_delete_findings_by_session(self, vector_store):
        mock_collection = MagicMock()
        now = datetime.now().isoformat()
        with patch.object(
            vector_store, "_get_chroma_collection", return_value=mock_collection
        ):
            conn = vector_store._get_conn()
            c = conn.cursor()
            c.execute(
                "INSERT INTO research_findings (finding_text, session_id, created_at) VALUES (?, ?, ?)",
                ("F1", "session_A", now),
            )
            c.execute(
                "INSERT INTO research_findings (finding_text, session_id, created_at) VALUES (?, ?, ?)",
                ("F2", "session_B", now),
            )
            conn.commit()
            conn.close()

            deleted = vector_store.delete_findings_by_session("session_A")
            assert deleted == 1
            mock_collection.delete.assert_called_once()

            conn = vector_store._get_conn()
            c = conn.cursor()
            c.execute(
                "SELECT count(*) FROM research_findings WHERE session_id = 'session_A'"
            )
            assert c.fetchone()[0] == 0
            conn.close()

    @patch("asky.research.vector_store.VectorStore.__new__")
    def test_asky_client_cleanup_orchestration(self, mock_vs_new):
        mock_vs = MagicMock()
        mock_vs_new.return_value = mock_vs
        mock_vs._initialized = True
        mock_vs.delete_findings_by_session.return_value = 5

        valid_model = list(MODELS.keys())[0] if MODELS else DEFAULT_MODEL
        client = AskyClient(AskyConfig(model_alias=valid_model))
        results = client.cleanup_session_research_data("session_123")
        assert results["deleted"] == 5

    @patch("asky.storage.get_session_by_id")
    @patch("asky.api.AskyClient.cleanup_session_research_data")
    def test_cli_handler_dispatch(self, mock_cleanup, mock_get_id):
        valid_model = list(MODELS.keys())[0] if MODELS else DEFAULT_MODEL
        args = argparse.Namespace(clean_session_research="123", model=valid_model)
        mock_session = MagicMock(id=123, name="Test")
        mock_get_id.return_value = mock_session
        mock_cleanup.return_value = {"deleted": 7}

        assert handle_clean_session_research_command(args) is True
        mock_cleanup.assert_called_once_with("123")

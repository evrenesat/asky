import json
import os
import shutil
from datetime import datetime
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import threading

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "research_corpus"
RESEARCH_QUERIES_ANSWERS_PATH = RESEARCH_FIXTURE_ROOT / "queries_answers.md"
REAL_PROVIDER_URL = "https://openrouter.ai/api/v1/chat/completions"
REAL_PROVIDER_DEFAULT_MODEL_ID = "google/gemini-2.0-flash-lite-001"


def pytest_collection_modifyitems(items):
    for item in items:
        if "cli_recorded" in str(item.fspath):
            if "subprocess" in item.nodeid:
                item.add_marker(pytest.mark.subprocess_cli)
            else:
                item.add_marker(pytest.mark.recorded_cli)
                item.add_marker(pytest.mark.vcr)


@pytest.fixture(scope="module")
def vcr_config():
    """Configure VCR with strict record mode rules and redact sensitive headers."""
    record_mode = "once" if os.environ.get("ASKY_CLI_RECORD") else "none"
    return {
        "filter_headers": ["authorization", "x-goog-api-key", "x-api-key", "api-key"],
        "record_mode": record_mode,
        "match_on": ["method", "scheme", "host", "path", "query"],
    }


@pytest.fixture(autouse=True)
def freeze_time(monkeypatch):
    """Freeze datetime to a deterministic value for replay stability."""
    iso_time = os.environ.get("ASKY_CLI_FIXED_TIME", "2024-01-01T12:00:00+00:00")
    fixed_dt = datetime.fromisoformat(iso_time)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_dt if tz is None else fixed_dt.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return fixed_dt.replace(tzinfo=None)

    monkeypatch.setattr("asky.core.prompts.datetime", FrozenDateTime)


class _RecordedFakeLLMHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        body_size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_size).decode("utf-8")
        payload = json.loads(body)
        messages = payload.get("messages", [])
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = str(msg.get("content", "")).lower()
                break

        content = "ok"
        if "capital of france" in user_text:
            content = "Paris"
        elif "say exactly 'pong'" in user_text:
            content = "PONG"
        elif "are you claude" in user_text:
            content = "yes"
        elif "2+2" in user_text:
            content = "4"
        elif "what is my favorite color" in user_text:
            content = "blue"
        elif "interactive" in user_text:
            content = "interactive"
        elif "software engineering" in user_text:
            content = "software engineering"
        elif "hello" in user_text:
            content = "Hello from recorded fake LLM."

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = {
            "id": "chatcmpl-recorded",
            "object": "chat.completion",
            "created": 1704110400,
            "model": payload.get("model", "fake-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


@pytest.fixture(scope="session")
def fake_llm_server():
    """Session-scoped fake OpenAI-compatible endpoint for recorded in-process tests."""
    server = HTTPServer(("127.0.0.1", 0), _RecordedFakeLLMHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"host": host, "port": port, "url": f"http://{host}:{port}/v1/chat/completions"}
    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)


def _is_real_recorded_case(request: pytest.FixtureRequest) -> bool:
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    node_id = str(getattr(request.node, "nodeid", ""))
    if node_path.endswith("/test_cli_real_model_recorded.py") or "test_cli_real_model_recorded.py" in node_id:
        return True
    marker = request.node.get_closest_marker("real_recorded_cli")
    return marker is not None


def _write_model_and_api_configs(
    *,
    config_dir: Path,
    is_real_recorded: bool,
    fake_llm_url: str,
) -> None:
    if is_real_recorded:
        model_id = os.environ.get("ASKY_CLI_REAL_MODEL_ID", REAL_PROVIDER_DEFAULT_MODEL_ID)
        (config_dir / "models.toml").write_text(
            '[models.gf]\n'
            f'id = "{model_id}"\n'
            'api = "openrouter"\n'
            "context_size = 32000\n",
            encoding="utf-8",
        )
        (config_dir / "api.toml").write_text(
            "[api.openrouter]\n"
            f'url = "{REAL_PROVIDER_URL}"\n'
            'api_key_env = "OPENROUTER_API_KEY"\n',
            encoding="utf-8",
        )
        return

    (config_dir / "models.toml").write_text(
        '[models.gf]\n'
        'id = "fake/gf"\n'
        'api = "fake"\n'
        "context_size = 32000\n"
        "\n"
        "[models.sonnet]\n"
        'id = "fake/sonnet"\n'
        'api = "fake"\n'
        "context_size = 32000\n",
        encoding="utf-8",
    )
    (config_dir / "api.toml").write_text(
        "[api.fake]\n"
        f'url = "{fake_llm_url}"\n'
        'api_key = "fake-key"\n',
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def recorded_cli_environment(
    request: pytest.FixtureRequest,
    test_home_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Configure isolated runtime for recorded in-process tests."""
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    if "tests/integration/cli_recorded/" not in node_path:
        return
    if "test_cli_interactive_subprocess.py" in node_path:
        return

    is_real_recorded = _is_real_recorded_case(request)
    if (
        is_real_recorded
        and os.environ.get("ASKY_CLI_RECORD")
        and not os.environ.get("OPENROUTER_API_KEY")
    ):
        pytest.fail(
            "OPENROUTER_API_KEY is required to refresh real_recorded_cli cassettes."
        )

    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    digest = sha1(request.node.nodeid.encode("utf-8")).hexdigest()[:12]
    fake_home = test_home_root / worker_id / f"recorded-{digest}"
    if fake_home.exists():
        shutil.rmtree(fake_home)
    config_dir = fake_home / ".config" / "asky"
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "general.toml").write_text(
        '[general]\n'
        'default_model = "gf"\n'
        'summarization_model = "gf"\n'
        'interface_model = "gf"\n'
        "\n"
        "[limits]\n"
        "max_retries = 1\n"
        "initial_backoff = 0\n",
        encoding="utf-8",
    )

    fake_llm_url = ""
    if not is_real_recorded:
        fake_llm_server = request.getfixturevalue("fake_llm_server")
        fake_llm_url = str(fake_llm_server["url"])

    _write_model_and_api_configs(
        config_dir=config_dir,
        is_real_recorded=is_real_recorded,
        fake_llm_url=fake_llm_url,
    )

    stable_research_root = test_home_root
    stable_research_root.mkdir(parents=True, exist_ok=True)

    (config_dir / "research.toml").write_text(
        "[research]\n"
        f'local_document_roots = ["{stable_research_root}", "{RESEARCH_FIXTURE_ROOT}"]\n'
        "allow_absolute_paths_outside_roots = true\n",
        encoding="utf-8",
    )
    (config_dir / "prompts.toml").write_text("", encoding="utf-8")
    (config_dir / "user.toml").write_text("", encoding="utf-8")
    (config_dir / "plugins.toml").write_text("", encoding="utf-8")
    (config_dir / "xmpp.toml").write_text("", encoding="utf-8")
    (config_dir / "voice_transcriber.toml").write_text("", encoding="utf-8")
    (config_dir / "image_transcriber.toml").write_text("", encoding="utf-8")
    (config_dir / "push_data.toml").write_text("", encoding="utf-8")
    (config_dir / "memory.toml").write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ASKY_HOME", str(config_dir))
    monkeypatch.setenv("ASKY_DB_PATH", str(fake_home / "test.db"))
    monkeypatch.setenv(
        "ASKY_CLI_MODEL_ALIAS",
        os.environ.get("ASKY_CLI_MODEL_ALIAS", "gf"),
    )
    monkeypatch.setenv("ASKY_CLI_FAKE_EMBED", "1")

    import asky.research.embeddings as embeddings_mod

    def _fake_embed(self, texts):
        return [[0.0] * 8 for text in texts if str(text).strip()]

    def _fake_embed_single(self, text):
        return [0.0] * 8

    monkeypatch.setattr(embeddings_mod.EmbeddingClient, "embed", _fake_embed)
    monkeypatch.setattr(
        embeddings_mod.EmbeddingClient, "embed_single", _fake_embed_single
    )
    monkeypatch.setattr(embeddings_mod.EmbeddingClient, "is_available", lambda _: True)

    import asky.research.chunker as chunker_mod

    monkeypatch.setattr(chunker_mod, "_get_embedding_tokenizer", lambda: (None, 0))


@pytest.fixture
def canonical_model_alias() -> str:
    """Resolve canonical model alias with env override support."""
    return os.environ.get("ASKY_CLI_MODEL_ALIAS", "gf")


@pytest.fixture
def local_research_corpus() -> Path:
    """Fixture corpus for subject-awareness regression checks."""
    corpus_dir = RESEARCH_FIXTURE_ROOT / "subject_awareness_v1"
    if not corpus_dir.exists():
        raise RuntimeError(f"Missing fixture corpus: {corpus_dir}")
    return corpus_dir.resolve()


@pytest.fixture
def realistic_research_sources() -> dict[str, Path]:
    """Larger realistic sources used for fact-grounded research assertions."""
    sources = {
        "research_paper": RESEARCH_FIXTURE_ROOT / "2025.11.07.687135v2.pdf",
        "sqlite_architecture": RESEARCH_FIXTURE_ROOT / "sqlite-documentation.epub",
        "udhr": RESEARCH_FIXTURE_ROOT / "UDHR.pdf",
        "oauth": RESEARCH_FIXTURE_ROOT / "rfc6749.pdf",
    }
    for source in sources.values():
        if not source.exists():
            raise RuntimeError(f"Missing realistic source fixture: {source}")
    return {key: value.resolve() for key, value in sources.items()}


@pytest.fixture
def research_queries_expected_facts() -> dict[str, list[str]]:
    """Ground-truth fact fragments mirrored from queries_answers.md."""
    if not RESEARCH_QUERIES_ANSWERS_PATH.exists():
        raise RuntimeError(
            f"Missing expected queries/answers fixture: {RESEARCH_QUERIES_ANSWERS_PATH}"
        )
    queries_answers_text = RESEARCH_QUERIES_ANSWERS_PATH.read_text(encoding="utf-8").lower()
    expected = {
        "udhr_article14": [
            "non-political crimes",
            "purposes and principles",
        ],
        "oauth_grants": [
            "authorization code",
            "implicit",
            "resource owner password credentials",
            "client credentials",
        ],
        "sqlite_vdbe": [
            "bytecode",
            "disk i/o",
            "virtual database engine",
        ],
    }
    for fact_fragments in expected.values():
        for fragment in fact_fragments:
            if fragment.lower() not in queries_answers_text:
                raise RuntimeError(
                    "queries_answers.md is missing expected fact fragment: "
                    f"{fragment}"
                )
    return expected

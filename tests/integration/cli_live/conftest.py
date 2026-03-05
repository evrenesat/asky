import os
import shutil
from hashlib import sha1
from pathlib import Path

import pytest

RESEARCH_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "research_corpus"
RESEARCH_QUERIES_ANSWERS_PATH = RESEARCH_FIXTURE_ROOT / "queries_answers.md"
REAL_PROVIDER_URL = "https://openrouter.ai/api/v1/chat/completions"
REAL_PROVIDER_DEFAULT_MODEL_ID = "google/gemini-2.0-flash-lite-001"


@pytest.fixture(autouse=True)
def live_cli_environment(
    request: pytest.FixtureRequest,
    test_home_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Configure isolated real-provider environment for live research integration tests."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.fail("OPENROUTER_API_KEY is required for live_research tests.")

    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    digest = sha1(request.node.nodeid.encode("utf-8")).hexdigest()[:12]
    fake_home = test_home_root / worker_id / f"live-{digest}"
    if fake_home.exists():
        shutil.rmtree(fake_home)

    config_dir = fake_home / ".config" / "asky"
    config_dir.mkdir(parents=True, exist_ok=True)

    model_id = os.environ.get("ASKY_CLI_REAL_MODEL_ID", REAL_PROVIDER_DEFAULT_MODEL_ID)

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

    stable_research_root = test_home_root
    stable_research_root.mkdir(parents=True, exist_ok=True)
    (config_dir / "research.toml").write_text(
        "[research]\n"
        f'local_document_roots = ["{stable_research_root}", "{RESEARCH_FIXTURE_ROOT}"]\n'
        "allow_absolute_paths_outside_roots = true\n",
        encoding="utf-8",
    )

    for name in (
        "prompts.toml",
        "user.toml",
        "plugins.toml",
        "xmpp.toml",
        "voice_transcriber.toml",
        "image_transcriber.toml",
        "push_data.toml",
        "memory.toml",
    ):
        (config_dir / name).write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ASKY_HOME", str(config_dir))
    monkeypatch.setenv("ASKY_DB_PATH", str(fake_home / "test.db"))
    monkeypatch.setenv("ASKY_CLI_MODEL_ALIAS", "gf")


@pytest.fixture
def local_research_corpus() -> Path:
    corpus_dir = RESEARCH_FIXTURE_ROOT / "subject_awareness_v1"
    if not corpus_dir.exists():
        raise RuntimeError(f"Missing fixture corpus: {corpus_dir}")
    return corpus_dir.resolve()


@pytest.fixture
def realistic_research_sources() -> dict[str, Path]:
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
    }
    for fact_fragments in expected.values():
        for fragment in fact_fragments:
            if fragment.lower() not in queries_answers_text:
                raise RuntimeError(
                    "queries_answers.md is missing expected fact fragment: "
                    f"{fragment}"
                )
    return expected

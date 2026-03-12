import contextlib
import importlib
import json
import os
import re
import sqlite3
import sys
import time
from io import StringIO
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest


class CliRunResult:
    def __init__(self, exit_code: int, stdout: str, stderr: str):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


TRANSIENT_PROVIDER_ERROR_PATTERNS = (
    "an error occurred: 'choices'",
    "internal server error",
    "rate limit",
    "service unavailable",
    "temporarily unavailable",
)

MODULE_RELOAD_ORDER = (
    "asky.config.loader",
    "asky.config",
    "asky.storage.sqlite",
    "asky.storage",
    "asky.plugins.manager",
    "asky.plugins.runtime",
    "asky.core.api_client",
    "asky.core.tool_registry_factory",
    "asky.core.session_manager",
    "asky.core.engine",
    "asky.core",
    "asky.research.adapters",
    "asky.research.cache",
    "asky.research.vector_store",
    "asky.cli.local_ingestion_flow",
    "asky.api.preload_policy",
    "asky.api.interface_query_policy",
    "asky.api.preload",
    "asky.api.session",
    "asky.api.client",
    "asky.api",
    "asky.cli.display",
    "asky.cli.history",
    "asky.cli.prompts",
    "asky.cli.sessions",
    "asky.cli.memory_commands",
    "asky.cli.research_commands",
    "asky.cli.section_commands",
    "asky.cli.utils",
    "asky.cli.chat",
    "asky.cli.main",
)


def _normalized_search_text(text: str) -> str:
    """Normalize CLI output for resilient substring assertions."""
    return re.sub(r"\s+", " ", normalize_cli_output(text).lower()).strip()


def _with_default_model(argv: list[str], model_alias: str) -> list[str]:
    grouped_or_non_query = {
        "history",
        "session",
        "memory",
        "corpus",
        "prompts",
        "persona",
        "--config",
        "--help",
        "--help-all",
    }
    if argv and argv[0] in grouped_or_non_query:
        return list(argv)
    if "-m" in argv or "--model" in argv:
        return list(argv)
    return ["-m", model_alias, *argv]


def _deterministic_session_name(query: str, max_words: int = 2) -> str:
    from asky.core import session_manager as session_manager_mod

    normalized_query = session_manager_mod._strip_terminal_context_wrapper(query)
    if not normalized_query:
        return "session"

    words = re.findall(r"[a-zA-Z]+", normalized_query.lower())
    key_words = [
        word
        for word in words
        if word not in session_manager_mod.STOPWORDS and len(word) > 2
    ]
    selected = key_words[:max_words]
    if not selected:
        return "session"
    return "_".join(selected)


def _reset_stateful_runtime() -> None:
    runtime_mod = sys.modules.get("asky.plugins.runtime")
    if runtime_mod is not None:
        runtime_cache = getattr(runtime_mod, "_RUNTIME_CACHE", None)
        if runtime_cache is not None:
            with contextlib.suppress(Exception):
                runtime_cache.shutdown()
        setattr(runtime_mod, "_RUNTIME_CACHE", None)
        setattr(runtime_mod, "_RUNTIME_INITIALIZED", False)

    for module_name, class_name in (
        ("asky.research.embeddings", "EmbeddingClient"),
        ("asky.research.cache", "ResearchCache"),
        ("asky.research.vector_store", "VectorStore"),
    ):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        cls = getattr(module, class_name, None)
        if cls is not None and hasattr(cls, "_instance"):
            setattr(cls, "_instance", None)


def _reload_runtime_modules() -> dict[str, Any]:
    reloaded: dict[str, Any] = {}
    for module_name in MODULE_RELOAD_ORDER:
        module = importlib.import_module(module_name)
        reloaded[module_name] = importlib.reload(module)
    return reloaded


def run_cli_inprocess(
    argv: list[str], env_overrides: Optional[dict[str, str]] = None
) -> CliRunResult:
    """Run CLI in-process by mocking sys.argv and capturing output."""
    stdout_buf = StringIO()
    stderr_buf = StringIO()

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    home_path = Path(env["HOME"])
    model_alias = env.get("ASKY_CLI_MODEL_ALIAS", "gf").strip() or "gf"
    effective_argv = _with_default_model(argv, model_alias)

    with (
        patch.object(sys, "argv", ["asky", *effective_argv]),
        patch("sys.stdout", stdout_buf),
        patch("sys.stderr", stderr_buf),
        patch("sys.stdin", StringIO("")),
        patch.dict(os.environ, env, clear=False),
        patch("pathlib.Path.home", return_value=home_path),
    ):
        exit_code = 0
        try:
            _reset_stateful_runtime()
            reloaded_modules = _reload_runtime_modules()
            core_session_mod = reloaded_modules["asky.core.session_manager"]
            lock_dir = home_path / ".asky_shell_locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            setattr(core_session_mod, "LOCK_DIR", lock_dir)
            setattr(
                core_session_mod,
                "generate_session_name",
                _deterministic_session_name,
            )
            storage_mod = reloaded_modules["asky.storage"]
            storage_mod.init_db()

            api_session_mod = reloaded_modules["asky.api.session"]
            setattr(
                api_session_mod,
                "generate_session_name",
                _deterministic_session_name,
            )

            cli_main_mod = reloaded_modules["asky.cli.main"]
            cli_main_mod.main()
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)

    return CliRunResult(exit_code, stdout_buf.getvalue(), stderr_buf.getvalue())


def normalize_cli_output(text: str) -> str:
    """Strip ANSI codes and dynamic timing lines for stable assertions."""
    # Remove ANSI escape sequences
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    text = ansi_escape.sub("", text)

    # Remove dynamic timing lines or tokens that break exact matching
    text = re.compile(r"\d+\.\d+s").sub("<TIME>s", text)

    return text.strip()


def run_cli_inprocess_with_retries(
    argv: list[str],
    env_overrides: Optional[dict[str, str]] = None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> CliRunResult:
    """Retry in-process CLI calls when provider responses fail transiently."""
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        result = run_cli_inprocess(argv, env_overrides=env_overrides)
        combined = normalize_cli_output(f"{result.stdout}\n{result.stderr}").lower()
        if not any(pattern in combined for pattern in TRANSIENT_PROVIDER_ERROR_PATTERNS):
            return result
        if attempt < attempts:
            time.sleep(retry_delay_seconds)
    return result


def assert_output_contains_sentences(text: str, sentences: list[str]) -> None:
    """Assert that the normalized text contains the expected sentences."""
    normalized = _normalized_search_text(text)
    for sentence in sentences:
        assert sentence.lower() in normalized, (
            f"Expected sentence '{sentence}' not found in output:\n{normalized}"
        )


def assert_output_contains_fragments(text: str, fragments: list[str]) -> None:
    """Assert that normalized output contains all required fragments."""
    normalized = _normalized_search_text(text)
    for fragment in fragments:
        assert fragment.lower() in normalized, (
            f"Expected fragment '{fragment}' not found in output:\n{normalized}"
        )


def assert_output_excludes_fragments(text: str, fragments: list[str]) -> None:
    """Assert that normalized output excludes forbidden fragments."""
    normalized = _normalized_search_text(text)
    for fragment in fragments:
        assert fragment.lower() not in normalized, (
            f"Forbidden fragment '{fragment}' found in output:\n{normalized}"
        )


def assert_output_contains_any_fragment(text: str, fragments: list[str]) -> None:
    """Assert that normalized output contains at least one fragment from a set."""
    normalized = _normalized_search_text(text)
    for fragment in fragments:
        if fragment.lower() in normalized:
            return
    joined = ", ".join(fragments)
    raise AssertionError(
        f"Expected one of '{joined}' to appear in output:\n{normalized}"
    )


def get_captured_fake_requests(request: pytest.FixtureRequest) -> list[dict]:
    """Get the list of captured request payloads from the fake LLM server."""
    try:
        server = request.getfixturevalue("fake_llm_server")
        return list(server.get("requests", []))
    except Exception:
        return []

def clear_captured_fake_requests(request: pytest.FixtureRequest) -> None:
    """Clear the captured request payloads in the fake LLM server."""
    try:
        server = request.getfixturevalue("fake_llm_server")
        if "requests" in server:
            server["requests"].clear()
    except Exception:
        pass


def configure_plugins_for_test(config_dir: Path, enabled_plugins: list[str]) -> None:
    """Rewrite plugins.toml to explicitly enable the specified plugins."""
    content = ""
    if enabled_plugins:
        content += "[plugins]\n"
        for p in enabled_plugins:
            content += f'"{p}" = true\n'
    (config_dir / "plugins.toml").write_text(content, encoding="utf-8")


def get_last_html_report(home_dir: Path) -> Optional[Path]:
    """Find the most recently modified HTML report file in the test home directory."""
    # Assuming reports are saved either under ASKY_HOME or standard paths
    reports_dir = home_dir / ".config" / "asky" / "reports"
    if not reports_dir.exists():
        # Fallback if saved in .asky or somewhere else
        reports_dir = home_dir / ".asky" / "reports"
        if not reports_dir.exists():
            return None
    reports = list(reports_dir.glob("*.html"))
    if not reports:
        return None
    return sorted(reports, key=lambda p: p.stat().st_mtime)[-1]


def get_session_profile_by_name(session_name: str) -> Optional[dict[str, Any]]:
    """Fetch persisted session research profile from the isolated test DB."""
    db_path = os.environ.get("ASKY_DB_PATH", "").strip()
    if not db_path:
        raise RuntimeError("ASKY_DB_PATH is not set in test environment.")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            (
                "SELECT id, name, research_mode, research_source_mode, "
                "research_local_corpus_paths "
                "FROM sessions WHERE name = ? ORDER BY created_at DESC LIMIT 1"
            ),
            (session_name,),
        ).fetchone()

    if row is None:
        return None

    raw_paths = row["research_local_corpus_paths"] or "[]"
    try:
        parsed_paths = json.loads(raw_paths)
    except json.JSONDecodeError:
        parsed_paths = []
    if not isinstance(parsed_paths, list):
        parsed_paths = []

    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "research_mode": bool(row["research_mode"]),
        "research_source_mode": str(row["research_source_mode"] or ""),
        "research_local_corpus_paths": [str(path) for path in parsed_paths],
    }

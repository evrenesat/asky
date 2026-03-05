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
            config_mod = importlib.import_module("asky.config")
            importlib.reload(config_mod)
            core_session_mod = importlib.import_module("asky.core.session_manager")
            importlib.reload(core_session_mod)
            lock_dir = home_path / ".asky_shell_locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            setattr(core_session_mod, "LOCK_DIR", lock_dir)
            core_mod = importlib.import_module("asky.core")
            importlib.reload(core_mod)
            storage_sqlite_mod = importlib.import_module("asky.storage.sqlite")
            importlib.reload(storage_sqlite_mod)
            storage_mod = importlib.import_module("asky.storage")
            importlib.reload(storage_mod)
            storage_mod.init_db()

            cli_main_mod = importlib.import_module("asky.cli.main")
            importlib.reload(cli_main_mod)
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

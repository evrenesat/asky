import json
import os
import pty
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from pathlib import Path

from tests.integration.cli_recorded.helpers import (
    CliRunResult,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.subprocess_cli]


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def _asky_entrypoint() -> Path:
    return _repo_root() / "asky"


class _SubprocessFakeLLMHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = {
            "id": "chatcmpl-subprocess",
            "object": "chat.completion",
            "created": 1704110400,
            "model": payload.get("model", "fake-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello from the fake LLM server!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
        }
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, fmt, *args):
        return


@pytest.fixture(scope="module")
def fake_llm_server():
    server = HTTPServer(("127.0.0.1", 0), _SubprocessFakeLLMHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield {"url": f"http://{host}:{port}/v1/chat/completions"}
    server.shutdown()
    server.server_close()
    thread.join(timeout=1.0)


def _build_subprocess_home(test_home_root: Path, nodeid: str, llm_url: str) -> Path:
    """Prepare a clean home directory for a subprocess test."""
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    import hashlib
    import shutil

    digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:12]
    home = test_home_root / worker_id / f"subprocess-{digest}"
    if home.exists():
        shutil.rmtree(home)

    config_dir = home / ".config" / "asky"
    config_dir.mkdir(parents=True)

    (config_dir / "general.toml").write_text(
        f'[general]\ndefault_model = "gf"\nsummarization_model = "gf"\ncompact_banner = true\n'
        f'interface_model_plain_query_enabled = false\n'
        f'[limits]\nmax_retries = 1\ninitial_backoff = 0\n'
        f'[research]\nenabled = false\n'
        f'[research.source_shortlist]\nenabled = false\n'
        f'[memory]\nenabled = false\n',
        encoding="utf-8"
    )
    (config_dir / "models.toml").write_text(
        '[models.gf]\nid = "fake/gf"\napi = "fake"\ncontext_size = 32000\n',
        encoding="utf-8"
    )
    (config_dir / "api.toml").write_text(
        f'[api.fake]\nurl = "{llm_url}"\napi_key = "fake-key"\n',
        encoding="utf-8"
    )

    return home


def run_cli_subprocess(
    argv: list[str], home_dir: Path, input_text: str = "", timeout: int = 60
) -> CliRunResult:
    """Run CLI in a subprocess with isolated HOME and config."""
    env = os.environ.copy()
    env.pop("ASKY_CLI_RECORD", None)
    env["HOME"] = str(home_dir)
    env["ASKY_HOME"] = str(home_dir / ".config" / "asky")
    env["ASKY_DB_PATH"] = str(home_dir / "test.db")
    # Speed up imports and startup by skipping real embeddings and heavy features
    env["ASKY_CLI_FAKE_EMBED"] = "1"
    env["NO_COLOR"] = "1"
    
    proc = subprocess.run(
        [sys.executable, str(_asky_entrypoint()), *argv],
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        timeout=timeout,
    )
    return CliRunResult(
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def run_cli_subprocess_pty(
    args: list[str],
    home_dir: Path,
    input_bytes: bytes = b"",
    timeout: float = 10.0,
) -> CliRunResult:
    """Run CLI in a pseudo-terminal to test process-boundary rendering paths."""
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env.pop("ASKY_CLI_RECORD", None)
    env["HOME"] = str(home_dir)
    env["ASKY_HOME"] = str(home_dir / ".config" / "asky")
    env["ASKY_DB_PATH"] = str(home_dir / "test.db")
    # Speed up imports and startup
    env["ASKY_CLI_FAKE_EMBED"] = "1"
    env["NO_COLOR"] = "1"
    # Ensure TERM is set for PTY
    env["TERM"] = "xterm-256color"

    proc = subprocess.Popen(
        [sys.executable, str(_asky_entrypoint()), *args],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        start_new_session=True,
    )
    os.close(slave_fd)

    if input_bytes:
        os.write(master_fd, input_bytes)

    output = b""
    try:
        import select
        import time

        deadline = time.time() + timeout
        while True:
            ready, _, _ = select.select([master_fd], [], [], 0.05)
            if master_fd in ready:
                try:
                    chunk = os.read(master_fd, 4096)
                    if not chunk:
                        break
                    output += chunk
                except OSError:
                    # EIO is common on macOS when slave side closes
                    break
            
            if proc.poll() is not None:
                drain_deadline = time.time() + 0.2
                while time.time() < drain_deadline:
                    ready, _, _ = select.select([master_fd], [], [], 0.01)
                    if master_fd not in ready:
                        break
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    output += chunk
                break
                    
            if time.time() > deadline:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.close(master_fd)
        except OSError:
            pass

    return CliRunResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=output.decode(errors="replace"),
        stderr="",
    )


def test_interactive_model_config_flow(
    test_home_root: Path, request: pytest.FixtureRequest, fake_llm_server
):
    """Interactive subprocess flow for model edit command."""
    home_dir = _build_subprocess_home(
        test_home_root, request.node.nodeid, fake_llm_server["url"]
    )
    result = run_cli_subprocess(
        ["--config", "model", "edit", "gf"],
        home_dir=home_dir,
        input_text="m\n",
    )
    assert result.exit_code == 0, result.stderr
    assert "Model: gf" in result.stdout


def test_interactive_model_add_flow(
    test_home_root: Path, request: pytest.FixtureRequest, fake_llm_server
):
    """Interactive subprocess flow for model add command."""
    home_dir = _build_subprocess_home(
        test_home_root, request.node.nodeid, fake_llm_server["url"]
    )
    # 1. Select provider (1)
    # 2. Enter model ID (gf)
    # 3. Context size (\n)
    # 4. Shortlist (auto)
    # 5. Image support (auto)
    # 6. Parameters (11 times \n to skip)
    # 7. Nickname (new-model)
    # 8. Save (y)
    # 9. Defaults (4 times \n)
    input_text = "1\ngf\n\nauto\nauto\n" + ("\n" * 11) + "new-model\ny\n\n\n\n\n"
    result = run_cli_subprocess(
        ["--config", "model", "add"],
        home_dir=home_dir,
        input_text=input_text,
    )
    assert result.exit_code == 0
    assert "model 'new-model' saved successfully" in result.stdout.lower()


def test_interactive_daemon_config_flow(
    test_home_root: Path, request: pytest.FixtureRequest, fake_llm_server
):
    """Interactive subprocess flow for daemon config edit command."""
    home_dir = _build_subprocess_home(
        test_home_root, request.node.nodeid, fake_llm_server["url"]
    )
    # 1. Enable (n)
    # 2. JID (\n)
    # 3. Password (\n)
    # 4. Allowed (\n)
    # 5. Run at login (\n)
    result = run_cli_subprocess(
        ["--config", "daemon", "edit"],
        home_dir=home_dir,
        input_text="n\n\n\n\n\n",
        timeout=60,
    )
    assert result.exit_code == 0
    assert "daemon configuration" in result.stdout.lower()


@pytest.mark.slow
def test_subprocess_fake_llm_smoke(
    test_home_root: Path, request: pytest.FixtureRequest, fake_llm_server
):
    """Subprocess roundtrip should use local fake LLM endpoint."""
    home_dir = _build_subprocess_home(
        test_home_root, request.node.nodeid, fake_llm_server["url"]
    )

    result = run_cli_subprocess(
        ["-m", "gf", "-off", "all", "--shortlist", "off", "Hello!"],
        home_dir=home_dir,
    )
    assert result.exit_code == 0, result.stderr
    assert "Hello from the fake LLM server!" in result.stdout

    result_pty = run_cli_subprocess_pty(
        ["-m", "gf", "-off", "all", "--shortlist", "off", "Hello again!"],
        home_dir,
    )
    assert "Hello from the fake LLM server!" in result_pty.stdout

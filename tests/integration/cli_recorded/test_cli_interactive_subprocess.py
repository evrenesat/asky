import json
import os
import pty
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

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
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    import hashlib
    import shutil

    digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:12]
    home = test_home_root / worker_id / f"subprocess-{digest}"
    if home.exists():
        shutil.rmtree(home)
    config_dir = home / ".config" / "asky"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "general.toml").write_text(
        '[general]\n'
        'default_model = "gf"\n'
        'summarization_model = "gf"\n'
        "\n"
        "[limits]\n"
        "max_retries = 1\n"
        "initial_backoff = 0\n",
        encoding="utf-8",
    )
    (config_dir / "models.toml").write_text(
        '[models.gf]\n'
        'id = "fake/gf"\n'
        'api = "fake"\n'
        "context_size = 32000\n",
        encoding="utf-8",
    )
    (config_dir / "api.toml").write_text(
        "[api.fake]\n"
        f'url = "{llm_url}"\n'
        'api_key = "fake-key"\n',
        encoding="utf-8",
    )
    return home


def run_cli_subprocess(
    argv: list[str], home_dir: Path, input_text: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run CLI in a subprocess with isolated HOME and config."""
    env = os.environ.copy()
    env.pop("ASKY_CLI_RECORD", None)
    env["HOME"] = str(home_dir)
    env["ASKY_HOME"] = str(home_dir / ".config" / "asky")
    env["ASKY_DB_PATH"] = str(home_dir / "test.db")
    return subprocess.run(
        [sys.executable, str(_asky_entrypoint()), *argv],
        input=input_text,
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )


def run_cli_subprocess_pty(
    argv: list[str], home_dir: Path, input_bytes: bytes = b""
) -> tuple[int, str]:
    """Run CLI in a pseudo-terminal to test process-boundary rendering paths."""
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env.pop("ASKY_CLI_RECORD", None)
    env["HOME"] = str(home_dir)
    env["ASKY_HOME"] = str(home_dir / ".config" / "asky")
    env["ASKY_DB_PATH"] = str(home_dir / "test.db")
    proc = subprocess.Popen(
        [sys.executable, str(_asky_entrypoint()), *argv],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
    )
    os.close(slave_fd)
    if input_bytes:
        os.write(master_fd, input_bytes)

    output = b""
    try:
        import select
        import time

        deadline = time.time() + 20.0
        while time.time() < deadline:
            ready, _, _ = select.select([master_fd], [], [], 0.25)
            if master_fd in ready:
                chunk = os.read(master_fd, 1024)
                if not chunk:
                    break
                output += chunk
            if proc.poll() is not None and master_fd not in ready:
                break
    except OSError:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=5)
        os.close(master_fd)
    return proc.returncode, output.decode(errors="replace")


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
    assert result.returncode == 0, result.stderr
    assert "Model: gf" in result.stdout


def test_subprocess_fake_llm_smoke(
    test_home_root: Path, request: pytest.FixtureRequest, fake_llm_server
):
    """Subprocess roundtrip should use local fake LLM endpoint."""
    home_dir = _build_subprocess_home(
        test_home_root, request.node.nodeid, fake_llm_server["url"]
    )

    result = run_cli_subprocess(["-m", "gf", "Hello!"], home_dir=home_dir)
    assert result.returncode == 0, result.stderr
    assert "Hello from the fake LLM server!" in result.stdout

    _, pty_output = run_cli_subprocess_pty(["-m", "gf", "Hello again!"], home_dir)
    assert "Hello from the fake LLM server!" in pty_output

import os
import shutil
import socket
from hashlib import sha1
from pathlib import Path
from unittest.mock import patch

import pytest

TEST_HOME_ROOT = Path(__file__).resolve().parent / ".test_home"


def _test_home_for_node(nodeid: str, worker_id: str) -> Path:
    digest = sha1(nodeid.encode("utf-8")).hexdigest()[:12]
    return TEST_HOME_ROOT / worker_id / digest


@pytest.fixture(scope="session")
def test_home_root() -> Path:
    TEST_HOME_ROOT.mkdir(parents=True, exist_ok=True)
    return TEST_HOME_ROOT

@pytest.fixture(autouse=True)
def mock_settings_env_vars(request: pytest.FixtureRequest, test_home_root: Path):
    """Mock HOME/ASKY_HOME/DB path to keep tests isolated from user state."""
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    if "tests/integration/cli_recorded/" in node_path:
        yield
        return

    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    fake_home = _test_home_for_node(request.node.nodeid, worker_id)
    if fake_home.exists():
        shutil.rmtree(fake_home)
    fake_home.mkdir(parents=True, exist_ok=True)
    asky_home = fake_home / ".config" / "asky"
    asky_home.mkdir(parents=True, exist_ok=True)

    with patch("pathlib.Path.home", return_value=fake_home):
        with patch.dict(
            os.environ,
            {
                "HOME": str(fake_home),
                "ASKY_HOME": str(asky_home),
                "ASKY_DB_PATH": str(fake_home / "test.db"),
            },
            clear=False,
        ):
            yield


@pytest.fixture(autouse=True)
def block_live_network_for_recorded_lane(request: pytest.FixtureRequest, monkeypatch):
    """Block live outbound network only for recorded replay tests."""
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    if "tests/integration/cli_recorded/" not in node_path:
        return
    if "test_cli_interactive_subprocess.py" in node_path:
        return
    if os.environ.get("ASKY_CLI_RECORD"):
        return

    def guard(*args, **kwargs):
        raise RuntimeError(
            "Live network is blocked for recorded_cli replay tests. "
            "Set ASKY_CLI_RECORD=1 only when refreshing cassettes."
        )

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)

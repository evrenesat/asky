import os
import shutil
import socket
from hashlib import sha1
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

pytest_plugins = ("asky.testing.pytest_feature_domains",)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_HOME_ROOT = PROJECT_ROOT / "temp" / "test_home"
HELPER_POLICY_TEST_PATHS = (
    "tests/asky/api/test_interface_query_policy.py",
    "tests/asky/api/test_plain_query_memory_validation.py",
    "tests/asky/api/test_plain_query_helper_gates.py",
    "tests/asky/api/test_preload_policy.py",
)


def _test_home_for_node(nodeid: str, worker_root: Path) -> Path:
    digest = sha1(nodeid.encode("utf-8")).hexdigest()[:12]
    return worker_root / digest


def _worker_test_home_root() -> Path:
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    return TEST_HOME_ROOT / worker_id / str(os.getpid())


def _prune_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


@pytest.fixture(scope="session")
def test_home_root() -> Iterator[Path]:
    worker_root = _worker_test_home_root()
    if worker_root.exists():
        shutil.rmtree(worker_root)
    worker_root.mkdir(parents=True, exist_ok=True)
    yield worker_root
    if worker_root.exists():
        shutil.rmtree(worker_root)
    _prune_empty_parents(worker_root.parent, PROJECT_ROOT)


@pytest.fixture(autouse=True)
def mock_settings_env_vars(request: pytest.FixtureRequest, test_home_root: Path):
    """Mock HOME/ASKY_HOME/DB path to keep tests isolated from user state."""
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    if "tests/integration/cli_recorded/" in node_path:
        yield
        return
    if "tests/integration/cli_live/" in node_path:
        yield
        return

    fake_home = _test_home_for_node(request.node.nodeid, test_home_root)
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


@pytest.fixture(autouse=True)
def disable_plain_query_helper_for_unit_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
):
    """Keep unit tests off the live plain-query helper unless they target it."""
    node_path = str(getattr(request.node, "fspath", "")).replace("\\", "/")
    if any(path in node_path for path in HELPER_POLICY_TEST_PATHS):
        return
    if "tests/integration/cli_recorded/" in node_path:
        return
    if "tests/integration/cli_live/" in node_path:
        return

    monkeypatch.setattr("asky.config.INTERFACE_MODEL", "")
    monkeypatch.setattr("asky.config.INTERFACE_MODEL_PLAIN_QUERY_ENABLED", False)

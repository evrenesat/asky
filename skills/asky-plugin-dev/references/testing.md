# Plugin Testing Guide

## Running the Full Suite

```bash
uv run pytest -x -q          # stop on first failure, quiet output
uv run pytest -x -q tests/plugins/   # only plugin tests
```

No test should take more than 1 second. New tests must not increase total suite
time disproportionately (adding 10 tests to a 400-test / 5s suite cannot add more
than ~0.1s per test).

---

## 1. Activation Test (all plugins should have this)

Verifies the plugin can be loaded and activated without errors.

```python
import sys
import types
import pytest
from asky.plugins.manager import PluginManager


def test_my_plugin_activates(tmp_path):
    (tmp_path / "plugins.toml").write_text("""
[plugin.my_plugin]
enabled = true
module  = "asky.plugins.my_plugin.plugin"
class   = "MyPlugin"
""")
    mgr = PluginManager(config_dir=tmp_path)
    mgr.load_roster()
    mgr.discover_and_import()
    mgr.activate_all()
    statuses = mgr.list_status()
    assert any(s.name == "my_plugin" and s.state == "active" for s in statuses)
```

---

## 2. Hook Behaviour Test (test what the hook actually does)

Use a real `HookRegistry` + `PluginManager` and inspect mutations.

```python
from asky.plugins.hooks import HookRegistry
from asky.plugins.hook_types import TOOL_REGISTRY_BUILD, ToolRegistryBuildContext


def test_tool_registered(tmp_path):
    (tmp_path / "plugins.toml").write_text("""
[plugin.my_plugin]
enabled = true
module  = "asky.plugins.my_plugin.plugin"
class   = "MyPlugin"
""")
    mgr = PluginManager(config_dir=tmp_path)
    mgr.load_roster()
    mgr.discover_and_import()
    mgr.activate_all()

    # build a fake registry and fire the hook
    registered = {}

    class FakeRegistry:
        def register(self, name, schema, executor):
            registered[name] = (schema, executor)

    payload = ToolRegistryBuildContext(
        mode="daemon",
        registry=FakeRegistry(),
        disabled_tools=set(),
    )
    mgr.hooks.invoke(TOOL_REGISTRY_BUILD, payload)
    assert "my_tool" in registered
```

---

## 3. Injecting a Fake Module (for fast unit tests without real imports)

When testing plugin infrastructure without the plugin's actual heavy dependencies.

```python
def _install_fake_plugin(monkeypatch, module_name: str, class_name: str):
    from asky.plugins.base import AskyPlugin
    module = types.ModuleType(module_name)

    class _FakePlugin(AskyPlugin):
        activated = False

        def activate(self, context):
            _FakePlugin.activated = True

    setattr(module, class_name, _FakePlugin)
    monkeypatch.setitem(sys.modules, module_name, module)
    return _FakePlugin


def test_fake_plugin(tmp_path, monkeypatch):
    cls = _install_fake_plugin(monkeypatch, "fake_pkg.plugin", "FakePlugin")
    (tmp_path / "plugins.toml").write_text("""
[plugin.fake]
enabled = true
module  = "fake_pkg.plugin"
class   = "FakePlugin"
""")
    mgr = PluginManager(config_dir=tmp_path)
    mgr.load_roster()
    mgr.discover_and_import()
    mgr.activate_all()
    assert cls.activated
```

---

## 4. Mocking the Plugin Runtime (for tray / daemon tests)

```python
from unittest.mock import MagicMock
from asky.plugins.hooks import HookRegistry


def test_tray_hook(monkeypatch):
    fake_runtime = MagicMock()
    fake_hooks = HookRegistry()
    fake_runtime.hooks = fake_hooks

    monkeypatch.setattr(
        "asky.plugins.runtime.get_or_create_plugin_runtime",
        lambda **kw: fake_runtime,
    )
    # ... continue test using fake_hooks.invoke(...)
```

---

## 5. Testing Subprocess-Based Executors (external tools)

Mock `subprocess.run` to avoid real network / process calls in unit tests.

```python
from unittest.mock import patch, MagicMock
from asky.plugins.yt_dlp_plugin.downloader import download_video
from pathlib import Path


def test_download_video_success(tmp_path):
    fake_output = tmp_path / "My Video.mp4"
    fake_output.write_bytes(b"fake video data")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = str(fake_output) + "\n"

    with patch("subprocess.run", return_value=mock_result):
        result = download_video("https://youtube.com/watch?v=abc", tmp_path)
    assert result == fake_output


def test_download_video_failure(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "ERROR: Video unavailable"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Video unavailable"):
            download_video("https://youtube.com/watch?v=bad", tmp_path)
```

---

## 6. POST_TURN_RENDER Integration Test

```python
from asky.plugins.hook_types import POST_TURN_RENDER, PostTurnRenderContext
from unittest.mock import MagicMock


def test_post_turn_render(tmp_path):
    (tmp_path / "plugins.toml").write_text("""
[plugin.my_plugin]
enabled = true
module  = "asky.plugins.my_plugin.plugin"
class   = "MyPlugin"
""")
    mgr = PluginManager(config_dir=tmp_path)
    mgr.load_roster()
    mgr.discover_and_import()
    mgr.activate_all()

    cli_args = MagicMock()
    cli_args.my_flag = True

    ctx = PostTurnRenderContext(
        final_answer="The answer is 42.",
        request=MagicMock(),
        result=MagicMock(),
        cli_args=cli_args,
        answer_title="Test",
    )
    mgr.hooks.invoke(POST_TURN_RENDER, ctx)
    # assert side-effects here (file written, mock called, etc.)
```

---

## Common Pitfalls

- **Never use `import` at module level for heavy deps** (ffmpeg bindings, ML models).
  Import them inside the executor function or inside `activate()` to keep
  `get_cli_contributions()` fast (it runs before activation).

- **Don't share mutable state across tests.** Use `tmp_path` for every test that
  needs a config dir.

- **Don't test private internals of `PluginManager`.** Test observable outcomes:
  `list_status()`, hook side-effects, return values from executors.

from __future__ import annotations

import sys
import types
from pathlib import Path

from asky.plugins.base import AskyPlugin
from asky.plugins.manager import (
    ACTIVE_PLUGIN_STATE,
    FAILED_ACTIVATION_STATE,
    FAILED_DEPENDENCY_STATE,
    FAILED_MANIFEST_STATE,
    INACTIVE_PLUGIN_STATE,
    PluginManager,
)


def _write_plugins_toml(config_dir: Path, content: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "plugins.toml").write_text(content, encoding="utf-8")


def _install_plugin_module(monkeypatch, module_name: str, class_name: str, events):
    module = types.ModuleType(module_name)

    class _Plugin(AskyPlugin):
        def activate(self, context):
            events.append(("activate", context.plugin_name))

        def deactivate(self):
            events.append(("deactivate", module_name))

    setattr(module, class_name, _Plugin)
    monkeypatch.setitem(sys.modules, module_name, module)


def test_roster_template_created_when_missing(tmp_path: Path):
    manager = PluginManager(config_dir=tmp_path / "config")
    manifests = manager.load_roster()

    assert (tmp_path / "config" / "plugins.toml").exists()
    assert sorted(manifest.name for manifest in manifests) == [
        "gui_server",
        "manual_persona_creator",
        "persona_manager",
    ]


def test_invalid_manifest_entry_sets_failed_status(tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_plugins_toml(
        config_dir,
        """
[plugin.bad]
enabled = true
module = "bad.module"

[plugin.good]
enabled = false
module = "good.module"
class = "Good"
""",
    )

    manager = PluginManager(config_dir=config_dir)
    manager.load_roster()
    statuses = {status.name: status for status in manager.list_status()}

    assert statuses["bad"].state == FAILED_MANIFEST_STATE
    assert statuses["good"].state == "disabled"


def test_dependency_cycle_marks_plugins_failed(tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_plugins_toml(
        config_dir,
        """
[plugin.a]
enabled = true
module = "example.a"
class = "A"
dependencies = ["b"]

[plugin.b]
enabled = true
module = "example.b"
class = "B"
dependencies = ["a"]
""",
    )

    manager = PluginManager(config_dir=config_dir)
    manager.load_roster()
    manager.discover_and_import()
    statuses = {status.name: status for status in manager.list_status()}

    assert statuses["a"].state == FAILED_DEPENDENCY_STATE
    assert statuses["b"].state == FAILED_DEPENDENCY_STATE


def test_dependency_on_disabled_plugin_fails(tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_plugins_toml(
        config_dir,
        """
[plugin.base]
enabled = false
module = "example.base"
class = "Base"

[plugin.dep]
enabled = true
module = "example.dep"
class = "Dep"
dependencies = ["base"]
""",
    )

    manager = PluginManager(config_dir=config_dir)
    manager.load_roster()
    manager.discover_and_import()
    statuses = {status.name: status for status in manager.list_status()}

    assert statuses["dep"].state == FAILED_DEPENDENCY_STATE


def test_activation_and_deactivation_are_deterministic(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_plugins_toml(
        config_dir,
        """
[plugin.alpha]
enabled = true
module = "plugins.alpha"
class = "Alpha"

[plugin.bravo]
enabled = true
module = "plugins.bravo"
class = "Bravo"
dependencies = ["alpha"]
""",
    )

    events = []
    _install_plugin_module(monkeypatch, "plugins.alpha", "Alpha", events)
    _install_plugin_module(monkeypatch, "plugins.bravo", "Bravo", events)

    manager = PluginManager(config_dir=config_dir)
    manager.load_roster()
    manager.discover_and_import()
    manager.activate_all()

    assert events[:2] == [("activate", "alpha"), ("activate", "bravo")]

    manager.deactivate_all()

    assert events[2:] == [
        ("deactivate", "plugins.bravo"),
        ("deactivate", "plugins.alpha"),
    ]

    statuses = {status.name: status for status in manager.list_status()}
    assert statuses["alpha"].state == INACTIVE_PLUGIN_STATE
    assert statuses["bravo"].state == INACTIVE_PLUGIN_STATE


def test_plugin_config_decode_error_marks_activation_failure(
    monkeypatch,
    tmp_path: Path,
):
    config_dir = tmp_path / "config"
    _write_plugins_toml(
        config_dir,
        """
[plugin.alpha]
enabled = true
module = "plugins.alpha"
class = "Alpha"
config_file = "plugins/alpha.toml"
""",
    )
    plugin_config_path = config_dir / "plugins" / "alpha.toml"
    plugin_config_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_config_path.write_text("[broken", encoding="utf-8")

    events = []
    _install_plugin_module(monkeypatch, "plugins.alpha", "Alpha", events)

    manager = PluginManager(config_dir=config_dir)
    manager.load_roster()
    manager.discover_and_import()
    manager.activate_all()

    statuses = {status.name: status for status in manager.list_status()}
    assert statuses["alpha"].state == FAILED_ACTIVATION_STATE
    assert events == []

from __future__ import annotations

import tomlkit


def test_dependency_issue_recorded_for_disabled_dep(tmp_path):
    """PluginManager records DependencyIssue when a required dep is disabled."""
    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "base_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            },
            "dependent_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
                "dependencies": ["missing_dep"],
            },
            "missing_dep": {
                "enabled": False,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            },
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    issues = manager.get_dependency_issues()
    assert len(issues) == 1
    assert issues[0].plugin_name == "dependent_plugin"
    assert issues[0].dep_name == "missing_dep"
    assert issues[0].reason == "disabled"


def test_dependency_issue_recorded_for_unknown_dep(tmp_path):
    """PluginManager records DependencyIssue when a required dep is not in roster."""
    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "dependent_plugin": {
                "enabled": True,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
                "dependencies": ["nonexistent_plugin"],
            },
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    issues = manager.get_dependency_issues()
    assert len(issues) == 1
    assert issues[0].plugin_name == "dependent_plugin"
    assert issues[0].dep_name == "nonexistent_plugin"
    assert issues[0].reason == "not_found"


def test_enable_plugin_persists_to_toml(tmp_path):
    """enable_plugin() updates the in-memory manifest and writes plugins.toml."""
    from asky.plugins.manager import PluginManager

    roster = {
        "plugin": {
            "my_plugin": {
                "enabled": False,
                "module": "asky.plugins.base",
                "class": "AskyPlugin",
            }
        }
    }
    roster_path = tmp_path / "plugins.toml"
    roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

    manager = PluginManager(config_dir=tmp_path)
    manager.load_roster()

    result = manager.enable_plugin("my_plugin")
    assert result is True
    assert manager._manifests["my_plugin"].enabled is True

    written = tomlkit.loads(roster_path.read_text(encoding="utf-8"))
    assert written["plugin"]["my_plugin"]["enabled"] is True


def test_handle_dependency_issues_emits_warnings_for_non_interactive(
    tmp_path, monkeypatch
):
    """Non-interactive context: dependency issues become warning strings."""
    from asky.daemon.launch_context import LaunchContext, set_launch_context
    from asky.plugins.manager import PluginManager
    from asky.plugins.runtime import _handle_dependency_issues

    set_launch_context(LaunchContext.DAEMON_FOREGROUND)
    try:
        roster = {
            "plugin": {
                "dep_plugin": {
                    "enabled": False,
                    "module": "asky.plugins.base",
                    "class": "AskyPlugin",
                },
                "consumer_plugin": {
                    "enabled": True,
                    "module": "asky.plugins.base",
                    "class": "AskyPlugin",
                    "dependencies": ["dep_plugin"],
                },
            }
        }
        roster_path = tmp_path / "plugins.toml"
        roster_path.write_text(tomlkit.dumps(roster), encoding="utf-8")

        manager = PluginManager(config_dir=tmp_path)
        manager.load_roster()

        warnings = _handle_dependency_issues(manager)
        assert len(warnings) == 1
        assert "consumer_plugin" in warnings[0]
        assert "dep_plugin" in warnings[0]
    finally:
        set_launch_context(LaunchContext.INTERACTIVE_CLI)
        _ = monkeypatch

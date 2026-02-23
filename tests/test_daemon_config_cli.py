from asky.cli import daemon_config


def test_get_daemon_settings_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("asky.cli.daemon_config._get_config_dir", lambda: tmp_path)
    settings = daemon_config.get_daemon_settings()
    assert settings.enabled is False
    assert settings.jid == ""
    assert settings.allowed_jids == []


def test_update_daemon_settings_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("asky.cli.daemon_config._get_config_dir", lambda: tmp_path)
    updated = daemon_config.update_daemon_settings(
        enabled=True,
        jid="bot@example.com",
        password="secret",
        allowed_jids=["a@example.com"],
        voice_enabled=True,
    )
    assert updated.enabled is True
    assert updated.jid == "bot@example.com"
    assert updated.password == "secret"
    assert updated.allowed_jids == ["a@example.com"]
    assert updated.voice_enabled is True


def test_minimum_requirements_accept_password_env(tmp_path, monkeypatch):
    monkeypatch.setattr("asky.cli.daemon_config._get_config_dir", lambda: tmp_path)
    daemon_config.update_daemon_settings(
        enabled=True,
        jid="bot@example.com",
        password="",
        allowed_jids=["a@example.com"],
        voice_enabled=False,
    )
    path = tmp_path / "xmpp.toml"
    content = path.read_text()
    content += 'password_env = "ASKY_XMPP_PASSWORD"\n'
    path.write_text(content)
    monkeypatch.setenv("ASKY_XMPP_PASSWORD", "from-env")
    settings = daemon_config.get_daemon_settings()
    assert settings.has_minimum_requirements() is True


def test_edit_daemon_command_interactive_flow(tmp_path, monkeypatch):
    monkeypatch.setattr("asky.cli.daemon_config._get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "asky.cli.daemon_config.startup.get_status",
        lambda: daemon_config.startup.StartupStatus(
            supported=True,
            enabled=False,
            active=False,
            platform_name="linux",
            details="",
        ),
    )
    startup_enabled = {"value": False}

    def _enable_startup():
        startup_enabled["value"] = True
        return daemon_config.startup.StartupStatus(
            supported=True,
            enabled=True,
            active=True,
            platform_name="linux",
            details="",
        )

    monkeypatch.setattr("asky.cli.daemon_config.startup.enable_startup", _enable_startup)
    monkeypatch.setattr(
        "asky.cli.daemon_config.startup.disable_startup",
        lambda: daemon_config.startup.StartupStatus(
            supported=True,
            enabled=False,
            active=False,
            platform_name="linux",
            details="",
        ),
    )
    prompt_values = iter(
        [
            "bot@example.com",
            "secret",
            "alice@example.com,bob@example.com",
        ]
    )
    confirm_values = iter([True, True, True])
    monkeypatch.setattr(
        "asky.cli.daemon_config.Prompt.ask",
        lambda *args, **kwargs: next(prompt_values),
    )
    monkeypatch.setattr(
        "asky.cli.daemon_config.Confirm.ask",
        lambda *args, **kwargs: next(confirm_values),
    )

    daemon_config.edit_daemon_command()
    result = daemon_config.get_daemon_settings()
    assert result.enabled is True
    assert result.jid == "bot@example.com"
    assert result.voice_enabled is True
    assert result.allowed_jids == ["alice@example.com", "bob@example.com"]
    assert startup_enabled["value"] is True

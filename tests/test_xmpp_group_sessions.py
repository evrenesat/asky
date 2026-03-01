"""Group-session profile persistence tests for daemon mode."""

from unittest.mock import patch

from asky.config import DEFAULT_MODEL, MODELS, SUMMARIZATION_MODEL
from asky.plugins.xmpp_daemon.session_profile_manager import SessionProfileManager
from asky.storage import _repo, init_db


def _patched_db(tmp_path):
    db_path = tmp_path / "xmpp_group_sessions.db"
    return (
        patch("asky.storage.sqlite.DB_PATH", db_path),
        patch("asky.config.DB_PATH", db_path),
        db_path,
    )


def test_room_binding_persists_across_manager_instances(tmp_path):
    patch_sqlite, patch_config, db_path = _patched_db(tmp_path)
    with patch_sqlite, patch_config:
        _repo.db_path = db_path
        init_db()
        manager_a = SessionProfileManager()
        manager_b = SessionProfileManager()

        session_id = manager_a.get_or_create_room_session_id(
            "Room@conference.example.com"
        )
        assert session_id > 0
        rebound_id = manager_b.get_or_create_room_session_id(
            "room@conference.example.com"
        )
        assert rebound_id == session_id
        assert manager_b.list_bound_room_jids() == ["room@conference.example.com"]


def test_general_override_last_write_wins_without_merge(tmp_path):
    patch_sqlite, patch_config, db_path = _patched_db(tmp_path)
    with patch_sqlite, patch_config:
        _repo.db_path = db_path
        init_db()
        manager = SessionProfileManager()
        session_id = manager.get_or_create_direct_session_id("u@example.com/resource")
        aliases = list(MODELS.keys())
        main_alias = aliases[0]
        sum_alias = aliases[1] if len(aliases) > 1 else aliases[0]

        first = manager.apply_override_file(
            session_id=session_id,
            filename="general.toml",
            content=(
                "[general]\n"
                f'default_model = "{main_alias}"\n'
                f'summarization_model = "{sum_alias}"\n'
            ),
        )
        assert first.error is None
        profile = manager.get_effective_profile(session_id=session_id)
        assert profile.default_model == main_alias
        assert profile.summarization_model == sum_alias

        second = manager.apply_override_file(
            session_id=session_id,
            filename="general.toml",
            content=f'[general]\ndefault_model = "{main_alias}"\n',
        )
        assert second.error is None
        updated = manager.get_effective_profile(session_id=session_id)
        assert updated.default_model == main_alias
        assert updated.summarization_model == SUMMARIZATION_MODEL


def test_user_prompts_override_last_write_wins(tmp_path):
    patch_sqlite, patch_config, db_path = _patched_db(tmp_path)
    with patch_sqlite, patch_config:
        _repo.db_path = db_path
        init_db()
        manager = SessionProfileManager()
        session_id = manager.get_or_create_direct_session_id("u@example.com/resource")

        manager.apply_override_file(
            session_id=session_id,
            filename="user.toml",
            content='[user_prompts]\na = "A"\nb = "B"\n',
        )
        first_profile = manager.get_effective_profile(session_id=session_id)
        assert first_profile.user_prompts == {"a": "A", "b": "B"}

        manager.apply_override_file(
            session_id=session_id,
            filename="user.toml",
            content='[user_prompts]\nc = "C"\n',
        )
        second_profile = manager.get_effective_profile(session_id=session_id)
        assert second_profile.user_prompts == {"c": "C"}


def test_override_rejects_unknown_file_and_ignores_unsupported_keys(tmp_path):
    patch_sqlite, patch_config, db_path = _patched_db(tmp_path)
    with patch_sqlite, patch_config:
        _repo.db_path = db_path
        init_db()
        manager = SessionProfileManager()
        session_id = manager.get_or_create_direct_session_id("u@example.com/resource")

        rejected = manager.apply_override_file(
            session_id=session_id,
            filename="prompts.toml",
            content='[prompts]\nsystem_prefix = "x"\n',
        )
        assert rejected.saved is False
        assert rejected.error is not None

        accepted = manager.apply_override_file(
            session_id=session_id,
            filename="general.toml",
            content='[general]\nunsupported = "x"\ndefault_model = "missing-alias"\n',
        )
        assert accepted.saved is True
        assert accepted.applied_keys == ()
        assert "general.unsupported" in accepted.ignored_keys
        profile = manager.get_effective_profile(session_id=session_id)
        assert profile.default_model == DEFAULT_MODEL

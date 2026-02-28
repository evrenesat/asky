import logging
import re
from pathlib import Path

import asky.logger as logger_module
from asky.logger import generate_timestamped_log_path, setup_logging


def _restore_root_logger(
    original_handlers: list[logging.Handler], original_level: int
) -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        if handler not in original_handlers:
            handler.close()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def test_generate_timestamped_log_path_migrates_legacy_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    generated_path = generate_timestamped_log_path("~/.config/asky/asky.log")

    expected_parent = tmp_path / ".config" / "asky" / "logs"
    assert generated_path.parent == expected_parent
    assert re.match(
        r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_asky\.log", generated_path.name
    )


def test_setup_logging_writes_to_migrated_legacy_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        setup_logging("INFO", "~/.config/asky/asky.log")
        test_message = "non-verbose logging path migration works"
        logging.getLogger("asky.tests.logger").info(test_message)

        for handler in logging.getLogger().handlers:
            handler.flush()

        expected_log_path = tmp_path / ".config" / "asky" / "logs" / "asky.log"
        assert expected_log_path.exists()
        assert test_message in expected_log_path.read_text(encoding="utf-8")
    finally:
        _restore_root_logger(original_handlers, original_level)


def test_setup_logging_archives_existing_file_and_keeps_canonical_name(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(logger_module, "_ROLLED_LOG_PATHS", set())
    expected_log_path = tmp_path / ".config" / "asky" / "logs" / "asky.log"
    expected_log_path.parent.mkdir(parents=True, exist_ok=True)
    expected_log_path.write_text("old asky log\n", encoding="utf-8")

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        setup_logging("INFO", "~/.config/asky/asky.log")
        logging.getLogger("asky.tests.logger").info("new asky log line")
        for handler in logging.getLogger().handlers:
            handler.flush()

        archived = list(expected_log_path.parent.glob("*_asky.log"))
        assert len(archived) == 1
        assert archived[0].read_text(encoding="utf-8") == "old asky log\n"
        assert "new asky log line" in expected_log_path.read_text(encoding="utf-8")

        setup_logging("INFO", "~/.config/asky/asky.log")
        logging.getLogger("asky.tests.logger").info("second run same process")
        for handler in logging.getLogger().handlers:
            handler.flush()

        archived_after = list(expected_log_path.parent.glob("*_asky.log"))
        assert len(archived_after) == 1
    finally:
        _restore_root_logger(original_handlers, original_level)


def test_setup_xmpp_logging_writes_plugin_logs_without_duplicate_handlers(
    monkeypatch, tmp_path
):
    log_path = tmp_path / "xmpp.log"
    monkeypatch.setattr(logger_module, "XMPP_LOG_FILE", str(log_path))

    daemon_logger = logging.getLogger("asky.daemon")
    plugin_logger = logging.getLogger("asky.plugins.xmpp_daemon.xmpp_client")
    slixmpp_logger = logging.getLogger("slixmpp")
    tracked_loggers = (daemon_logger, plugin_logger, slixmpp_logger)
    original_state = {
        logger: (list(logger.handlers), logger.level) for logger in tracked_loggers
    }

    try:
        logger_module.setup_xmpp_logging("DEBUG")
        logger_module.setup_xmpp_logging("DEBUG")

        plugin_logger.debug("xmpp plugin log write test")
        slixmpp_logger.debug("slixmpp log write test")

        for logger in tracked_loggers:
            for handler in logger.handlers:
                handler.flush()

        text = log_path.read_text(encoding="utf-8")
        assert "xmpp plugin log write test" in text
        assert "slixmpp log write test" in text

        daemon_paths = [
            getattr(handler, "baseFilename", "")
            for handler in daemon_logger.handlers
            if getattr(handler, "baseFilename", "")
        ]
        assert daemon_paths.count(str(log_path)) == 1
    finally:
        for logger, (handlers, level) in original_state.items():
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler not in handlers:
                    handler.close()
            for handler in handlers:
                logger.addHandler(handler)
            logger.setLevel(level)


def test_setup_xmpp_logging_archives_existing_file_and_uses_xmpp_log(
    monkeypatch, tmp_path
):
    log_path = tmp_path / "xmpp.log"
    log_path.write_text("old xmpp log\n", encoding="utf-8")
    monkeypatch.setattr(logger_module, "XMPP_LOG_FILE", str(log_path))
    monkeypatch.setattr(logger_module, "_ROLLED_LOG_PATHS", set())

    daemon_logger = logging.getLogger("asky.daemon")
    plugin_logger = logging.getLogger("asky.plugins.xmpp_daemon.xmpp_client")
    slixmpp_logger = logging.getLogger("slixmpp")
    tracked_loggers = (daemon_logger, plugin_logger, slixmpp_logger)
    original_state = {
        logger: (list(logger.handlers), logger.level) for logger in tracked_loggers
    }

    try:
        logger_module.setup_xmpp_logging("DEBUG")
        plugin_logger.debug("new xmpp log line")
        for logger in tracked_loggers:
            for handler in logger.handlers:
                handler.flush()

        archived = list(log_path.parent.glob("*_xmpp.log"))
        assert len(archived) == 1
        assert archived[0].read_text(encoding="utf-8") == "old xmpp log\n"
        assert "new xmpp log line" in log_path.read_text(encoding="utf-8")
    finally:
        for logger, (handlers, level) in original_state.items():
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler not in handlers:
                    handler.close()
            for handler in handlers:
                logger.addHandler(handler)
            logger.setLevel(level)


def test_setup_xmpp_logging_disables_propagation(monkeypatch, tmp_path):
    log_path = tmp_path / "xmpp.log"
    monkeypatch.setattr(logger_module, "XMPP_LOG_FILE", str(log_path))

    daemon_logger = logging.getLogger("asky.daemon")
    plugin_logger = logging.getLogger("asky.plugins.xmpp_daemon")
    slixmpp_logger = logging.getLogger("slixmpp")
    tracked_loggers = (daemon_logger, plugin_logger, slixmpp_logger)

    original_state = {
        logger: (list(logger.handlers), logger.level, logger.propagate)
        for logger in tracked_loggers
    }

    try:
        # Before setup, propagation should be True (default)
        for logger in tracked_loggers:
            logger.propagate = True

        logger_module.setup_xmpp_logging("DEBUG")

        for logger in tracked_loggers:
            assert logger.propagate is False, (
                f"Logger {logger.name} should have propagate=False"
            )
    finally:
        for logger, (handlers, level, propagate) in original_state.items():
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                if handler not in handlers:
                    handler.close()
            for handler in handlers:
                logger.addHandler(handler)
            logger.setLevel(level)
            logger.propagate = propagate

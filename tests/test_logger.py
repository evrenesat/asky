import logging
import re
from pathlib import Path

from asky.logger import generate_timestamped_log_path, setup_logging


def _restore_root_logger(original_handlers: list[logging.Handler], original_level: int) -> None:
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
    assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_asky\.log", generated_path.name)


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

"""Logging configuration for asky."""

import logging
import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

DEFAULT_LOG_FILE = "~/.config/asky/logs/asky.log"
LEGACY_DEFAULT_LOG_FILE = "~/.config/asky/asky.log"
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024  # 5 MiB per rotated file.
LOG_BACKUP_COUNT = 3


def resolve_log_file_path(log_file: Union[str, Path]) -> Path:
    """Resolve and migrate legacy log-file paths to the current logs directory."""
    resolved = Path(log_file).expanduser()
    legacy_default = Path(LEGACY_DEFAULT_LOG_FILE).expanduser()
    if resolved == legacy_default:
        return Path(DEFAULT_LOG_FILE).expanduser()
    return resolved


def generate_timestamped_log_path(base_path: str) -> Path:
    """Generate a log file path with a timestamp prefix."""
    path = resolve_log_file_path(base_path)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return path.parent / f"{timestamp}_{path.name}"


def setup_logging(
    level_name: str = "INFO", log_file: Optional[Union[str, Path]] = None
) -> None:
    """Configure logging to write to a file."""
    level = getattr(logging, level_name.upper(), logging.INFO)

    if not log_file:
        return
    log_path = resolve_log_file_path(log_file)

    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create file handler
    handler = RotatingFileHandler(
        log_path,
        mode="a",  # Append to allow multiple handlers or re-opens
        maxBytes=MAX_LOG_FILE_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    # Remove existing handlers to avoid duplicates if re-initialized
    for existing_handler in list(logger.handlers):
        logger.removeHandler(existing_handler)
        existing_handler.close()

    logger.addHandler(handler)

    # Suppress noisy libraries
    noisy_libraries = [
        "markdown_it",
        "urllib3",
        "requests",
        "httpcore",
        "httpx",
        "pygments",
        "trafilatura",
    ]
    for lib in noisy_libraries:
        logging.getLogger(lib).setLevel(logging.WARNING)


XMPP_LOG_FILE = "~/.config/asky/logs/xmpp.log"


def setup_xmpp_logging(level_name: str = "DEBUG") -> None:
    """Attach a dedicated log handler for asky.daemon.* to a separate xmpp.log file.

    This does not affect the root logger - other asky logs continue going to the
    main log file. Only the asky.daemon namespace is captured here.
    """
    level = getattr(logging, level_name.upper(), logging.DEBUG)
    log_path = Path(XMPP_LOG_FILE).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=MAX_LOG_FILE_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    handler.setLevel(level)

    daemon_logger = logging.getLogger("asky.daemon")
    daemon_logger.addHandler(handler)

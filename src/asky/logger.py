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
_ROLLED_LOG_PATHS: set[Path] = set()


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


def _archive_existing_log_file(log_path: Path) -> None:
    """Archive an existing log file to a timestamp-prefixed name once per process."""
    resolved_path = log_path.resolve()
    if resolved_path in _ROLLED_LOG_PATHS:
        return
    if not log_path.exists():
        _ROLLED_LOG_PATHS.add(resolved_path)
        return
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archived_path = log_path.parent / f"{timestamp}_{log_path.name}"
    suffix = 1
    while archived_path.exists():
        archived_path = log_path.parent / f"{timestamp}_{suffix}_{log_path.name}"
        suffix += 1
    log_path.rename(archived_path)
    _ROLLED_LOG_PATHS.add(resolved_path)


def setup_logging(
    level_name: str = "INFO", log_file: Optional[Union[str, Path]] = None
) -> None:
    """Configure root logging and rotate an existing target file at startup."""
    level = getattr(logging, level_name.upper(), logging.INFO)

    if not log_file:
        return
    log_path = resolve_log_file_path(log_file)

    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_existing_log_file(log_path)

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
XMPP_LOGGER_NAMES = ("asky.daemon", "asky.plugins.xmpp_daemon", "slixmpp")


def _handler_targets_path(handler: logging.Handler, log_path: Path) -> bool:
    base_filename = getattr(handler, "baseFilename", None)
    if not base_filename:
        return False
    try:
        return Path(base_filename).resolve() == log_path.resolve()
    except Exception:
        return Path(base_filename) == log_path


def setup_xmpp_logging(level_name: str = "DEBUG") -> None:
    """Attach dedicated handlers for XMPP namespaces to xmpp.log.

    This does not affect root logger destinations; root output continues to the
    main log file. Captured namespaces are listed in ``XMPP_LOGGER_NAMES``.
    """
    level = getattr(logging, level_name.upper(), logging.DEBUG)
    log_path = Path(XMPP_LOG_FILE).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _archive_existing_log_file(log_path)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for logger_name in XMPP_LOGGER_NAMES:
        target_logger = logging.getLogger(logger_name)
        target_logger.setLevel(level)
        already_attached = any(
            _handler_targets_path(existing_handler, log_path)
            for existing_handler in target_logger.handlers
        )
        if already_attached:
            continue
        handler = RotatingFileHandler(
            log_path,
            mode="a",
            maxBytes=MAX_LOG_FILE_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        handler.setLevel(level)
        target_logger.addHandler(handler)

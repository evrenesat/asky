"""Logging configuration for asky."""

import logging
import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def generate_timestamped_log_path(base_path: str) -> Path:
    """Generate a log file path with a timestamp prefix."""
    path = Path(base_path).expanduser()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return path.parent / f"{timestamp}_{path.name}"


def setup_logging(level_name: str = "INFO", log_file: str = None) -> None:
    """Configure logging to write to a file."""
    level = getattr(logging, level_name.upper(), logging.INFO)

    if log_file:
        # Use provided log file path
        log_path = Path(log_file)
    else:
        return

    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create file handler
    handler = RotatingFileHandler(
        log_path,
        mode="a",  # Append to allow multiple handlers or re-opens
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    # Remove existing handlers to avoid duplicates if re-initialized
    if logger.handlers:
        logger.handlers.clear()

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

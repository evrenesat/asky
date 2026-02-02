"""Logging configuration for asky."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level_name: str, log_file: str) -> None:
    """Configure logging to write to a file."""
    level = getattr(logging, level_name.upper(), logging.INFO)

    # Expand user path
    log_path = Path(log_file).expanduser()

    # Ensure directory exists
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Create file handler
    handler = RotatingFileHandler(
        log_path,
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
    ]
    for lib in noisy_libraries:
        logging.getLogger(lib).setLevel(logging.WARNING)

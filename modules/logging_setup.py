from __future__ import annotations

import logging
import os
from dotenv import load_dotenv


load_dotenv()


def _to_level(name: str, default: int) -> int:
    if not name:
        return default
    n = name.strip().upper()
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    return mapping.get(n, default)


def setup_logging():
    """Configure python's stdlib logging.

    This primarily controls 3rd party libraries (e.g. httpx/httpcore) so we don't
    leak sensitive URLs (Telegram bot token in path) into container logs.
    """

    app_level = _to_level(os.getenv("LOG_LEVEL", "INFO"), logging.INFO)
    httpx_level = _to_level(os.getenv("HTTPX_LOG_LEVEL", "WARNING"), logging.WARNING)
    httpcore_level = _to_level(os.getenv("HTTPCORE_LOG_LEVEL", os.getenv("HTTPX_LOG_LEVEL", "WARNING")), logging.WARNING)

    # If something already configured handlers, basicConfig won't override.
    # That's fine; we still enforce per-logger levels below.
    logging.basicConfig(
        level=app_level,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    for name, level in (
        ("httpx", httpx_level),
        ("httpcore", httpcore_level),
        ("h11", httpcore_level),
    ):
        logging.getLogger(name).setLevel(level)

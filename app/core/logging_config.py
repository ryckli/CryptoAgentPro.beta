from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.core.config import settings

_logger: logging.Logger | None = None


def setup_logging(log_level: str | None = None):
    global _logger
    level = log_level or settings.LOG_LEVEL
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    _logger = logging.getLogger("cryptoagents")
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    _logger.addHandler(console)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    _logger.addHandler(file_handler)


def get_logger(name: str = "cryptoagents") -> logging.Logger:
    if _logger is None:
        setup_logging()
    return _logger.getChild(name) if _logger else logging.getLogger(name)

"""Centralized structured logging.

Per the coding standard: never use print(). Every module obtains a logger via
``get_logger(__name__)``. Separate files are produced for the main domains so
that browser/AI/job noise can be inspected independently.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Logger-name prefix -> dedicated category file. A record also propagates to
# the catch-all application.log and the console; WARNING+ also hits errors.log.
_DOMAIN_FILES = {
    "careerpilot.browser": "browser.log",
    "careerpilot.ai": "ai.log",
    "careerpilot.db": "database.log",
    "careerpilot.core.scheduler": "scheduler.log",
}
_SYSTEM_FILE = "application.log"
_ERROR_FILE = "errors.log"


def setup_logging(log_dir: str | Path, level: int = logging.INFO) -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)

    root = logging.getLogger("careerpilot")
    root.setLevel(level)
    root.handlers.clear()

    # Console.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # System (everything) + errors (WARNING+) files, rotating.
    system_handler = _rotating(log_dir / _SYSTEM_FILE, formatter)
    root.addHandler(system_handler)

    error_handler = _rotating(log_dir / _ERROR_FILE, formatter)
    error_handler.setLevel(logging.WARNING)
    root.addHandler(error_handler)

    # Domain-specific files via dedicated child loggers.
    for prefix, filename in _DOMAIN_FILES.items():
        handler = _rotating(log_dir / filename, formatter)
        domain_logger = logging.getLogger(prefix)
        domain_logger.addHandler(handler)
        # Records still propagate to root (system.log + console).

    _CONFIGURED = True


def _rotating(path: Path, formatter: logging.Formatter) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    return handler


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``careerpilot`` namespace."""
    if not name.startswith("careerpilot"):
        name = f"careerpilot.{name}"
    return logging.getLogger(name)

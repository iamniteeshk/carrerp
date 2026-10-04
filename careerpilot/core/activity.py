"""Small on-disk activity board the dashboard reads while the bot runs.

The scheduler, collectors, and pipeline publish here. The file is local only
and must never stop a scan if it cannot be written.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)

_PATH = Path("logs/activity.json")


def publish_activity(**fields) -> None:
    """Merge fields into logs/activity.json."""
    try:
        current = read_activity()
        current.update({k: v for k, v in fields.items() if v is not None})
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(current, indent=2, default=str), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write activity board: %s", exc)


def read_activity() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}

"""Remember manual Apply / Reject choices so later scoring can follow them.

Stored as JSON next to the database. A short summary is appended to the AI
prompt. Writes never raise.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


class DecisionMemory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read decision memory %s: %s", self.path, exc)
            return []

    def record(self, *, action: str, job_title: str, company: str = "",
               portal: str = "", reason: str = "") -> None:
        action = (action or "").strip().lower()
        if action not in ("apply", "reject"):
            return
        entry = {
            "action": action,
            "job_title": (job_title or "").strip(),
            "company": (company or "").strip(),
            "portal": (portal or "").strip(),
            "reason": (reason or "").strip()[:300],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            data = self.all()
            data.append(entry)
            data = data[-400:]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except OSError as exc:
                logger.warning("Could not write decision memory: %s", exc)
                return
        logger.info("Learned manual %s: %s @ %s", action, entry["job_title"],
                    entry["company"])

    def summary(self, limit: int = 8) -> str:
        data = self.all()
        if not data:
            return ""
        applied = [e for e in data if e.get("action") == "apply"][-limit:]
        rejected = [e for e in data if e.get("action") == "reject"][-limit:]

        def _fmt(rows: list[dict]) -> str:
            parts = []
            for e in rows:
                bit = e.get("job_title") or "untitled"
                if e.get("company"):
                    bit += f" @ {e['company']}"
                parts.append(bit)
            return "; ".join(parts)

        chunks = []
        if applied:
            chunks.append("Operator chose to apply to: " + _fmt(applied) + ".")
        if rejected:
            chunks.append("Operator chose to reject: " + _fmt(rejected) + ".")
        chunks.append(
            "Follow these choices when a new job is similar. "
            "If you are not sure, say review — do not force apply or reject.")
        return " ".join(chunks)

"""Long-running retention and cleanup for 24x7 operation.

Prevents unbounded growth of cache files, reports, screenshots, debug evidence,
DB backups, and learning JSON stores. Safe to call repeatedly; never raises to
the caller (logs and returns a summary dict).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class RetentionConfig:
    """Age limits in days. 0 disables that cleanup category."""
    cache_days: int = 30
    report_days: int = 60
    screenshot_days: int = 14
    evidence_days: int = 14
    backup_days: int = 30
    human_interaction_days: int = 14
    session_history_max: int = 500
    good_jobs_max: int = 1000
    vacuum_db: bool = True


@dataclass
class CleanupResult:
    deleted_files: int = 0
    freed_bytes: int = 0
    truncated_stores: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "deleted_files": self.deleted_files,
            "freed_bytes": self.freed_bytes,
            "truncated_stores": list(self.truncated_stores),
            "errors": list(self.errors),
        }


def _purge_older_than(root: Path, days: int, *,
                      patterns: tuple[str, ...] = ("*",),
                      result: CleanupResult) -> None:
    if days <= 0 or not root.exists():
        return
    cutoff = time.time() - days * 86400
    for pattern in patterns:
        for path in root.rglob(pattern):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    size = path.stat().st_size
                    path.unlink(missing_ok=True)
                    result.deleted_files += 1
                    result.freed_bytes += size
            except OSError as exc:
                result.errors.append(f"{path}: {exc}")


def _trim_json_list(path: Path, max_items: int, result: CleanupResult,
                    label: str) -> None:
    if max_items <= 0 or not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) <= max_items:
            return
        trimmed = data[-max_items:]
        path.write_text(json.dumps(trimmed, indent=2), encoding="utf-8")
        result.truncated_stores.append(f"{label}:{len(data)}->{len(trimmed)}")
    except (OSError, json.JSONDecodeError) as exc:
        result.errors.append(f"{path}: {exc}")


def run_maintenance(*, cache_dir: str = "cache/jobs",
                    report_dir: str = "reports",
                    screenshot_dir: str = "screenshots",
                    evidence_dir: str = "debug",
                    backup_dir: str = "database/backups",
                    human_dir: str = "human_interactions",
                    session_history_path: str = "database/session_history.json",
                    good_jobs_path: str = "database/good_jobs.json",
                    database_path: str = "",
                    config: RetentionConfig | None = None) -> CleanupResult:
    """Run all retention cleanups. Never raises."""
    cfg = config or RetentionConfig()
    result = CleanupResult()
    try:
        _purge_older_than(Path(cache_dir), cfg.cache_days,
                          patterns=("*.json",), result=result)
        _purge_older_than(Path(report_dir), cfg.report_days,
                          patterns=("*.csv", "*.md", "*.txt"), result=result)
        _purge_older_than(Path(screenshot_dir), cfg.screenshot_days,
                          patterns=("*.png", "*.jpg", "*.jpeg", "*.webp"),
                          result=result)
        _purge_older_than(Path(evidence_dir), cfg.evidence_days,
                          patterns=("*",), result=result)
        _purge_older_than(Path(backup_dir), cfg.backup_days,
                          patterns=("*.db", "*.sqlite", "*.bak", "*"),
                          result=result)
        _purge_older_than(Path(human_dir), cfg.human_interaction_days,
                          patterns=("*",), result=result)
        _trim_json_list(Path(session_history_path), cfg.session_history_max,
                        result, "session_history")
        _trim_json_list(Path(good_jobs_path), cfg.good_jobs_max,
                        result, "good_jobs")
        if cfg.vacuum_db and database_path:
            _vacuum_db(database_path, result)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(str(exc))
        logger.warning("Maintenance error: %s", exc)
    logger.info("Maintenance complete: deleted=%s freed=%sB truncated=%s errors=%s",
                result.deleted_files, result.freed_bytes,
                result.truncated_stores, len(result.errors))
    return result


def _vacuum_db(database_path: str, result: CleanupResult) -> None:
    try:
        import sqlite3
        path = Path(database_path)
        if not path.exists():
            return
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
        result.truncated_stores.append("db:vacuum")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"vacuum: {exc}")


def write_health_heartbeat(path: str | Path = "logs/health.json",
                           *, status: str = "ok",
                           extra: dict | None = None) -> Path:
    """Write a small heartbeat file for external watchdogs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p

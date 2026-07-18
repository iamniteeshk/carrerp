"""Full production backup / restore (config, DB, resumes, optional profiles).

Preserves user secrets and Chrome sessions. Never overwrites existing restore
targets without an explicit force flag. Used by CLI and PowerShell wrappers.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class BackupResult:
    path: str
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "copied": list(self.copied),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


def _copy_path(src: Path, dest: Path, result: BackupResult, label: str) -> None:
    if not src.exists():
        result.skipped.append(f"{label}: missing ({src})")
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, dirs_exist_ok=False)
        else:
            shutil.copy2(src, dest)
        result.copied.append(label)
    except OSError as exc:
        result.errors.append(f"{label}: {exc}")


def create_backup(*, root: str | Path = ".",
                  backup_root: str | Path = "backups",
                  config_path: str = "config/config.yaml",
                  env_path: str = ".env",
                  database_path: str = "database/careerpilot.db",
                  profiles_dir: str = "profiles",
                  browser_profiles: str = "profiles_browser",
                  logs_dir: str = "logs",
                  reports_dir: str = "reports",
                  include_chrome_profiles: bool = False,
                  include_logs: bool = True,
                  include_reports: bool = True,
                  stamp: str | None = None) -> BackupResult:
    """Create backups/<YYYY-MM-DD>/ (or stamp) with production-critical files."""
    root = Path(root)
    day = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest_root = Path(backup_root) / day
    dest_root.mkdir(parents=True, exist_ok=True)
    result = BackupResult(path=str(dest_root.resolve()))

    _copy_path(root / config_path, dest_root / "config" / Path(config_path).name,
               result, "config")
    _copy_path(root / env_path, dest_root / ".env", result, ".env")
    _copy_path(root / database_path, dest_root / "database" / Path(database_path).name,
               result, "database")
    # Also use SQLite online backup when possible for a consistent snapshot.
    try:
        from ..db.database import Database
        db_src = root / database_path
        if db_src.exists():
            db = Database(str(db_src))
            db.initialize()
            online = db.backup(dest_root / "database")
            db.close()
            result.copied.append(f"database_online:{Path(online).name}")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"database_online: {exc}")

    _copy_path(root / profiles_dir, dest_root / "profiles", result, "profiles")
    if include_chrome_profiles:
        _copy_path(root / browser_profiles, dest_root / "profiles_browser",
                   result, "chrome_profiles")
    else:
        result.skipped.append("chrome_profiles: disabled (pass include_chrome_profiles)")
    if include_logs:
        _copy_path(root / logs_dir, dest_root / "logs", result, "logs")
    if include_reports:
        _copy_path(root / reports_dir, dest_root / "reports", result, "reports")

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "include_chrome_profiles": include_chrome_profiles,
        **result.as_dict(),
    }
    try:
        (dest_root / "backup_manifest.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"manifest: {exc}")

    logger.info("Backup complete -> %s (copied=%s errors=%s)",
                result.path, len(result.copied), len(result.errors))
    return result


def restore_backup(backup_dir: str | Path, *, root: str | Path = ".",
                   force: bool = False,
                   restore_chrome_profiles: bool = False) -> BackupResult:
    """Restore from a backups/YYYY-MM-DD directory into the install root.

    By default refuses to overwrite existing config/.env/database unless
    ``force=True``. Chrome profiles restore only when explicitly requested.
    """
    src = Path(backup_dir)
    root = Path(root)
    result = BackupResult(path=str(src.resolve()))
    if not src.exists():
        result.errors.append(f"backup dir not found: {src}")
        return result

    mapping = [
        ("config", root / "config", True),
        (".env", root / ".env", False),
        ("database", root / "database", True),
        ("profiles", root / "profiles", True),
    ]
    if restore_chrome_profiles:
        mapping.append(("profiles_browser", root / "profiles_browser", True))

    for name, dest, is_dir in mapping:
        item = src / name
        if not item.exists():
            # config may be nested as config/config.yaml
            if name == "config" and (src / "config").exists():
                item = src / "config"
            else:
                result.skipped.append(f"{name}: not in backup")
                continue
        if dest.exists() and not force:
            result.skipped.append(
                f"{name}: exists (pass force=True to overwrite)")
            continue
        try:
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
            result.copied.append(name)
        except OSError as exc:
            result.errors.append(f"{name}: {exc}")

    logger.info("Restore from %s complete (copied=%s skipped=%s errors=%s)",
                src, result.copied, result.skipped, result.errors)
    return result

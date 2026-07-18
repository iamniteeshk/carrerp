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


def create_backup(*, root: str | Path | None = None,
                  backup_root: str | Path | None = None,
                  config_path: str | Path | None = None,
                  env_path: str | Path | None = None,
                  database_path: str | Path | None = None,
                  profiles_dir: str | Path | None = None,
                  browser_profiles: str | Path | None = None,
                  logs_dir: str | Path | None = None,
                  reports_dir: str | Path | None = None,
                  include_chrome_profiles: bool = False,
                  include_logs: bool = True,
                  include_reports: bool = True,
                  include_certificates: bool = True,
                  compress: bool = False,
                  stamp: str | None = None) -> BackupResult:
    """Create backups/<YYYY-MM-DD>/ with production-critical user data."""
    from .paths import get_layout
    layout = get_layout()
    root = Path(root) if root is not None else layout.data_root
    backup_root = Path(backup_root) if backup_root is not None else layout.backups_root

    def abs_path(p: str | Path | None, default: Path) -> Path:
        if p is None:
            return default
        pp = Path(p)
        return pp if pp.is_absolute() else (root / pp)

    config_path = abs_path(config_path, layout.config_yaml)
    env_path = abs_path(env_path, layout.env_file)
    database_path = abs_path(database_path, layout.database_path)
    profiles_dir = abs_path(profiles_dir, layout.profiles_dir)
    browser_profiles = abs_path(browser_profiles, layout.browser_dir)
    logs_dir = abs_path(logs_dir, layout.logs_dir)
    reports_dir = abs_path(reports_dir, layout.reports_dir)
    certificates_dir = layout.certificates_dir
    documents_dir = layout.documents_dir

    day = stamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest_root = Path(backup_root) / day
    dest_root.mkdir(parents=True, exist_ok=True)
    result = BackupResult(path=str(dest_root.resolve()))

    _copy_path(config_path, dest_root / "config" / "config.yaml", result, "config")
    _copy_path(env_path, dest_root / ".env", result, ".env")
    _copy_path(database_path, dest_root / "database" / database_path.name, result, "database")
    try:
        from ..db.database import Database
        if database_path.exists():
            db = Database(str(database_path))
            db.initialize()
            online = db.backup(dest_root / "database")
            db.close()
            result.copied.append(f"database_online:{Path(online).name}")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"database_online: {exc}")

    _copy_path(profiles_dir, dest_root / "profiles", result, "profiles")
    _copy_path(documents_dir, dest_root / "documents", result, "documents")
    if include_certificates:
        _copy_path(certificates_dir, dest_root / "certificates", result, "certificates")
    if include_chrome_profiles:
        _copy_path(browser_profiles, dest_root / "browser", result, "browser_profiles")
    else:
        result.skipped.append("browser_profiles: disabled (pass include_chrome_profiles)")
    if include_logs:
        _copy_path(logs_dir, dest_root / "logs", result, "logs")
    if include_reports:
        _copy_path(reports_dir, dest_root / "reports", result, "reports")

    # Learning JSON next to the DB
    for name in ("good_jobs.json", "session_history.json"):
        _copy_path(database_path.parent / name, dest_root / "database" / name,
                   result, name)

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(layout.data_root),
        "include_chrome_profiles": include_chrome_profiles,
        "kind": "full",
        **result.as_dict(),
    }
    try:
        (dest_root / "backup_manifest.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"manifest: {exc}")

    # Optional compressed archive beside the day folder (same stamp).
    # Callers pass compress=True via create_backup(..., compress=True).
    if compress:
        try:
            zpath = create_backup_zip(dest_root)
            result.copied.append(f"zip:{zpath.name}")
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"zip: {exc}")

    logger.info("Backup complete -> %s (copied=%s errors=%s)",
                result.path, len(result.copied), len(result.errors))
    return result


def create_backup_zip(backup_dir: str | Path,
                      zip_path: str | Path | None = None) -> Path:
    """Compress an existing backups/YYYY-MM-DD folder to a .zip archive."""
    src = Path(backup_dir)
    if not src.is_dir():
        raise FileNotFoundError(f"backup dir not found: {src}")
    out = Path(zip_path) if zip_path else src.with_suffix(".zip")
    # shutil.make_archive wants path without .zip suffix
    base = str(out.with_suffix(""))
    archive = shutil.make_archive(base, "zip", root_dir=str(src.parent),
                                  base_dir=src.name)
    return Path(archive)


def verify_backup(backup_dir: str | Path) -> dict:
    """Verify a backup folder has the critical pieces. Returns a report dict."""
    src = Path(backup_dir)
    report = {"path": str(src), "ok": True, "missing": [], "present": []}
    required = [
        "backup_manifest.json",
        "config/config.yaml",
        ".env",
        "profiles",
    ]
    optional = [
        "database/careerpilot.db",
        "documents",
        "certificates",
        "browser",
        "logs",
        "reports",
        "database/good_jobs.json",
    ]
    if not src.exists():
        report["ok"] = False
        report["missing"].append("(entire backup dir)")
        return report
    for rel in required:
        p = src / rel
        if p.exists():
            report["present"].append(rel)
        else:
            report["missing"].append(rel)
            report["ok"] = False
    for rel in optional:
        p = src / rel
        if p.exists():
            report["present"].append(rel)
    return report


def restore_backup(backup_dir: str | Path, *, root: str | Path | None = None,
                   force: bool = False,
                   restore_chrome_profiles: bool = False) -> BackupResult:
    """Restore from backups/YYYY-MM-DD into the data root."""
    from .paths import get_layout
    layout = get_layout()
    src = Path(backup_dir)
    root = Path(root) if root is not None else layout.data_root
    result = BackupResult(path=str(src.resolve()))
    if not src.exists():
        result.errors.append(f"backup dir not found: {src}")
        return result

    mapping = [
        ("config", layout.config_dir if root == layout.data_root else root / "config", True),
        (".env", layout.env_file if root == layout.data_root else root / ".env", False),
        ("database", layout.database_dir if root == layout.data_root else root / "database", True),
        ("profiles", layout.profiles_dir if root == layout.data_root else root / "profiles", True),
        ("documents", layout.documents_dir if root == layout.data_root else root / "documents", True),
        ("certificates", layout.certificates_dir if root == layout.data_root else root / "certificates", True),
    ]
    if restore_chrome_profiles:
        # Prefer new name; accept legacy profiles_browser in the backup.
        browser_src = "browser" if (src / "browser").exists() else "profiles_browser"
        mapping.append((browser_src, layout.browser_dir if root == layout.data_root
                        else root / "browser", True))

    for name, dest, is_dir in mapping:
        item = src / name
        if not item.exists():
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

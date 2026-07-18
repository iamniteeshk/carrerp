"""Ops hardening: backup/restore, health snapshot, banner, validation fixes."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.backup_ops import create_backup, restore_backup
from careerpilot.core.health_snapshot import collect_health
from careerpilot.core.startup_banner import build_banner
from careerpilot.core.validation import validate_all
from tests._fixture import make_deployment

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def test_backup_and_restore_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg, env = make_deployment(tmp)
        # Seed a fake db file path from config
        import yaml
        raw = yaml.safe_load(Path(cfg).read_text())
        db_path = raw["database"]["path"]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # initialize real sqlite
        from careerpilot.db.database import Database
        Database(db_path).initialize()

        old = os.getcwd()
        try:
            os.chdir(tmp)
            result = create_backup(
                config_path="config.yaml" if Path("config.yaml").exists() else cfg,
                env_path=env if Path(env).is_absolute() else env,
                database_path=db_path,
                profiles_dir=str(tmp / "profiles"),
                logs_dir=str(tmp / "logs"),
                reports_dir=str(tmp / "reports"),
                backup_root=str(tmp / "backups"),
                include_chrome_profiles=False,
            )
            check("backup created path", Path(result.path).is_dir(), result.path)
            check("backup copied config or database",
                  any("config" in c or "database" in c for c in result.copied),
                  str(result.copied))
            # Restore into a sibling root
            dest = tmp / "restored"
            dest.mkdir()
            r2 = restore_backup(result.path, root=dest, force=True)
            check("restore copied something", len(r2.copied) + len(r2.skipped) > 0,
                  str(r2.as_dict()))
        finally:
            os.chdir(old)


def test_banner_contains_version():
    text = build_banner()
    check("banner has version", "version" in text.lower() and "4.0.0" in text)
    check("banner has python", "python" in text.lower())
    check("banner has playwright", "playwright" in text.lower())


def test_health_snapshot_shape():
    snap = collect_health()
    for key in ("timestamp", "process", "disk", "database", "resources"):
        check(f"health has {key}", key in snap)


def test_validation_fix_hints():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bad = tmp / "config.yaml"
        bad.write_text("database: {}\n", encoding="utf-8")
        report = validate_all(bad, tmp / "missing.env")
        msgs = " ".join(i.message for i in report.errors)
        check("invalid config mentions Fix", "Fix:" in msgs or "missing" in msgs.lower(),
              msgs[:200])


def test_scripts_exist():
    root = Path(__file__).resolve().parents[1]
    for name in ("scripts/update_careerpilot.ps1", "scripts/backup.ps1",
                 "scripts/restore.ps1", "scripts/health.ps1",
                 "scripts/Allow-DashboardLan.ps1",
                 "scripts/Register-CareerPilotStartup.ps1",
                 "docs/PRODUCTION_CHECKLIST.md", "requirements.lock"):
        check(name, (root / name).exists())
    reg = (root / "scripts/Register-CareerPilotStartup.ps1").read_text(
        encoding="utf-8")
    check("startup LogOn+Startup modes", "LogOn" in reg and "Startup" in reg)
    check("startup restart every 1 min", "Minutes 1" in reg)


if __name__ == "__main__":
    print("=== ops hardening ===")
    test_backup_and_restore_roundtrip()
    test_banner_contains_version()
    test_health_snapshot_shape()
    test_validation_fix_hints()
    test_scripts_exist()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

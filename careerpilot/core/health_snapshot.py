"""Production health snapshot for operators (and health.ps1)."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging_setup import get_logger

logger = get_logger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_pid_file() -> Path:
    try:
        from .paths import get_layout
        return get_layout().pid_file
    except Exception:  # noqa: BLE001
        return Path("careerpilot.pid")


def _pid_alive(pid_file: Path | None = None) -> dict[str, Any]:
    pid_file = pid_file or _default_pid_file()
    if not pid_file.exists():
        return {"running": False, "pid": None, "detail": f"no {pid_file.name}"}
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return {"running": False, "pid": None, "detail": "invalid pid file"}
    try:
        os.kill(pid, 0)
        return {"running": True, "pid": pid, "detail": "process alive"}
    except OSError:
        return {"running": False, "pid": pid, "detail": "stale pid file"}


def _resource_usage() -> dict[str, Any]:
    out: dict[str, Any] = {"cpu_percent": None, "ram_percent": None, "ram_used_mb": None}
    try:
        # Prefer psutil if installed; otherwise /proc on Linux / skip on Windows.
        import psutil  # type: ignore
        out["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        out["ram_percent"] = mem.percent
        out["ram_used_mb"] = round(mem.used / (1024 * 1024), 1)
        return out
    except Exception:  # noqa: BLE001
        pass
    try:
        # Windows-friendly fallback via PowerShell (best-effort).
        if os.name == "nt":
            import subprocess
            ps = (
                "$cpu=(Get-Counter '\\Processor(_Total)\\% Processor Time')"
                ".CounterSamples.CookedValue; "
                "$os=Get-CimInstance Win32_OperatingSystem; "
                "$ram=100*(1-($os.FreePhysicalMemory/$os.TotalVisibleMemorySize)); "
                "Write-Output \"$cpu|$ram|$([math]::Round("
                "($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1024,1))\""
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split("|")
                if len(parts) >= 3:
                    out["cpu_percent"] = round(float(parts[0]), 1)
                    out["ram_percent"] = round(float(parts[1]), 1)
                    out["ram_used_mb"] = float(parts[2])
    except Exception as exc:  # noqa: BLE001
        out["detail"] = str(exc)
    return out


def collect_health(*, config=None, db_path: str = "",
                   heartbeat_path: str = "") -> dict[str, Any]:
    """Build a single JSON-serialisable health snapshot. Never raises."""
    try:
        from .paths import get_layout
        layout = get_layout()
        data_root = layout.data_root
        pid_file = layout.pid_file
        default_hb = layout.logs_dir / "health.json"
        default_browser = layout.browser_dir
    except Exception:  # noqa: BLE001
        layout = None
        data_root = Path(".")
        pid_file = Path("careerpilot.pid")
        default_hb = Path("logs/health.json")
        default_browser = Path("browser")

    if not heartbeat_path:
        if config is not None and getattr(config, "log_path", None):
            heartbeat_path = str(Path(config.log_path) / "health.json")
        else:
            heartbeat_path = str(default_hb)

    snap: dict[str, Any] = {
        "timestamp": _utcnow(),
        "process": _pid_alive(pid_file),
        "resources": _resource_usage(),
        "disk": {},
        "database": {},
        "ai": {},
        "telegram": {},
        "scheduler": {},
        "browser": {},
        "last_scan": {},
        "last_application": {},
        "heartbeat": {},
        "layout": {
            "data_root": str(data_root),
            "pid_file": str(pid_file),
        },
    }
    try:
        usage = shutil.disk_usage(str(data_root))
        snap["disk"] = {
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_percent": round(100 * (1 - usage.free / usage.total), 1),
        }
    except OSError as exc:
        snap["disk"] = {"error": str(exc)}

    # Heartbeat written by scheduler / maintenance.
    hb = Path(heartbeat_path)
    if hb.exists():
        try:
            snap["heartbeat"] = json.loads(hb.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            snap["heartbeat"] = {"error": str(exc)}

    path = db_path
    if config is not None:
        path = path or getattr(config, "database_path", "")
    if path and Path(path).exists():
        try:
            from ..db.database import Database
            db = Database(path)
            conn = db.connect()
            # Last completed scan
            row = conn.execute(
                "SELECT started_at, finished_at, status, jobs_found, jobs_matched, "
                "jobs_applied FROM scan_history WHERE status != 'RUNNING' "
                "ORDER BY scan_id DESC LIMIT 1").fetchone()
            if row:
                snap["last_scan"] = dict(row)
                snap["scheduler"] = {
                    "alive": snap["process"].get("running"),
                    "last_scan_status": row["status"],
                    "last_scan_finished": row["finished_at"],
                }
            app = conn.execute(
                "SELECT applied_at, company, portal, application_status FROM "
                "applications WHERE dry_run=0 AND application_status='APPLIED' "
                "ORDER BY application_id DESC LIMIT 1").fetchone()
            if app:
                snap["last_application"] = dict(app)
            note = conn.execute(
                "SELECT sent_at, notification_type FROM notifications "
                "WHERE sent=1 ORDER BY notification_id DESC LIMIT 1").fetchone()
            if note:
                snap["telegram"] = {
                    "last_sent_at": note["sent_at"],
                    "last_type": note["notification_type"],
                }
            snap["database"] = {"reachable": True, "path": path}
            db.close()
        except Exception as exc:  # noqa: BLE001
            snap["database"] = {"reachable": False, "error": str(exc)}
    else:
        snap["database"] = {"reachable": False, "error": "db path missing"}

    # Browser: presence of profile dirs + process heuristic.
    try:
        profiles = Path(getattr(config, "browser_profiles_path", str(default_browser))
                        if config else str(default_browser))
        snap["browser"] = {
            "profile_dir_exists": profiles.exists(),
            "linkedin_profile": (profiles / "linkedin").exists(),
            "naukri_profile": (profiles / "naukri").exists(),
            "note": "Process-level Chrome attach not probed here; "
                    "see ensure_healthy during scans",
        }
    except Exception as exc:  # noqa: BLE001
        snap["browser"] = {"error": str(exc)}

    # AI reachability (cheap — uses configured keys only if config present).
    if config is not None:
        try:
            from ..ai.engine import AIEngine
            engine = AIEngine(
                config.ai,
                candidate_profile="(health)",
                profile_names=config.profile_engine.names(),
                default_profile=config.default_career_profile)
            snap["ai"] = {
                "any_available": engine.any_available(),
                "active_provider": getattr(config.ai, "active_provider", ""),
            }
        except Exception as exc:  # noqa: BLE001
            snap["ai"] = {"any_available": False, "error": str(exc)}

    if config is not None:
        token = getattr(config, "telegram_token", "") or ""
        chat = getattr(config, "telegram_chat_id", "") or ""
        snap["telegram"] = {
            **snap.get("telegram", {}),
            "configured": bool(token and chat),
        }

    return snap


def write_health_snapshot(path: str | Path | None = None, **kwargs) -> Path:
    if path is None:
        try:
            from .paths import get_layout
            layout = get_layout()
            path = layout.logs_dir / "health_snapshot.json"
        except Exception:  # noqa: BLE001
            path = Path("logs/health_snapshot.json")
    snap = collect_health(**kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    return p

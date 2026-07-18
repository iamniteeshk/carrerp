"""Effective runtime configuration + configuration health for Mission Control.

Read-only views over the live ``AppConfig`` / Doctor-style checks. Never exposes
secret values — only Configured / Missing status.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import get_layout


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secret_status(*env_names: str) -> dict[str, str]:
    present = [n for n in env_names if (os.getenv(n) or "").strip()]
    if present:
        return {"status": "Configured", "vars": present}
    return {"status": "Missing", "vars": list(env_names)}


def _browser_session_status(profiles_path: str) -> dict[str, Any]:
    root = Path(profiles_path)
    out: dict[str, Any] = {"path": str(root), "portals": {}}

    def _used(d: Path) -> str:
        if not d.exists():
            return "Missing"
        if (d / "Default").exists() or (d / "Local State").exists():
            return "Present"
        try:
            return "Present" if any(d.iterdir()) else "Empty"
        except OSError:
            return "Error"

    for portal in ("linkedin", "naukri"):
        out["portals"][portal] = _used(root / portal)
    return out


def build_config_summary(*, config, hub=None) -> dict[str, Any]:
    """Effective runtime configuration snapshot (secrets redacted)."""
    layout = get_layout()
    cfg = config
    cand = getattr(cfg, "candidate", None)
    apply = getattr(cfg, "apply", None)
    ai = getattr(cfg, "ai", None)
    browser = getattr(cfg, "browser", None)
    engine = getattr(cfg, "profile_engine", None)

    last_profile = None
    if hub is not None:
        last_profile = getattr(hub, "last_profile_name", None)

    providers = []
    if ai is not None:
        for spec in getattr(ai, "providers", []) or []:
            providers.append({
                "name": getattr(spec, "name", ""),
                "enabled": getattr(spec, "enabled", True),
                "kind": getattr(spec, "kind", ""),
                "preferred_model": getattr(spec, "preferred_model", "") or "",
                "has_keys": bool(getattr(spec, "api_keys", None)),
            })

    profiles = engine.summary_rows() if engine is not None else []
    source = getattr(cfg, "source_path", "") or ""
    source_mtime = None
    if source and Path(source).exists():
        source_mtime = datetime.fromtimestamp(
            Path(source).stat().st_mtime, tz=timezone.utc).isoformat()

    return {
        "generated_at": _utcnow(),
        "read_only": True,
        "candidate": {
            "full_name": getattr(cand, "full_name", "") if cand else "",
            "email": getattr(cand, "email", "") if cand else "",
            "phone": getattr(cand, "phone", "") if cand else "",
            "current_location": getattr(cand, "current_location", "") if cand else "",
            "remote_preference": getattr(cand, "remote_preference", "") if cand else "",
            "willing_to_relocate": getattr(cand, "willing_to_relocate", None) if cand else None,
            "total_experience": getattr(cand, "total_experience", "") if cand else "",
            "current_designation": getattr(cand, "current_designation", "") if cand else "",
            "current_company": getattr(cand, "current_company", "") if cand else "",
        },
        "profiles": {
            "default": getattr(cfg, "default_career_profile", ""),
            "current": last_profile or getattr(cfg, "default_career_profile", ""),
            "count": len(profiles),
            "enabled_count": sum(1 for p in profiles if p.get("enabled")),
            "rows": profiles,
            "dir": getattr(cfg, "profiles_dir", ""),
        },
        "ai": {
            "active_provider": getattr(ai, "active_provider", "") if ai else "",
            "timeout": getattr(ai, "request_timeout", None) if ai else None,
            "max_retries": getattr(ai, "max_retries", None) if ai else None,
            "min_apply_score": getattr(ai, "min_apply_score", None) if ai else None,
            "providers": providers,
            "gemini_keys_status": _secret_status(
                "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"),
        },
        "apply": {
            "mode": getattr(apply, "mode", "") if apply else "",
            "require_final_confirmation": getattr(
                apply, "require_final_confirmation", None) if apply else None,
            "max_applications_per_day": getattr(
                apply, "max_applications_per_day", None) if apply else None,
            "easy_apply_only": getattr(apply, "easy_apply_only", None) if apply else None,
            "min_apply_score": getattr(ai, "min_apply_score", None) if ai else None,
        },
        "browser": {
            "channel": getattr(browser, "channel", "") if browser else "",
            "headless": getattr(browser, "headless", None) if browser else None,
            "profiles_path": getattr(browser, "profiles_path", "") if browser else "",
            "sessions": _browser_session_status(
                getattr(browser, "profiles_path", "browser") if browser else "browser"),
        },
        "scheduler": {
            "scan_interval_hours": getattr(cfg, "scan_interval_hours", None),
            "daily_summary_hour": getattr(cfg, "daily_summary_hour", None),
            "paused": getattr(hub, "paused", None) if hub is not None else None,
        },
        "database": {
            "path": getattr(cfg, "database_path", ""),
        },
        "runtime": {
            "app_name": getattr(cfg, "app_name", "CareerPilot"),
            "data_root": getattr(cfg, "data_root", str(layout.data_root)),
            "app_root": getattr(cfg, "app_root", str(layout.app_root)),
            "backups_root": getattr(cfg, "backups_root", str(layout.backups_root)),
            "dashboard_host": getattr(cfg, "dashboard_host", ""),
            "dashboard_port": getattr(cfg, "dashboard_port", None),
            "log_path": getattr(cfg, "log_path", ""),
            "report_path": getattr(cfg, "report_path", ""),
            "uptime_seconds": round(hub.uptime_seconds, 1) if hub is not None else None,
            "phase": hub.current_phase() if hub is not None else None,
        },
        "reload": {
            "source_path": source,
            "source_mtime": source_mtime,
            "note": "Restart CareerPilot to reload config.yaml / .env changes",
        },
        "secrets": {
            "telegram": _secret_status("TELEGRAM_BOT_TOKEN"),
            "telegram_chat": {
                "status": "Configured" if (
                    getattr(cfg, "telegram_chat_id", "") or os.getenv("TELEGRAM_CHAT_ID")
                ) else "Missing",
            },
            "dashboard_password": _secret_status(
                "DASHBOARD_PASSWORD", "CAREERPILOT_DASHBOARD_PASSWORD"),
        },
    }


def build_config_health(*, config, hub=None) -> dict[str, Any]:
    """Configuration health board (doctor-inspired, JSON for Mission Control)."""
    layout = get_layout()
    checks: list[dict[str, Any]] = []
    score_parts: list[tuple[str, float]] = []  # weight, earned fraction

    def add(group: str, name: str, status: str, message: str = "",
            weight: float = 1.0) -> None:
        checks.append({
            "group": group, "name": name, "status": status, "message": message})
        frac = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0, "SKIP": 0.75}.get(status, 0.5)
        score_parts.append((weight, frac * weight))

    cfg = config

    # Configuration
    if cfg is None:
        add("Configuration", "Config loaded", "FAIL", "no AppConfig bound", 8)
    else:
        add("Configuration", "Config loaded", "PASS",
            getattr(cfg, "source_path", ""), 8)
        env_path = layout.env_file
        if env_path.exists() or (layout.app_root / ".env").exists():
            add("Configuration", ".env loaded", "PASS", str(env_path), 6)
        else:
            add("Configuration", ".env loaded", "FAIL", "missing .env", 6)

    # Profiles / resumes
    engine = getattr(cfg, "profile_engine", None) if cfg else None
    if engine is None:
        add("Profiles", "Profiles found", "FAIL", "no profile engine", 7)
    else:
        rows = engine.summary_rows()
        add("Profiles", "Profiles found", "PASS" if rows else "FAIL",
            f"{len(rows)} profile(s)", 7)
        missing = [r["name"] for r in rows if not r["resume_ok"]]
        default = getattr(cfg, "default_career_profile", "")
        if missing:
            default_missing = default in missing
            add("Resumes", "Resume files",
                "FAIL" if default_missing else "WARN",
                f"missing: {', '.join(missing)}", 7)
        else:
            add("Resumes", "Resume files", "PASS",
                f"all {len(rows)} present", 7)
        no_kw = [r["name"] for r in rows if r["keyword_count"] == 0]
        add("Profiles", "Keywords",
            "WARN" if no_kw else "PASS",
            f"empty keywords: {', '.join(no_kw)}" if no_kw else "present", 2)

    # Browser
    if cfg is not None:
        sessions = _browser_session_status(cfg.browser.profiles_path)
        for portal, st in sessions["portals"].items():
            add("Browser", f"{portal.title()} session",
                "PASS" if st == "Present" else "WARN", st, 3)

    # AI
    if cfg is not None:
        ai = cfg.ai
        n_keys = len(getattr(ai, "gemini_keys", []) or [])
        provider_keys = 0
        for spec in getattr(ai, "providers", []) or []:
            if getattr(spec, "enabled", True) and getattr(spec, "api_keys", None):
                provider_keys += len(spec.api_keys)
            elif getattr(spec, "enabled", True) and not getattr(spec, "requires_auth", True):
                provider_keys += 1
        if n_keys or provider_keys:
            add("AI", "API keys", "PASS",
                f"gemini={n_keys} provider_keys={provider_keys}", 8)
        else:
            add("AI", "API keys", "FAIL", "no AI provider keys in .env", 8)
        add("AI", "Active provider", "PASS",
            getattr(ai, "active_provider", "") or "(none)", 2)
        if hub is not None and hub.ai is not None:
            try:
                ok = hub.ai.any_available()
                add("AI", "Provider reachable", "PASS" if ok else "WARN",
                    "at least one provider available" if ok else "none available",
                    4)
            except Exception as exc:  # noqa: BLE001
                add("AI", "Provider reachable", "WARN", str(exc), 4)

    # Database
    if cfg is not None:
        db_path = Path(cfg.database_path)
        if db_path.exists():
            add("Database", "Database file", "PASS", str(db_path), 5)
        else:
            add("Database", "Database file", "WARN",
                f"not created yet: {db_path}", 5)
        bdir = Path(cfg.backup_path)
        try:
            bdir.mkdir(parents=True, exist_ok=True)
            add("Database", "DB backups dir", "PASS", str(bdir), 2)
        except OSError as exc:
            add("Database", "DB backups dir", "FAIL", str(exc), 2)

    # Scheduler
    if hub is not None and hub.scheduler is not None:
        try:
            st = hub.scheduler.status() if hasattr(hub.scheduler, "status") else {}
            add("Scheduler", "Scheduler", "PASS",
                f"paused={getattr(hub, 'paused', False)} status={st}", 3)
        except Exception as exc:  # noqa: BLE001
            add("Scheduler", "Scheduler", "WARN", str(exc), 3)
    else:
        add("Scheduler", "Scheduler", "WARN", "not bound (dashboard-only?)", 3)

    # Storage
    try:
        usage = shutil.disk_usage(str(layout.data_root))
        free_gb = usage.free / (1024 ** 3)
        add("Storage", "Free disk", "PASS" if free_gb >= 5 else "FAIL",
            f"{free_gb:.1f} GB free", 5)
    except OSError as exc:
        add("Storage", "Free disk", "FAIL", str(exc), 5)

    # Telegram
    if cfg is not None:
        tok = bool(cfg.telegram_token)
        chat = bool(cfg.telegram_chat_id)
        if tok and chat:
            add("Telegram", "Telegram", "PASS", "token + chat configured", 2)
        elif tok or chat:
            add("Telegram", "Telegram", "WARN", "incomplete", 2)
        else:
            add("Telegram", "Telegram", "SKIP", "not configured", 2)

    # Doctor score (best-effort reuse of in-process doctor weights)
    total_w = sum(w for w, _ in score_parts) or 1.0
    earned = sum(e for _, e in score_parts)
    score = int(round(100 * earned / total_w))
    fails = sum(1 for c in checks if c["status"] == "FAIL")
    warns = sum(1 for c in checks if c["status"] == "WARN")
    if score >= 90:
        band = "PRODUCTION-READY"
    elif score >= 70:
        band = "DRY-RUN READY"
    elif score >= 40:
        band = "SETUP INCOMPLETE"
    else:
        band = "NOT READY"

    return {
        "generated_at": _utcnow(),
        "score": score,
        "band": band,
        "fails": fails,
        "warns": warns,
        "checks": checks,
        "data_root": str(layout.data_root),
        "app_root": str(layout.app_root),
    }

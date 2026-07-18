"""Ops dashboard JSON + control API."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..activity import FEED
from ..auth import get_csrf, require_csrf
from .. import queries
from ..runtime import HUB

router = APIRouter(prefix="/api", tags=["api"])


def _db():
    if HUB.db is None:
        return None
    return HUB.db


@router.get("/summary")
def api_summary():
    db = _db()
    cards = queries.summary_cards(db) if db else {}
    live = HUB.live_status()
    health = {}
    try:
        from ...core.health_snapshot import collect_health
        health = collect_health(config=HUB.config)
    except Exception as exc:  # noqa: BLE001
        health = {"error": str(exc)}
    sched = {}
    if HUB.scheduler is not None and hasattr(HUB.scheduler, "status"):
        try:
            sched = HUB.scheduler.status()
        except Exception as exc:  # noqa: BLE001
            sched = {"error": str(exc)}
    browser = {}
    if HUB.browser is not None and hasattr(HUB.browser, "status_snapshot"):
        try:
            browser = HUB.browser.status_snapshot()
        except Exception as exc:  # noqa: BLE001
            browser = {"error": str(exc)}
    browser.update(HUB.browser_restart_stats())
    preview = HUB.preview_meta()
    return {
        "phase": HUB.current_phase(),
        "paused": HUB.paused,
        "uptime_seconds": round(HUB.uptime_seconds, 1),
        "cards": cards,
        "live": live,
        "scheduler": sched,
        "browser": browser,
        "preview": preview,
        "health": health,
        "ai_runtime": HUB.ai_runtime_stats(),
        "alerts": FEED.alerts(20),
    }


@router.get("/activity")
def api_activity(limit: int = 100, after: str = ""):
    mem = FEED.recent(limit=limit, after_ts=after)
    if mem:
        return {"events": mem, "source": "memory"}
    db = _db()
    if db:
        return {"events": queries.activity_from_db(db, limit), "source": "db"}
    return {"events": [], "source": "none"}


@router.get("/jobs")
def api_jobs(
    portal: str = "",
    status: str = "",
    q: str = "",
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    today: bool = False,
    limit: int = 200,
    offset: int = 0,
):
    db = _db()
    if not db:
        return {"jobs": []}
    return {
        "jobs": queries.list_jobs(
            db, portal=portal, status=status, q=q, min_score=min_score,
            max_score=max_score, today_only=today, limit=limit, offset=offset),
    }


@router.get("/jobs/{job_id}")
def api_job_detail(job_id: int):
    db = _db()
    if not db:
        return JSONResponse({"error": "no database"}, status_code=503)
    data = queries.get_job(db, job_id)
    if not data:
        return JSONResponse({"error": "not found"}, status_code=404)
    return data


@router.get("/applications")
def api_applications(limit: int = 100):
    db = _db()
    return {"applications": queries.applications(db, limit) if db else []}


@router.get("/ai")
def api_ai():
    db = _db()
    out = queries.ai_summary(db) if db else {"by_provider": [], "today": {}, "recent": []}
    out["runtime"] = HUB.ai_runtime_stats()
    cfg = HUB.config
    out["active_provider"] = getattr(getattr(cfg, "ai", None), "active_provider", "") if cfg else ""
    out["secrets"] = {
        "gemini": "Configured" if (
            cfg and (getattr(cfg.ai, "gemini_keys", None) or [])
        ) else "Missing",
    }
    if cfg is not None:
        specs = []
        for spec in getattr(cfg.ai, "providers", []) or []:
            specs.append({
                "name": getattr(spec, "name", ""),
                "enabled": getattr(spec, "enabled", True),
                "kind": getattr(spec, "kind", ""),
                "preferred_model": getattr(spec, "preferred_model", "") or "",
                "discover_models": getattr(spec, "discover_models", True),
                "keys_status": "Configured" if getattr(spec, "api_keys", None)
                else ("Not required" if not getattr(spec, "requires_auth", True)
                      else "Missing"),
            })
        out["config_providers"] = specs
        out["timeout"] = cfg.ai.request_timeout
        out["max_retries"] = cfg.ai.max_retries
    if HUB.ai is not None:
        try:
            out["providers"] = [
                {"name": p.name, "available": p.is_available(),
                 "model": getattr(p, "model", "")}
                for p in getattr(HUB.ai, "providers", [])
            ]
            out["any_available"] = HUB.ai.any_available()
        except Exception as exc:  # noqa: BLE001
            out["providers_error"] = str(exc)
    return out


@router.get("/config/summary")
def api_config_summary():
    from ...core.config_views import build_config_summary
    if HUB.config is None:
        return JSONResponse({"error": "no config"}, status_code=503)
    return build_config_summary(config=HUB.config, hub=HUB)


@router.get("/config/health")
def api_config_health():
    from ...core.config_views import build_config_health
    if HUB.config is None:
        return JSONResponse({"error": "no config"}, status_code=503)
    return build_config_health(config=HUB.config, hub=HUB)


@router.get("/profiles")
def api_profiles():
    cfg = HUB.config
    if cfg is None or cfg.profile_engine is None:
        return {"profiles": []}
    rows = cfg.profile_engine.summary_rows()
    # Attach simple DB stats when available
    db = _db()
    stats: dict[str, dict] = {}
    if db is not None:
        try:
            conn = db.connect()
            # Prefer jobs.selected_resume / resume column if present.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            col = "selected_resume" if "selected_resume" in cols else (
                "career_profile" if "career_profile" in cols else None)
            if col:
                for row in conn.execute(
                    f"SELECT {col} AS profile, COUNT(*) AS n, "
                    f"AVG(match_score) AS avg_score "
                    f"FROM jobs WHERE {col} IS NOT NULL AND {col} != '' "
                    f"GROUP BY {col}"
                ).fetchall():
                    stats[str(row["profile"])] = {
                        "applications": row["n"],
                        "avg_score": round(float(row["avg_score"] or 0), 1),
                    }
        except Exception:  # noqa: BLE001
            pass
    for r in rows:
        r["stats"] = stats.get(r["name"], {"applications": 0, "avg_score": None})
    return {
        "default": cfg.default_career_profile,
        "current": HUB.last_profile_name,
        "profiles": rows,
    }


@router.get("/settings")
def api_settings():
    cfg = HUB.config
    if cfg is None:
        return {"error": "no config"}
    # Redact secrets — never expose API keys. Group for operator console.
    return {
        "read_only": True,
        "groups": {
            "General": {
                "apply_mode": cfg.apply.mode,
                "require_final_confirmation": cfg.apply.require_final_confirmation,
                "max_applications_per_day": cfg.apply.max_applications_per_day,
                "min_apply_score": cfg.ai.min_apply_score,
                "default_profile": cfg.default_career_profile,
                "scan_interval_hours": cfg.scan_interval_hours,
                "daily_summary_hour": cfg.daily_summary_hour,
            },
            "Advanced": {
                "easy_apply_only": cfg.apply.easy_apply_only,
                "ai_provider": cfg.ai.active_provider,
                "ai_timeout": cfg.ai.request_timeout,
                "ai_retries": cfg.ai.max_retries,
                "browser_channel": cfg.browser.channel,
                "browser_headless": cfg.browser.headless,
                "preferred_locations": cfg.rules.preferred_locations,
            },
            "Developer": {
                "browser_profiles": cfg.browser.profiles_path,
                "profiles_dir": cfg.profiles_dir,
                "database_path": cfg.database_path,
                "report_path": cfg.report_path,
                "log_path": cfg.log_path,
                "source_path": cfg.source_path,
                "data_root": cfg.data_root,
                "dashboard_host": cfg.dashboard_host,
                "dashboard_port": cfg.dashboard_port,
                "visual_mode": getattr(cfg.debug, "visual_mode", False),
            },
        },
        "telegram_configured": bool(cfg.telegram_token and cfg.telegram_chat_id),
        "note": "Settings are read-only in v1 freeze. Edit config.yaml / .env on disk, then restart.",
    }


@router.get("/logs/tail")
def api_log_tail(name: str = "application.log", lines: int = 200):
    cfg = HUB.config
    log_dir = Path(getattr(cfg, "log_path", "logs") if cfg else "logs")
    # only basename
    safe = Path(name).name
    return {"name": safe, "text": queries.tail_log(str(log_dir / safe), lines)}


@router.post("/control/{action}")
async def api_control(action: str, request: Request,
                      csrf_token: str = Form(None)):
    # Accept CSRF from form or header for HTMX/JSON clients.
    token = csrf_token or request.headers.get("X-CSRF-Token") or ""
    expected = request.session.get("csrf")
    if expected:
        import hmac
        if not token or not hmac.compare_digest(str(token), str(expected)):
            return JSONResponse({"error": "csrf"}, status_code=403)
    action = action.lower().strip()
    allowed = {
        "pause", "resume", "restart_browser", "doctor", "backup",
        "scan_now",
    }
    if action not in allowed:
        return JSONResponse({"error": f"unknown action {action}"}, status_code=400)
    if action == "pause":
        HUB.set_paused(True)
        FEED.push("Operator paused CareerPilot", level="warn", category="system")
        return {"ok": True, "paused": True}
    if action == "resume":
        HUB.set_paused(False)
        FEED.push("Operator resumed CareerPilot", level="success", category="system")
        return {"ok": True, "paused": False}
    HUB.enqueue(action)
    FEED.push(f"Control command queued: {action}", level="info", category="system")
    return {"ok": True, "queued": action, "csrf": get_csrf(request)}


@router.get("/browser")
def api_browser():
    data = {}
    if HUB.browser is not None and hasattr(HUB.browser, "status_snapshot"):
        data = HUB.browser.status_snapshot()
    data.update(HUB.browser_restart_stats())
    data["preview"] = HUB.preview_meta()
    data["live"] = HUB.live_status()
    return data


@router.get("/browser/preview.jpg")
@router.get("/browser/preview.png")
def api_browser_preview():
    meta = HUB.preview_meta()
    path = meta.get("path") or "logs/browser_preview.png"
    p = Path(path)
    if not p.exists():
        # 1x1 transparent PNG
        from fastapi.responses import Response
        return Response(content=_EMPTY_PNG, media_type="image/png")
    from fastapi.responses import FileResponse
    return FileResponse(p, media_type="image/png")


_EMPTY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@router.get("/scheduler")
def api_scheduler():
    if HUB.scheduler is not None and hasattr(HUB.scheduler, "status"):
        return HUB.scheduler.status()
    return {"running": False, "detail": "scheduler not bound"}


@router.get("/health")
def api_health():
    from ...core.health_snapshot import collect_health
    snap = collect_health(config=HUB.config)
    snap["phase"] = HUB.current_phase()
    snap["paused"] = HUB.paused
    snap["uptime_seconds"] = round(HUB.uptime_seconds, 1)
    return snap


@router.get("/reports/charts")
def api_charts():
    db = _db()
    return queries.reports_charts(db) if db else {}


@router.get("/reports/csv")
def api_csv_list():
    cfg = HUB.config
    root = getattr(cfg, "report_path", "reports") if cfg else "reports"
    return {"files": queries.list_csv_reports(root)}


@router.get("/reports/csv/preview")
def api_csv_preview(path: str = Query(...)):
    cfg = HUB.config
    root = Path(getattr(cfg, "report_path", "reports") if cfg else "reports").resolve()
    target = Path(path)
    if not target.is_absolute():
        target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return JSONResponse({"error": "path outside reports/"}, status_code=400)
    return queries.read_csv_preview(str(target))


@router.get("/reports/csv/export")
def api_csv_export(path: str = Query(...)):
    cfg = HUB.config
    root = Path(getattr(cfg, "report_path", "reports") if cfg else "reports").resolve()
    target = Path(path)
    if not target.is_absolute():
        target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return JSONResponse({"error": "path outside reports/"}, status_code=400)
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(target, filename=target.name, media_type="text/csv")


@router.get("/notifications")
def api_notifications(limit: int = 100):
    db = _db()
    return {
        "notifications": queries.notifications(db, limit) if db else [],
        "alerts": FEED.alerts(limit),
    }

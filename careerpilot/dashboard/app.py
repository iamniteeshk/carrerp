"""Jarvis-style Flask console.

The dashboard binds to the home LAN (``0.0.0.0``). Every page and API,
including status, requires ``DASHBOARD_USER`` / ``DASHBOARD_PASSWORD``.
Do not publish port 5000 on the public internet.
"""

from __future__ import annotations

import os
import secrets
from functools import wraps
from typing import Any, Callable

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)

from ..core.enums import JobStatus
from ..core.logging_setup import get_logger
from ..core.schedule_config import (DAY_NAMES, default_schedule, describe_schedule,
                                    schedule_from_dict)
from ..db.database import Database
from ..db.services import JobService, SettingsService

logger = get_logger(__name__)


def _dashboard_credentials() -> tuple[str, str]:
    user = (os.environ.get("DASHBOARD_USER") or "Admin").strip()
    password = (os.environ.get("DASHBOARD_PASSWORD") or "Adming").strip()
    return user, password


def create_dashboard(
    db: Database,
    refresh_seconds: int = 30,
    *,
    config: Any = None,
    settings: SettingsService | None = None,
    on_settings_change: Callable[[], None] | None = None,
    control: Any = None,
) -> Flask:
    app = Flask(__name__)
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("DASHBOARD_SECRET_KEY")
        or secrets.token_hex(32)
    )
    # Home LAN is plain HTTP. HttpOnly + SameSite stop casual cookie theft
    # from another site; Secure would break http:// on the local network.
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
    )
    jobs_svc = JobService(db)
    settings_svc = settings or SettingsService(db)

    def q(sql: str, params: tuple = ()) -> list[dict]:
        conn = db.connect()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def require_admin(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "admin login required"}), 401
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def _lan_login_required():
        if request.endpoint in ("login", "static"):
            return None
        if request.path.startswith("/static/"):
            return None
        if session.get("admin"):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "admin login required"}), 401
        nxt = request.path if request.path.startswith("/") else "/"
        return redirect(url_for("login", next=nxt))

    def _notify_change() -> None:
        if on_settings_change:
            try:
                on_settings_change()
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_settings_change failed: %s", exc)

    def _effective_schedule():
        override = settings_svc.get_json("schedule_json")
        if isinstance(override, dict) and override:
            return schedule_from_dict(override)
        if config is not None and getattr(config, "schedule", None) is not None:
            return config.schedule
        return default_schedule()

    @app.route("/")
    def home():
        return render_template(
            "index.html",
            refresh=refresh_seconds,
            is_admin=bool(session.get("admin")),
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = ""
        if request.method == "POST":
            user, password = _dashboard_credentials()
            got_user = (request.form.get("username") or "").strip()
            got_pass = request.form.get("password") or ""
            if secrets.compare_digest(got_user, user) and secrets.compare_digest(
                    got_pass, password):
                session["admin"] = True
                session.permanent = True
                nxt = request.args.get("next") or url_for("home")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = url_for("home")
                return redirect(nxt)
            error = "Invalid username or password"
            logger.warning("Dashboard admin login failed for user=%r", got_user)
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST", "GET"])
    def logout():
        session.pop("admin", None)
        return redirect(url_for("home"))

    @app.route("/api/me")
    def me():
        return jsonify({"admin": bool(session.get("admin"))})

    @app.route("/api/stats")
    def stats():
        conn = db.connect()
        by_status = {r["status"]: r["c"] for r in
                     conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
        applied = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE dry_run=0").fetchone()["c"]
        dry = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE dry_run=1").fetchone()["c"]
        failed = conn.execute("SELECT COUNT(*) c FROM failed_jobs").fetchone()["c"]
        from ..core.activity import read_activity
        activity = read_activity()
        bot_command = settings_svc.get("bot_command") or "running"
        evaluated = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE match_score IS NOT NULL"
        ).fetchone()["c"]
        waiting_approval = 0
        try:
            waiting_approval = conn.execute(
                "SELECT COUNT(*) c FROM pending_applications WHERE state='waiting'"
            ).fetchone()["c"]
        except Exception:  # noqa: BLE001 - migration not applied yet
            waiting_approval = 0
        telegram = "not configured"
        ai_provider = ""
        ai_model = ""
        if config is not None:
            token = getattr(config, "telegram_token", "") or ""
            chat = getattr(config, "telegram_chat_id", "") or ""
            telegram = "configured" if token and chat else "not configured"
            ai_provider = getattr(getattr(config, "ai", None), "active_provider", "") or ""
            ai_model = settings_svc.get("ai_text_model") or ""
            if not ai_model:
                for spec in getattr(getattr(config, "ai", None), "providers", []) or []:
                    if getattr(spec, "name", "") == ai_provider:
                        ai_model = getattr(spec, "preferred_model", "") or ""
        sessions = {"present": False, "linkedin": False, "naukri": False, "path": ""}
        if config is not None:
            root = __import__("pathlib").Path(
                getattr(getattr(config, "browser", None), "profiles_path",
                        "profiles_browser"))
            sessions = {
                "path": str(root),
                "present": root.exists(),
                "linkedin": (root / "linkedin").exists(),
                "naukri": (root / "naukri").exists(),
            }
        return jsonify({
            "by_status": by_status, "applications": applied,
            "dry_runs": dry, "failed": failed, "evaluated": evaluated,
            "waiting_approval": waiting_approval, "bot_command": bot_command,
            "telegram": telegram, "ai_provider": ai_provider, "ai_model": ai_model,
            "apply_mode": settings_svc.get("apply_mode") or (
                getattr(getattr(config, "apply", None), "mode", "dry_run")
                if config else "dry_run"),
            "activity": activity, "sessions": sessions,
        })

    @app.route("/api/control", methods=["POST"])
    @require_admin
    def control_bot():
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "").strip().lower()
        allowed = {"start", "stop", "pause", "resume", "scan_now"}
        if action not in allowed:
            return jsonify({"ok": False, "error": "unknown action"}), 400
        if action in ("start", "resume"):
            settings_svc.set("bot_command", "running")
        elif action == "pause":
            settings_svc.set("bot_command", "paused")
        elif action == "stop":
            settings_svc.set("bot_command", "stopped")
        if action == "scan_now" and control is not None:
            scheduler = getattr(control, "scheduler", None)
            if scheduler is not None and hasattr(scheduler, "request_scan"):
                try:
                    scheduler.request_scan()
                except Exception as exc:  # noqa: BLE001
                    return jsonify({"ok": False, "error": str(exc)}), 500
            else:
                return jsonify({
                    "ok": False,
                    "error": "scheduler is not running in this process",
                }), 409
        try:
            from ..core.activity import publish_activity
            publish_activity(activity=settings_svc.get("bot_command") or action,
                             stage=action)
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": True, "bot_command": settings_svc.get("bot_command")})

    @app.route("/api/emergency")
    def emergency():
        data = settings_svc.get_json("emergency_login") or {"active": False}
        return jsonify(data)

    @app.route("/api/emergency/clear", methods=["POST"])
    @require_admin
    def emergency_clear():
        cur = settings_svc.get_json("emergency_login") or {}
        cur["active"] = False
        cur["cleared_by"] = "admin"
        settings_svc.set_json("emergency_login", cur)
        return jsonify({"ok": True, "emergency": cur})

    @app.route("/api/jobs")
    def jobs():
        return jsonify(q("SELECT job_id, portal, company, job_title, location, "
                         "match_score, selected_resume, status, rejection_reason, "
                         "discovered_at FROM jobs ORDER BY discovered_at DESC LIMIT 200"))

    @app.route("/api/rejected")
    def rejected_jobs():
        rows = q(
            "SELECT job_id, portal, company, job_title, location, salary, "
            "experience, job_description, match_score, rejection_reason, "
            "job_url, status, discovered_at, updated_at "
            "FROM jobs WHERE status='REJECTED' "
            "ORDER BY updated_at DESC LIMIT 300"
        )
        return jsonify(rows)

    def _learn(action: str, row: dict) -> None:
        if config is None:
            return
        try:
            from pathlib import Path
            from ..core.decision_memory import DecisionMemory
            path = Path(config.database_path).parent / "decision_memory.json"
            DecisionMemory(path).record(
                action=action,
                job_title=row.get("job_title") or "",
                company=row.get("company") or "",
                portal=row.get("portal") or "",
                reason=row.get("rejection_reason") or "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store manual decision: %s", exc)

    @app.route("/api/review")
    def review_jobs():
        rows = q(
            "SELECT job_id, portal, company, job_title, location, salary, "
            "experience, job_description, match_score, rejection_reason, "
            "job_url, status, discovered_at, updated_at "
            "FROM jobs WHERE status IN ('CONFUSED', 'QUEUED', 'MANUAL_REVIEW') "
            "ORDER BY updated_at DESC LIMIT 300"
        )
        return jsonify(rows)

    @app.route("/api/jobs/<int:job_id>/approve", methods=["POST"])
    @require_admin
    def approve_job(job_id: int):
        updated = jobs_svc.approve(job_id)
        if updated is None:
            row = jobs_svc.get(job_id)
            if row is None:
                return jsonify({"ok": False, "error": "job not found"}), 404
            return jsonify({
                "ok": False,
                "error": (f"job status is {row.get('status')}; approve works for "
                          "rejected, confused, queued, or matched jobs"),
            }), 400
        _learn("apply", updated)
        try:
            from ..db.services import PendingApplicationService
            PendingApplicationService(db).set_state(job_id, "proceed", "dashboard apply")
        except Exception:  # noqa: BLE001
            pass
        logger.info("Dashboard manual approve job_id=%s title=%s",
                    job_id, updated.get("job_title"))
        return jsonify({"ok": True, "job": {
            "job_id": updated.get("job_id"),
            "job_title": updated.get("job_title"),
            "status": updated.get("status"),
            "rejection_reason": updated.get("rejection_reason"),
        }})

    @app.route("/api/jobs/<int:job_id>/reject", methods=["POST"])
    @require_admin
    def reject_job(job_id: int):
        body = request.get_json(silent=True) or {}
        reason = str(body.get("reason") or "manual reject")
        updated = jobs_svc.reject_manual(job_id, reason)
        if updated is None:
            row = jobs_svc.get(job_id)
            if row is None:
                return jsonify({"ok": False, "error": "job not found"}), 404
            return jsonify({
                "ok": False,
                "error": f"job status is {row.get('status')}; cannot reject from here",
            }), 400
        _learn("reject", updated)
        try:
            from ..db.services import PendingApplicationService
            PendingApplicationService(db).set_state(
                job_id, "done", "dashboard reject")
        except Exception:  # noqa: BLE001
            pass
        return jsonify({"ok": True, "job": {
            "job_id": updated.get("job_id"),
            "status": updated.get("status"),
            "rejection_reason": updated.get("rejection_reason"),
        }})

    @app.route("/api/applications")
    def applications():
        return jsonify(q("SELECT company, portal, resume_used, match_score, "
                         "application_status, dry_run, applied_at FROM applications "
                         "ORDER BY applied_at DESC LIMIT 200"))

    @app.route("/api/ai")
    def ai_usage():
        return jsonify(q("SELECT provider, COUNT(*) requests, SUM(tokens_used) tokens, "
                         "AVG(execution_time) avg_time, SUM(success) successes "
                         "FROM ai_history GROUP BY provider"))

    @app.route("/api/rejections")
    def rejections():
        return jsonify(q("SELECT rejection_reason, COUNT(*) c FROM jobs "
                         "WHERE status='REJECTED' GROUP BY rejection_reason "
                         "ORDER BY c DESC"))

    @app.route("/api/resume_usage")
    def resume_usage():
        return jsonify(q("SELECT resume_used, COUNT(*) c FROM applications "
                         "WHERE dry_run=0 GROUP BY resume_used ORDER BY c DESC"))

    @app.route("/api/portals")
    def portals():
        return jsonify(q("SELECT portal, COUNT(*) found FROM jobs GROUP BY portal"))

    # ---- Operator controls (Admin) --------------------------------------

    @app.route("/api/console/state")
    def console_state():
        sched = _effective_schedule()
        ai_active = settings_svc.get("ai_active_provider")
        if not ai_active and config is not None:
            ai_active = getattr(getattr(config, "ai", None), "active_provider", "")
        providers = []
        if config is not None:
            for p in getattr(getattr(config, "ai", None), "providers", []) or []:
                providers.append({
                    "name": getattr(p, "name", ""),
                    "enabled": bool(getattr(p, "enabled", True)),
                    "preferred_model": getattr(p, "preferred_model", ""),
                    "base_url": getattr(p, "base_url", ""),
                    "requires_auth": bool(getattr(p, "requires_auth", True)),
                })
        vision = getattr(config, "vision", None) if config is not None else None
        return jsonify({
            "admin": bool(session.get("admin")),
            "apply_mode": settings_svc.get("apply_mode") or (
                getattr(getattr(config, "apply", None), "mode", "dry_run")
                if config else "dry_run"),
            "apply_step_screenshots": (
                settings_svc.get("apply_step_screenshots")
                or str(bool(getattr(getattr(config, "apply", None),
                                    "step_screenshots", True))).lower()),
            "vision_login_enabled": (
                settings_svc.get("vision_login_enabled")
                or str(bool(getattr(vision, "login_check", True))).lower()),
            "vision_model": settings_svc.get("vision_model") or getattr(
                vision, "model", "qwen3-vl:8b"),
            "vision_base_url": settings_svc.get("vision_base_url") or getattr(
                vision, "base_url", "http://127.0.0.1:11434/v1"),
            "debug_visual_mode": (
                settings_svc.get("debug_visual_mode")
                or str(bool(getattr(getattr(config, "debug", None),
                                    "visual_mode", False))).lower()),
            "ai_active_provider": ai_active or "",
            "ai_text_model": settings_svc.get("ai_text_model") or "",
            "providers": providers,
            "schedule": sched.as_dict(),
            "schedule_lines": describe_schedule(sched),
            "day_names": list(DAY_NAMES),
            "emergency": settings_svc.get_json("emergency_login") or {"active": False},
        })

    @app.route("/api/console/ai", methods=["POST"])
    @require_admin
    def console_ai():
        body = request.get_json(silent=True) or {}
        if "active_provider" in body:
            settings_svc.set("ai_active_provider", str(body["active_provider"]).strip())
        if "text_model" in body:
            settings_svc.set("ai_text_model", str(body["text_model"]).strip())
        if "vision_login_enabled" in body:
            settings_svc.set("vision_login_enabled",
                             "true" if body["vision_login_enabled"] else "false")
        if "vision_model" in body:
            settings_svc.set("vision_model", str(body["vision_model"]).strip())
        if "vision_base_url" in body:
            settings_svc.set("vision_base_url", str(body["vision_base_url"]).strip())
        _notify_change()
        return jsonify({"ok": True})

    @app.route("/api/console/toggles", methods=["POST"])
    @require_admin
    def console_toggles():
        body = request.get_json(silent=True) or {}
        if "apply_step_screenshots" in body:
            settings_svc.set("apply_step_screenshots",
                             "true" if body["apply_step_screenshots"] else "false")
        if "debug_visual_mode" in body:
            settings_svc.set("debug_visual_mode",
                             "true" if body["debug_visual_mode"] else "false")
        if "apply_mode" in body:
            from ..apply.modes import canonical_apply_mode
            settings_svc.set("apply_mode", canonical_apply_mode(body["apply_mode"]))
        _notify_change()
        return jsonify({"ok": True})

    @app.route("/api/console/schedule", methods=["GET", "POST"])
    def console_schedule():
        if request.method == "GET":
            return jsonify(_effective_schedule().as_dict())
        if not session.get("admin"):
            return jsonify({"ok": False, "error": "admin login required"}), 401
        body = request.get_json(silent=True) or {}
        sched = schedule_from_dict(body)
        settings_svc.set_json("schedule_json", sched.as_dict())
        _notify_change()
        logger.info("Schedule updated via dashboard mode=%s", sched.mode)
        return jsonify({"ok": True, "schedule": sched.as_dict(),
                        "lines": describe_schedule(sched)})

    _ = JobStatus
    return app

"""Flask dashboard — public stats; Admin login required for edits.

Anyone on the LAN can view stats. Mutating actions (manual approve, etc.)
require ``DASHBOARD_USER`` / ``DASHBOARD_PASSWORD`` from the environment
(defaults: Admin / Adming for first boot — change these in ``.env``).
"""

from __future__ import annotations

import os
import secrets
from functools import wraps

from flask import (Flask, jsonify, redirect, render_template, request, session,
                   url_for)

from ..core.enums import JobStatus
from ..core.logging_setup import get_logger
from ..db.database import Database
from ..db.services import JobService

logger = get_logger(__name__)


def _dashboard_credentials() -> tuple[str, str]:
    user = (os.environ.get("DASHBOARD_USER") or "Admin").strip()
    password = (os.environ.get("DASHBOARD_PASSWORD") or "Adming").strip()
    return user, password


def create_dashboard(db: Database, refresh_seconds: int = 30) -> Flask:
    app = Flask(__name__)
    app.secret_key = (
        os.environ.get("FLASK_SECRET_KEY")
        or os.environ.get("DASHBOARD_SECRET_KEY")
        or secrets.token_hex(32)
    )
    jobs_svc = JobService(db)

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

    @app.route("/")
    def home():
        return render_template(
            "index.html",
            refresh=refresh_seconds,
            is_admin=bool(session.get("admin")),
            admin_user=_dashboard_credentials()[0],
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
        failed = conn.execute("SELECT COUNT(*) c FROM failed_jobs").fetchone()["c"]
        return jsonify({"by_status": by_status, "applications": applied,
                        "failed": failed})

    @app.route("/api/jobs")
    def jobs():
        return jsonify(q("SELECT job_id, portal, company, job_title, location, "
                         "match_score, selected_resume, status, rejection_reason, "
                         "discovered_at FROM jobs ORDER BY discovered_at DESC LIMIT 200"))

    @app.route("/api/rejected")
    def rejected_jobs():
        """Rejected jobs for the accordion UI (title + expandable details)."""
        rows = q(
            "SELECT job_id, portal, company, job_title, location, salary, "
            "experience, job_description, match_score, rejection_reason, "
            "job_url, status, discovered_at, updated_at "
            "FROM jobs WHERE status='REJECTED' "
            "ORDER BY updated_at DESC LIMIT 300"
        )
        return jsonify(rows)

    @app.route("/api/jobs/<int:job_id>/approve", methods=["POST"])
    @require_admin
    def approve_job(job_id: int):
        """Manual override: REJECTED → APPROVED (apply on next scan)."""
        updated = jobs_svc.approve(job_id)
        if updated is None:
            row = jobs_svc.get(job_id)
            if row is None:
                return jsonify({"ok": False, "error": "job not found"}), 404
            return jsonify({
                "ok": False,
                "error": f"job status is {row.get('status')}, only REJECTED can be approved",
            }), 400
        logger.info("Dashboard manual approve job_id=%s title=%s",
                    job_id, updated.get("job_title"))
        return jsonify({"ok": True, "job": {
            "job_id": updated.get("job_id"),
            "job_title": updated.get("job_title"),
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

    # Silence unused import warning for JobStatus (documented for readers).
    _ = JobStatus
    return app

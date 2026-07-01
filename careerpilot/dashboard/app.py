"""Read-only Flask dashboard (P012).

Displays state from SQLite. No business logic, no AI calls, no applying -- it
only reads and renders. Runs locally; no auth in V1.
"""

from __future__ import annotations

from flask import Flask, jsonify, render_template

from ..core.logging_setup import get_logger
from ..db.database import Database

logger = get_logger(__name__)


def create_dashboard(db: Database, refresh_seconds: int = 30) -> Flask:
    app = Flask(__name__)

    def q(sql: str, params: tuple = ()) -> list[dict]:
        conn = db.connect()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    @app.route("/")
    def home():
        return render_template("index.html", refresh=refresh_seconds)

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

    return app

"""Read models for the ops dashboard — all SQL stays here."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _q(db, sql: str, params: tuple = ()) -> list[dict]:
    conn = db.connect()
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _one(db, sql: str, params: tuple = ()) -> dict | None:
    rows = _q(db, sql, params)
    return rows[0] if rows else None


def today_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def summary_cards(db) -> dict[str, Any]:
    today = today_prefix()
    by_status = {r["status"]: r["c"] for r in _q(
        db, "SELECT status, COUNT(*) c FROM jobs GROUP BY status")}
    found_today = _one(
        db, "SELECT COUNT(*) c FROM jobs WHERE discovered_at LIKE ?",
        (f"{today}%",))
    scored = _one(
        db, "SELECT COUNT(*) c FROM jobs WHERE match_score IS NOT NULL "
            "AND discovered_at LIKE ?", (f"{today}%",))
    applied = _one(
        db, "SELECT COUNT(*) c FROM applications WHERE dry_run=0 "
            "AND applied_at LIKE ?", (f"{today}%",))
    rejected = _one(
        db, "SELECT COUNT(*) c FROM jobs WHERE status='REJECTED' "
            "AND discovered_at LIKE ?", (f"{today}%",))
    pending = sum(by_status.get(s, 0) for s in (
        "QUEUED", "PARTIAL_DATA", "APPLYING", "FOUND", "MATCHED", "MANUAL_REVIEW"))
    failed = _one(db, "SELECT COUNT(*) c FROM failed_jobs")
    ai_today = _one(
        db, "SELECT COUNT(*) c, COALESCE(SUM(tokens_used),0) tokens, "
            "COALESCE(AVG(execution_time),0) avg_t FROM ai_history "
            "WHERE created_at LIKE ?", (f"{today}%",))
    last_scan = _one(
        db, "SELECT started_at, finished_at, status, jobs_found, jobs_matched, "
            "jobs_applied FROM scan_history WHERE status != 'RUNNING' "
            "ORDER BY finished_at DESC LIMIT 1")
    return {
        "by_status": by_status,
        "jobs_found_today": (found_today or {}).get("c", 0),
        "jobs_scored_today": (scored or {}).get("c", 0),
        "jobs_applied_today": (applied or {}).get("c", 0),
        "jobs_rejected_today": (rejected or {}).get("c", 0),
        "jobs_pending": pending,
        "failed_jobs": (failed or {}).get("c", 0),
        "ai_requests_today": (ai_today or {}).get("c", 0),
        "ai_tokens_today": (ai_today or {}).get("tokens", 0),
        "ai_avg_latency_s": round(float((ai_today or {}).get("avg_t") or 0), 3),
        "last_scan": last_scan or {},
        "matched_total": by_status.get("MATCHED", 0) + by_status.get("APPLIED", 0),
        "applied_total": by_status.get("APPLIED", 0),
        "rejected_total": by_status.get("REJECTED", 0),
    }


def list_jobs(db, *, portal: str = "", status: str = "", q: str = "",
              min_score: float | None = None, max_score: float | None = None,
              today_only: bool = False, limit: int = 200, offset: int = 0) -> list[dict]:
    sql = [
        "SELECT job_id, portal, company, job_title, location, salary, experience,",
        "match_score, selected_resume, status, rejection_reason, job_url,",
        "discovered_at, updated_at, is_easy_apply FROM jobs WHERE 1=1",
    ]
    params: list[Any] = []
    if portal:
        sql.append("AND lower(portal)=lower(?)")
        params.append(portal)
    if status:
        sql.append("AND upper(status)=upper(?)")
        params.append(status)
    if today_only:
        sql.append("AND discovered_at LIKE ?")
        params.append(f"{today_prefix()}%")
    if q:
        sql.append("AND (company LIKE ? OR job_title LIKE ? OR location LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if min_score is not None:
        sql.append("AND match_score >= ?")
        params.append(min_score)
    if max_score is not None:
        sql.append("AND match_score <= ?")
        params.append(max_score)
    sql.append("ORDER BY discovered_at DESC LIMIT ? OFFSET ?")
    params.extend([int(limit), int(offset)])
    return _q(db, " ".join(sql), tuple(params))


def get_job(db, job_id: int) -> dict | None:
    job = _one(db, "SELECT * FROM jobs WHERE job_id=?", (job_id,))
    if not job:
        return None
    apps = _q(db, "SELECT * FROM applications WHERE job_id=? ORDER BY applied_at DESC",
              (job_id,))
    fails = _q(db, "SELECT * FROM failed_jobs WHERE job_id=? ORDER BY last_attempt DESC",
               (job_id,))
    ai = _q(db, "SELECT * FROM ai_history WHERE job_id=? ORDER BY created_at DESC",
            (job_id,))
    return {"job": job, "applications": apps, "failures": fails, "ai_history": ai}


def applications(db, limit: int = 100) -> list[dict]:
    return _q(
        db,
        "SELECT a.*, j.job_title, j.location, j.rejection_reason, j.job_url "
        "FROM applications a LEFT JOIN jobs j ON j.job_id=a.job_id "
        "ORDER BY a.applied_at DESC LIMIT ?",
        (limit,))


def rejections(db, limit: int = 50) -> list[dict]:
    return _q(
        db,
        "SELECT rejection_reason, COUNT(*) c FROM jobs "
        "WHERE status='REJECTED' AND rejection_reason IS NOT NULL "
        "AND rejection_reason != '' GROUP BY rejection_reason "
        "ORDER BY c DESC LIMIT ?",
        (limit,))


def ai_summary(db) -> dict[str, Any]:
    today = today_prefix()
    by_provider = _q(
        db,
        "SELECT provider, COUNT(*) requests, SUM(tokens_used) tokens, "
        "AVG(execution_time) avg_time, SUM(success) successes, "
        "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) failures "
        "FROM ai_history GROUP BY provider")
    today_row = _one(
        db,
        "SELECT COUNT(*) requests, COALESCE(SUM(tokens_used),0) tokens, "
        "COALESCE(AVG(execution_time),0) avg_time, "
        "SUM(success) successes, "
        "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) failures "
        "FROM ai_history WHERE created_at LIKE ?",
        (f"{today}%",))
    recent = _q(
        db,
        "SELECT provider, model, purpose, tokens_used, execution_time, success, "
        "created_at, job_id FROM ai_history ORDER BY created_at DESC LIMIT 50")
    return {
        "by_provider": by_provider,
        "today": today_row or {},
        "recent": recent,
    }


def reports_charts(db) -> dict[str, Any]:
    per_day = _q(
        db,
        "SELECT substr(discovered_at,1,10) day, COUNT(*) found, "
        "SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) rejected, "
        "SUM(CASE WHEN status IN ('MATCHED','APPLIED') THEN 1 ELSE 0 END) accepted "
        "FROM jobs WHERE discovered_at IS NOT NULL "
        "GROUP BY day ORDER BY day DESC LIMIT 30")
    portals = _q(
        db,
        "SELECT portal, COUNT(*) found, "
        "SUM(CASE WHEN status='APPLIED' THEN 1 ELSE 0 END) applied, "
        "SUM(CASE WHEN status='REJECTED' THEN 1 ELSE 0 END) rejected, "
        "AVG(match_score) avg_score FROM jobs GROUP BY portal")
    score_dist = _q(
        db,
        "SELECT CAST(match_score/10 AS INT)*10 bucket, COUNT(*) c "
        "FROM jobs WHERE match_score IS NOT NULL "
        "GROUP BY bucket ORDER BY bucket")
    companies = _q(
        db,
        "SELECT company, COUNT(*) c FROM applications WHERE dry_run=0 "
        "GROUP BY company ORDER BY c DESC LIMIT 15")
    return {
        "per_day": list(reversed(per_day)),
        "portals": portals,
        "score_dist": score_dist,
        "companies": companies,
        "rejections": rejections(db),
    }


def notifications(db, limit: int = 100) -> list[dict]:
    return _q(
        db,
        "SELECT * FROM notifications ORDER BY sent_at DESC LIMIT ?",
        (limit,))


def activity_from_db(db, limit: int = 100) -> list[dict]:
    try:
        return _q(
            db,
            "SELECT ts, level, category, message, detail, job_id, portal "
            "FROM activity_events ORDER BY id DESC LIMIT ?",
            (limit,))
    except Exception:  # noqa: BLE001
        return []


def list_csv_reports(report_dir: str) -> list[dict]:
    root = Path(report_dir)
    out = []
    if not root.exists():
        return out
    for path in sorted(root.rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            st = path.stat()
            out.append({
                "path": str(path),
                "name": str(path.relative_to(root)),
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
            })
        except OSError:
            continue
    return out[:200]


def read_csv_preview(path: str, max_rows: int = 200) -> dict[str, Any]:
    import csv
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".csv":
        return {"error": "not found", "headers": [], "rows": []}
    # Path traversal guard — must stay under reports/
    try:
        p.resolve().relative_to(Path("reports").resolve())
    except Exception:
        # also allow absolute under configured report dir via caller
        pass
    headers: list[str] = []
    rows: list[list[str]] = []
    with p.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        for i, row in enumerate(reader):
            if i == 0:
                headers = row
                continue
            rows.append(row)
            if len(rows) >= max_rows:
                break
    return {"headers": headers, "rows": rows, "path": str(p), "name": p.name}


def tail_log(path: str, lines: int = 200) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    try:
        data = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])
    except OSError as exc:
        return f"(error reading log: {exc})"

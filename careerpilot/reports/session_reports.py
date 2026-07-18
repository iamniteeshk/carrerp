"""Production session reports (always written, not debug-only).

Every scan produces:
  - summary report
  - portal report
  - application report
  - failure report
  - performance report
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger(__name__)


def write_session_reports(report_dir: str | Path, *, counts: dict,
                          duration: float, portals: list[str] | None = None,
                          ai_calls: int = 0, avg_score: float | None = None,
                          errors: int = 0, recoveries: int = 0,
                          run_log_lines: list[str] | None = None) -> dict[str, str]:
    """Write the five required session reports. Returns path map. Never raises."""
    out: dict[str, str] = {}
    try:
        root = Path(report_dir)
        sess = root / "sessions"
        sess.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        prefix = sess / f"session_{stamp}"

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": round(duration, 1),
            "jobs_found": counts.get("found", 0),
            "jobs_opened": (counts.get("found", 0) - counts.get("partial", 0)),
            "jobs_skipped": counts.get("skipped", 0),
            "jobs_rejected": counts.get("rejected", 0),
            "jobs_matched": counts.get("matched", 0),
            "jobs_applied": counts.get("applied", 0),
            "jobs_failed": counts.get("failed", 0),
            "jobs_queued": counts.get("queued", 0),
            "ai_calls": ai_calls,
            "average_score": avg_score,
            "errors": errors,
            "recoveries": recoveries,
            "portals": list(portals or []),
        }
        summary_path = Path(str(prefix) + "_summary.json")
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        out["summary"] = str(summary_path)

        # Portal report (CSV)
        portal_path = Path(str(prefix) + "_portal.csv")
        with portal_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "portal", "found", "rejected", "matched", "applied", "failed"])
            w.writeheader()
            for p in (portals or ["(all)"]):
                w.writerow({
                    "portal": p,
                    "found": counts.get("found", 0),
                    "rejected": counts.get("rejected", 0),
                    "matched": counts.get("matched", 0),
                    "applied": counts.get("applied", 0),
                    "failed": counts.get("failed", 0),
                })
        out["portal"] = str(portal_path)

        # Application report
        app_path = Path(str(prefix) + "_applications.json")
        app_path.write_text(json.dumps({
            "applied": counts.get("applied", 0),
            "matched_ready": counts.get("matched", 0),
            "queued_for_approval": counts.get("queued", 0),
            "mode_note": "See AppliedJobs.csv / jobs_applied.csv for row detail",
        }, indent=2), encoding="utf-8")
        out["applications"] = str(app_path)

        # Failure report
        fail_path = Path(str(prefix) + "_failures.json")
        fail_path.write_text(json.dumps({
            "failed": counts.get("failed", 0),
            "partial": counts.get("partial", 0),
            "errors": errors,
            "recoveries": recoveries,
            "note": "See FailedJobs.csv / failed_jobs.csv for row detail",
        }, indent=2), encoding="utf-8")
        out["failures"] = str(fail_path)

        # Performance report
        perf_path = Path(str(prefix) + "_performance.json")
        jobs_decided = (counts.get("rejected", 0) + counts.get("matched", 0)
                        + counts.get("failed", 0))
        perf_path.write_text(json.dumps({
            "runtime_seconds": round(duration, 1),
            "jobs_processed": counts.get("found", 0),
            "jobs_terminal": jobs_decided,
            "ai_calls": ai_calls,
            "average_score": avg_score,
            "jobs_per_minute": (round(counts.get("found", 0) / (duration / 60), 2)
                                if duration > 0 else 0),
            "stage_trace_lines": len(run_log_lines or []),
        }, indent=2), encoding="utf-8")
        out["performance"] = str(perf_path)

        logger.info("Session reports written under %s", sess)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Session report write failed: %s", exc)
    return out

#!/usr/bin/env python3
"""Ops dashboard smoke tests (no live browser / no network UI)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} {detail}")
        failed += 1


def main() -> int:
    print("=== ops dashboard ===")
    # Package importable
    from careerpilot.ops_dashboard import create_ops_dashboard
    from careerpilot.ops_dashboard.activity import FEED, emit
    from careerpilot.ops_dashboard.runtime import HUB, RuntimeHub
    from careerpilot.ops_dashboard import queries
    from careerpilot.db.database import Database

    check("create_ops_dashboard import", callable(create_ops_dashboard))
    check("templates exist", (ROOT / "careerpilot/ops_dashboard/templates/mission.html").exists())
    check("static css exists", (ROOT / "careerpilot/ops_dashboard/static/css/ops.css").exists())
    check("docs exist", (ROOT / "docs/OPS_DASHBOARD.md").exists())

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "t.db"
        db = Database(db_path)
        db.initialize()
        # migration v4
        row = db.connect().execute(
            "SELECT name FROM sqlite_master WHERE name='activity_events'").fetchone()
        check("activity_events migration", row is not None)

        FEED.bind_db(db)
        emit("test event", level="info", category="system")
        check("activity feed memory", len(FEED.recent(5)) >= 1)
        rows = queries.activity_from_db(db, 5)
        check("activity feed persisted", len(rows) >= 1)

        HUB.bind(config=None, db=db)
        cards = queries.summary_cards(db)
        check("summary cards keys", "jobs_found_today" in cards)

        # App factory (loopback, no password)
        os.environ.pop("DASHBOARD_PASSWORD", None)
        app = create_ops_dashboard(db=db, host="127.0.0.1", port=18006, password="")
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.get("/healthz")
        check("healthz 200", r.status_code == 200, str(r.status_code))
        r = client.get("/api/summary")
        check("api summary 200", r.status_code == 200, str(r.status_code))
        data = r.json()
        check("summary has phase", "phase" in data)
        r = client.get("/")
        check("mission page 200", r.status_code == 200, str(r.status_code))
        check("mission mentions Mission", b"Mission" in r.content)
        r = client.get("/jobs")
        check("jobs page 200", r.status_code == 200, str(r.status_code))
        r = client.get("/api/jobs")
        check("api jobs 200", r.status_code == 200, str(r.status_code))
        r = client.get("/api/health")
        check("api health 200", r.status_code == 200, str(r.status_code))
        # WebSocket live feed
        try:
            with client.websocket_connect("/ws/live") as ws:
                msg = ws.receive_json()
            check("websocket live tick", msg.get("type") == "tick", str(msg)[:120])
        except Exception as exc:  # noqa: BLE001
            check("websocket live tick", False, str(exc))

        # Auth required for LAN password
        app2 = create_ops_dashboard(db=db, host="0.0.0.0", port=18007,
                                    password="secret-test")
        c2 = TestClient(app2)
        r = c2.get("/api/summary")
        check("api unauthorized without login", r.status_code in (401, 303), str(r.status_code))
        r = c2.post("/login", data={"password": "secret-test", "next": "/"},
                    follow_redirects=False)
        check("login redirects", r.status_code in (303, 302), str(r.status_code))

        # Scheduler status method
        from careerpilot.core.scheduler import Scheduler
        check("Scheduler.status exists", hasattr(Scheduler, "status"))
        from careerpilot.browser.session import BrowserManager, BrowserConfig
        bm = BrowserManager(BrowserConfig())
        snap = bm.status_snapshot()
        check("browser snapshot no launch", snap.get("playwright_started") is False)
        check("browser snapshot portals empty", snap.get("portals") == {})

        # Runtime hub pause
        hub = RuntimeHub()
        hub.set_paused(True)
        check("pause flag", hub.paused is True)
        hub.enqueue("backup")
        cmds = hub.drain_commands()
        check("control queue", len(cmds) == 1 and cmds[0].action == "backup")

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

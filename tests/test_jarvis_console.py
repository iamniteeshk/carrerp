"""Schedule batches/fixed, vision parse, settings, Jarvis console APIs."""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from random import Random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.ai.vision import _parse_json_reply
from careerpilot.core.schedule_config import (active_batch, default_schedule,
                                              plan_from_schedule,
                                              schedule_from_dict)
from careerpilot.dashboard.app import create_dashboard
from careerpilot.db.database import Database
from careerpilot.db.services import SettingsService


def test_default_morning_batch_two_hours():
    s = default_schedule()
    assert s.mode == "batches"
    assert s.daily_max_minutes <= 240
    # Light random windows — not multi-hour stacks by default
    assert s.batches["morning"].duration_max <= 60
    assert s.batches["evening"].duration_max <= 60
    assert s.batches["night"].duration_max <= 120
    assert s.batches["morning"].run_probability < 0.6


def test_active_batch_by_clock():
    s = default_schedule()
    now = datetime(2026, 8, 10, 8, 0)  # Monday morning
    b = active_batch(s, now)
    assert b is not None and b.name == "morning"
    now2 = datetime(2026, 8, 10, 18, 30)
    assert active_batch(s, now2).name == "evening"
    now_night = datetime(2026, 8, 10, 21, 0)
    assert active_batch(s, now_night).name == "night"
    now3 = datetime(2026, 8, 10, 3, 0)
    assert active_batch(s, now3) is None


def test_plan_from_schedule_batches():
    s = default_schedule()
    s.skip_probability = 0.0
    s.batches["morning"].run_probability = 1.0
    plan = plan_from_schedule(s, datetime(2026, 8, 10, 8, 0), Random(1),
                              keywords=["Director"])
    assert plan.skip_today is False
    assert plan.window == "morning"
    assert 20 <= plan.duration_minutes <= 45
    assert "LinkedIn" in plan.portals


def test_morning_sometime_can_skip():
    s = default_schedule()
    s.skip_probability = 0.0
    s.batches["morning"].run_probability = 0.0  # never
    plan = plan_from_schedule(s, datetime(2026, 8, 10, 8, 0), Random(0),
                              keywords=["Director"])
    assert plan.skip_today is True
    assert plan.window == "morning_skipped"


def test_night_random_duration_2_to_3_hours():
    s = default_schedule()
    s.skip_probability = 0.0
    s.batches["night"].run_probability = 1.0
    plan = plan_from_schedule(s, datetime(2026, 8, 10, 21, 0), Random(7),
                              keywords=["Head"], used_minutes_today=0)
    assert plan.window == "night"
    assert 40 <= plan.duration_minutes <= 110
    assert set(plan.portals) == {"LinkedIn", "Naukri"}


def test_daily_budget_caps_total_at_4h():
    from careerpilot.core.schedule_config import day_budget_minutes, minutes_used_today
    s = default_schedule()
    s.skip_probability = 0.0
    s.daily_min_minutes = 180
    s.daily_max_minutes = 240
    now = datetime(2026, 8, 10, 21, 0)
    budget = day_budget_minutes(s, now)
    assert 180 <= budget <= 240
    s.batches["night"].run_probability = 1.0
    # Already used almost all of today's budget → skip
    plan = plan_from_schedule(s, now, Random(1), keywords=["X"],
                              used_minutes_today=budget - 5)
    assert plan.skip_today is True
    assert plan.window == "daily_budget_spent"
    # History helper
    used = minutes_used_today([
        {"start": "2026-08-10T08:00:00", "planned_duration_minutes": 40},
        {"start": "2026-08-10T18:00:00", "planned_duration_minutes": 35},
        {"start": "2026-08-09T21:00:00", "planned_duration_minutes": 99},
    ], now)
    assert used == 75


def test_fixed_slot_plan():
    raw = {
        "mode": "fixed",
        "enabled_days": ["mon", "tue", "wed", "thu", "fri"],
        "fixed": [{
            "enabled": True, "days": ["mon"], "start": "09:00", "end": "11:00",
            "duration_minutes": 90, "portals": ["Naukri"], "max_jobs": 12,
        }],
        "batches": {},
    }
    s = schedule_from_dict(raw)
    plan = plan_from_schedule(s, datetime(2026, 8, 10, 10, 0), Random(0),
                              keywords=["Head"])
    assert plan.window == "fixed"
    assert plan.duration_minutes == 90
    assert plan.portals == ["Naukri"]


def test_vision_json_parse():
    data = _parse_json_reply('{"logged_in": true, "reason": "feed visible"}')
    assert data["logged_in"] is True
    data2 = _parse_json_reply('```json\n{"logged_in": false, "reason": "login"}\n```')
    assert data2["logged_in"] is False


def test_settings_and_console_schedule():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        settings = SettingsService(db)
        app = create_dashboard(db, refresh_seconds=5, settings=settings)
        client = app.test_client()
        r = client.get("/api/console/state")
        assert r.status_code == 200
        assert "schedule" in r.get_json()
        # Admin login
        os.environ["DASHBOARD_USER"] = "Admin"
        os.environ["DASHBOARD_PASSWORD"] = "Adming"
        client.post("/login", data={"username": "Admin", "password": "Adming"})
        body = default_schedule().as_dict()
        body["batches"]["morning"]["duration_minutes"] = 90
        r = client.post("/api/console/schedule", json=body)
        assert r.status_code == 200 and r.get_json()["ok"]
        stored = settings.get_json("schedule_json")
        assert stored["batches"]["morning"]["duration_minutes"] == 90
        r = client.post("/api/console/ai", json={
            "active_provider": "ollama", "text_model": "qwen2.5:8b",
            "vision_login_enabled": True, "vision_model": "qwen2-vl:7b",
        })
        assert r.status_code == 200
        assert settings.get("ai_active_provider") == "ollama"
        r = client.post("/api/console/toggles", json={
            "apply_step_screenshots": True, "apply_mode": "dry_run",
        })
        assert r.status_code == 200
        assert settings.get("apply_mode") == "dry_run"
        db.close()


def test_emergency_banner_api():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        settings = SettingsService(db)
        settings.set_json("emergency_login", {
            "active": True, "portal": "LinkedIn", "reason": "logged out",
        })
        app = create_dashboard(db, settings=settings)
        client = app.test_client()
        r = client.get("/api/emergency").get_json()
        assert r["active"] is True
        os.environ["DASHBOARD_USER"] = "Admin"
        os.environ["DASHBOARD_PASSWORD"] = "Adming"
        client.post("/login", data={"username": "Admin", "password": "Adming"})
        assert client.post("/api/emergency/clear").status_code == 200
        assert settings.get_json("emergency_login")["active"] is False
        db.close()


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL  {t.__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

"""Operator-configurable scan schedule (batches, fixed windows, per-day).

Modes
-----
* ``batches`` — named morning/evening/night windows (default). Durations can be
  fixed or randomized between ``duration_min`` / ``duration_max``. Per-batch
  ``run_probability`` lets a window fire only “sometimes”.
  A **daily budget** (default random 1–4h, hard cap 4h) limits total scan time
  across all windows in a calendar day.
* ``fixed`` — explicit day + start/end slots (still respects daily budget)
* ``human_random`` — legacy randomized plan_daily_session behaviour

Dashboard edits persist via SettingsService (``schedule_json``) and override the
YAML defaults for the next scan.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from random import Random
from typing import Any

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class BatchWindow:
    name: str
    enabled: bool = True
    start: str = "08:00"          # HH:MM local
    end: str = "10:00"            # HH:MM local (inclusive window for matching)
    duration_minutes: int = 40    # used when min/max not set
    # When both set, each run picks a random duration in [min, max].
    duration_min: int | None = None
    duration_max: int | None = None
    # 1.0 = always run when clock is in window; lower = “sometimes”.
    run_probability: float = 1.0
    portals: list[str] = field(default_factory=lambda: ["LinkedIn", "Naukri"])
    max_jobs: int = 40
    max_jobs_min: int | None = None
    max_jobs_max: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    def pick_duration(self, rng) -> int:
        lo = self.duration_min
        hi = self.duration_max
        if lo is not None and hi is not None:
            a, b = int(lo), int(hi)
            if a > b:
                a, b = b, a
            return max(1, rng.randint(a, b))
        return max(1, int(self.duration_minutes or 40))

    def pick_max_jobs(self, rng) -> int:
        lo = self.max_jobs_min
        hi = self.max_jobs_max
        if lo is not None and hi is not None:
            a, b = int(lo), int(hi)
            if a > b:
                a, b = b, a
            return max(1, rng.randint(a, b))
        return max(1, int(self.max_jobs or 40))


@dataclass
class FixedSlot:
    days: list[str] = field(default_factory=lambda: list(DAY_NAMES[:5]))
    start: str = "09:00"
    end: str = "11:00"
    duration_minutes: int = 120
    portals: list[str] = field(default_factory=lambda: ["LinkedIn", "Naukri"])
    max_jobs: int = 50
    enabled: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScheduleConfig:
    mode: str = "batches"  # batches | fixed | human_random
    enabled_days: list[str] = field(default_factory=lambda: list(DAY_NAMES))
    skip_probability: float = 0.08
    # Hard daily cap: app never plans more than this many minutes per calendar day.
    daily_max_minutes: int = 240          # 4 hours
    # Each day picks a random target budget in [daily_min, daily_max].
    daily_min_minutes: int = 60           # 1 hour floor for a “light” day
    batches: dict[str, BatchWindow] = field(default_factory=dict)
    fixed: list[FixedSlot] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "enabled_days": list(self.enabled_days),
            "skip_probability": self.skip_probability,
            "daily_min_minutes": self.daily_min_minutes,
            "daily_max_minutes": self.daily_max_minutes,
            "batches": {k: v.as_dict() for k, v in self.batches.items()},
            "fixed": [f.as_dict() for f in self.fixed],
        }


def _parse_hhmm(text: str) -> int:
    """Return minutes since midnight for 'HH:MM' (tolerant of 'H:MM')."""
    parts = (text or "0:0").strip().split(":")
    h = int(parts[0] or 0)
    m = int(parts[1] or 0) if len(parts) > 1 else 0
    return max(0, min(24 * 60 - 1, h * 60 + m))


def _day_key(weekday: int) -> str:
    return DAY_NAMES[weekday % 7]


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def default_schedule() -> ScheduleConfig:
    """Default: totally random light sessions, max 3–4h/day total.

    Individual windows are short and often skipped; a daily budget (random
    1–4h, hard-capped at 4h) stops the day from stacking into a marathon.
    """
    return ScheduleConfig(
        mode="batches",
        enabled_days=list(DAY_NAMES),
        skip_probability=0.10,            # occasional full day off
        daily_min_minutes=60,             # light day ~1h
        daily_max_minutes=240,            # never more than 4h planned
        batches={
            "morning": BatchWindow(
                name="morning", enabled=True,
                start="07:00", end="10:00",
                duration_minutes=30,
                duration_min=20, duration_max=45,
                run_probability=0.40,          # often skip morning
                portals=["LinkedIn"],
                max_jobs=20, max_jobs_min=8, max_jobs_max=25),
            "evening": BatchWindow(
                name="evening", enabled=True,
                start="17:30", end="19:30",
                duration_minutes=35,
                duration_min=25, duration_max=45,
                run_probability=0.45,
                portals=["Naukri"],
                max_jobs=25, max_jobs_min=10, max_jobs_max=30),
            "night": BatchWindow(
                name="night", enabled=True,
                start="20:00", end="23:00",
                duration_minutes=75,
                duration_min=40, duration_max=110,  # chunk of the daily budget
                run_probability=0.50,
                portals=["LinkedIn", "Naukri"],
                max_jobs=50, max_jobs_min=20, max_jobs_max=70),
            "lunch": BatchWindow(
                name="lunch", enabled=False,
                start="12:00", end="13:30",
                duration_minutes=30,
                duration_min=20, duration_max=40,
                run_probability=0.35,
                portals=["Naukri"],
                max_jobs=20),
        },
        fixed=[
            FixedSlot(days=list(DAY_NAMES[:5]), start="09:00", end="11:00",
                      duration_minutes=90, portals=["LinkedIn", "Naukri"],
                      max_jobs=40, enabled=False),
        ],
    )


def schedule_from_dict(raw: dict | None) -> ScheduleConfig:
    if not raw:
        return default_schedule()
    base = default_schedule()
    mode = str(raw.get("mode") or base.mode).strip().lower()
    if mode not in ("batches", "fixed", "human_random"):
        mode = "batches"
    days = [str(d).strip().lower()[:3] for d in (raw.get("enabled_days") or base.enabled_days)]
    days = [d for d in days if d in DAY_NAMES] or list(DAY_NAMES)

    batches: dict[str, BatchWindow] = {}
    src_batches = raw.get("batches") or {}
    if isinstance(src_batches, dict):
        for name, b in src_batches.items():
            b = b or {}
            batches[str(name)] = BatchWindow(
                name=str(name),
                enabled=bool(b.get("enabled", True)),
                start=str(b.get("start", "08:00")),
                end=str(b.get("end", "10:00")),
                duration_minutes=int(b.get("duration_minutes", 40) or 40),
                duration_min=_opt_int(b.get("duration_min")),
                duration_max=_opt_int(b.get("duration_max")),
                run_probability=float(b["run_probability"])
                if "run_probability" in b and b.get("run_probability") is not None
                else 1.0,
                portals=list(b.get("portals") or ["LinkedIn", "Naukri"]),
                max_jobs=int(b.get("max_jobs", 40) or 40),
                max_jobs_min=_opt_int(b.get("max_jobs_min")),
                max_jobs_max=_opt_int(b.get("max_jobs_max")),
            )
    if not batches:
        batches = base.batches

    fixed: list[FixedSlot] = []
    for item in (raw.get("fixed") or []):
        item = item or {}
        fdays = [str(d).strip().lower()[:3] for d in (item.get("days") or DAY_NAMES[:5])]
        fixed.append(FixedSlot(
            days=[d for d in fdays if d in DAY_NAMES] or list(DAY_NAMES[:5]),
            start=str(item.get("start", "09:00")),
            end=str(item.get("end", "11:00")),
            duration_minutes=int(item.get("duration_minutes", 120) or 120),
            portals=list(item.get("portals") or ["LinkedIn", "Naukri"]),
            max_jobs=int(item.get("max_jobs", 50) or 50),
            enabled=bool(item.get("enabled", True)),
        ))

    dmin = int(raw.get("daily_min_minutes", base.daily_min_minutes) or base.daily_min_minutes)
    dmax = int(raw.get("daily_max_minutes", base.daily_max_minutes) or base.daily_max_minutes)
    if dmin > dmax:
        dmin, dmax = dmax, dmin
    dmax = max(30, min(240, dmax))   # hard product cap: 4 hours
    dmin = max(15, min(dmin, dmax))

    return ScheduleConfig(
        mode=mode,
        enabled_days=days,
        skip_probability=float(raw.get("skip_probability", base.skip_probability)
                               or 0.0),
        daily_min_minutes=dmin,
        daily_max_minutes=dmax,
        batches=batches,
        fixed=fixed,
    )


def active_batch(schedule: ScheduleConfig, now: datetime) -> BatchWindow | None:
    """Return the enabled batch whose [start, end] contains ``now``, if any."""
    if _day_key(now.weekday()) not in schedule.enabled_days:
        return None
    minutes = now.hour * 60 + now.minute
    for name in ("morning", "lunch", "afternoon", "evening", "night"):
        b = schedule.batches.get(name)
        if b and b.enabled:
            if _parse_hhmm(b.start) <= minutes <= _parse_hhmm(b.end):
                return b
    for name, b in schedule.batches.items():
        if name in ("morning", "lunch", "afternoon", "evening", "night"):
            continue
        if b.enabled and _parse_hhmm(b.start) <= minutes <= _parse_hhmm(b.end):
            return b
    return None


def active_fixed_slot(schedule: ScheduleConfig, now: datetime) -> FixedSlot | None:
    day = _day_key(now.weekday())
    if day not in schedule.enabled_days:
        return None
    minutes = now.hour * 60 + now.minute
    for slot in schedule.fixed:
        if not slot.enabled:
            continue
        if day not in slot.days:
            continue
        if _parse_hhmm(slot.start) <= minutes <= _parse_hhmm(slot.end):
            return slot
    return None


def day_budget_minutes(schedule: ScheduleConfig, now: datetime) -> int:
    """Stable random daily budget for this calendar day (within min/max, ≤4h)."""
    dmin = int(getattr(schedule, "daily_min_minutes", 60) or 60)
    dmax = int(getattr(schedule, "daily_max_minutes", 240) or 240)
    dmax = max(30, min(240, dmax))
    dmin = max(15, min(dmin, dmax))
    # Seed by date so every scan the same day shares one budget.
    seed = int(now.strftime("%Y%m%d")) ^ (dmin * 1009) ^ (dmax * 9176)
    return Random(seed).randint(dmin, dmax)


def minutes_used_today(history_entries: list[dict] | None, now: datetime) -> int:
    """Sum planned/runtime minutes already consumed today from session history."""
    if not history_entries:
        return 0
    day = now.strftime("%Y-%m-%d")
    total = 0
    for entry in history_entries:
        stamp = str(entry.get("start") or entry.get("date") or "")
        if not stamp.startswith(day):
            # Also accept local dates embedded as YYYY-MM-DD anywhere early
            if day not in stamp[:16]:
                continue
        planned = entry.get("planned_duration_minutes")
        if planned is not None:
            try:
                total += max(0, int(planned))
                continue
            except (TypeError, ValueError):
                pass
        runtime = entry.get("runtime_seconds")
        if runtime is not None:
            try:
                total += max(0, int(round(float(runtime) / 60.0)))
            except (TypeError, ValueError):
                pass
    return total


def plan_from_schedule(schedule: ScheduleConfig, now: datetime, rng,
                       keywords: list[str] | None = None,
                       *, used_minutes_today: int = 0):
    """Build a SessionPlan from operator schedule (batches/fixed) or legacy random.

    ``used_minutes_today`` comes from session history so the daily 3–4h budget
    is enforced across morning + evening + night runs.
    """
    from .learning import SessionPlan, plan_daily_session

    kw = list(keywords or [])
    if schedule.mode == "human_random":
        return plan_daily_session(
            rng, now, kw, skip_probability=float(schedule.skip_probability or 0.12))

    day = _day_key(now.weekday())
    is_weekend = now.weekday() >= 5
    if day not in schedule.enabled_days:
        return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])

    if schedule.skip_probability and rng.random() < schedule.skip_probability:
        return SessionPlan(skip_today=True, window="skipped", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])

    budget = day_budget_minutes(schedule, now)
    remaining = budget - max(0, int(used_minutes_today or 0))
    if remaining < 15:
        return SessionPlan(skip_today=True, window="daily_budget_spent",
                           duration_minutes=0, max_jobs=0,
                           is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])

    if schedule.mode == "fixed":
        slot = active_fixed_slot(schedule, now)
        if slot is None:
            return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                               max_jobs=0, is_weekend=is_weekend, keywords=kw,
                               portals=[], idle_gaps=[])
        portals = list(slot.portals)
        gaps = [rng.randint(5, 12)] if len(portals) > 1 else []
        duration = min(max(1, int(slot.duration_minutes)), remaining)
        return SessionPlan(
            skip_today=False, window="fixed",
            duration_minutes=duration,
            max_jobs=max(1, int(slot.max_jobs)),
            is_weekend=is_weekend, keywords=kw, portals=portals, idle_gaps=gaps)

    # batches (default) — random window + duration, clipped by remaining budget
    batch = active_batch(schedule, now)
    if batch is None:
        return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    raw_prob = getattr(batch, "run_probability", 1.0)
    prob = 1.0 if raw_prob is None else float(raw_prob)
    if prob < 1.0 and rng.random() > prob:
        return SessionPlan(skip_today=True, window=f"{batch.name}_skipped",
                           duration_minutes=0, max_jobs=0,
                           is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    portals = list(batch.portals)
    gaps = [rng.randint(5, 12)] if len(portals) > 1 else []
    duration = min(batch.pick_duration(rng), remaining)
    return SessionPlan(
        skip_today=False, window=batch.name,
        duration_minutes=duration,
        max_jobs=batch.pick_max_jobs(rng),
        is_weekend=is_weekend, keywords=kw, portals=portals, idle_gaps=gaps)


def describe_schedule(schedule: ScheduleConfig) -> list[str]:
    """Human-readable lines for the dashboard HUD."""
    lines = [
        f"Mode: {schedule.mode}",
        f"Days: {', '.join(schedule.enabled_days)}",
        f"Daily budget: {schedule.daily_min_minutes}-{schedule.daily_max_minutes}m "
        f"random (hard cap {min(240, schedule.daily_max_minutes)}m / 4h)",
    ]
    if schedule.mode == "batches":
        for name, b in schedule.batches.items():
            flag = "ON" if b.enabled else "off"
            if b.duration_min is not None and b.duration_max is not None:
                dur = f"{b.duration_min}-{b.duration_max}m random"
            else:
                dur = f"{b.duration_minutes}m"
            sometime = ""
            if float(b.run_probability if b.run_probability is not None else 1) < 1:
                sometime = f" sometime≈{int(float(b.run_probability)*100)}%"
            lines.append(
                f"{name}: {flag} {b.start}-{b.end} / {dur}{sometime} "
                f"portals={','.join(b.portals)} max={b.max_jobs}")
    elif schedule.mode == "fixed":
        for i, s in enumerate(schedule.fixed):
            flag = "ON" if s.enabled else "off"
            lines.append(
                f"slot{i+1}: {flag} {','.join(s.days)} {s.start}-{s.end} "
                f"{s.duration_minutes}m")
    elif schedule.mode == "human_random":
        lines.append("Legacy random windows (morning short / lunch / evening)")
    return lines

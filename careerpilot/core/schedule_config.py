"""Operator-configurable scan schedule (batches, fixed windows, per-day).

Modes
-----
* ``batches`` — named morning/evening/night windows (default). Durations can be
  fixed or randomized between ``duration_min`` / ``duration_max``. Per-batch
  ``run_probability`` lets a window fire only “sometimes” (e.g. morning ~1h).
* ``fixed`` — explicit day + start/end slots
* ``human_random`` — legacy randomized plan_daily_session behaviour

Dashboard edits persist via SettingsService (``schedule_json``) and override the
YAML defaults for the next scan.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class BatchWindow:
    name: str
    enabled: bool = True
    start: str = "08:00"          # HH:MM local
    end: str = "10:00"            # HH:MM local (inclusive window for matching)
    duration_minutes: int = 60    # used when min/max not set
    # When both set, each run picks a random duration in [min, max].
    duration_min: int | None = None
    duration_max: int | None = None
    # 1.0 = always run when clock is in window; 0.55 = “sometimes” (~half the days).
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
        return max(1, int(self.duration_minutes or 60))

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
    skip_probability: float = 0.0
    batches: dict[str, BatchWindow] = field(default_factory=dict)
    fixed: list[FixedSlot] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "enabled_days": list(self.enabled_days),
            "skip_probability": self.skip_probability,
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
    """Default: randomized human-like batches.

    * Morning — ~1 hour, only *sometimes* (run_probability 0.55)
    * Evening — ~40 minutes
    * Night — 2–3 hours (main session)
    """
    return ScheduleConfig(
        mode="batches",
        enabled_days=list(DAY_NAMES),
        skip_probability=0.0,
        batches={
            "morning": BatchWindow(
                name="morning", enabled=True,
                start="07:15", end="09:30",
                duration_minutes=60,
                duration_min=50, duration_max=70,
                run_probability=0.55,          # sometime in the morning
                portals=["LinkedIn"],
                max_jobs=25, max_jobs_min=15, max_jobs_max=35),
            "evening": BatchWindow(
                name="evening", enabled=True,
                start="17:45", end="19:15",
                duration_minutes=40,
                duration_min=35, duration_max=45,
                run_probability=1.0,
                portals=["Naukri"],
                max_jobs=30, max_jobs_min=20, max_jobs_max=40),
            "night": BatchWindow(
                name="night", enabled=True,
                start="20:00", end="23:30",
                duration_minutes=150,
                duration_min=120, duration_max=180,   # 2–3 hours
                run_probability=1.0,
                portals=["LinkedIn", "Naukri"],
                max_jobs=80, max_jobs_min=50, max_jobs_max=120),
            # Lunch kept available but off by default (enable in Jarvis if wanted).
            "lunch": BatchWindow(
                name="lunch", enabled=False,
                start="12:00", end="13:30",
                duration_minutes=40,
                duration_min=30, duration_max=45,
                run_probability=1.0,
                portals=["Naukri"],
                max_jobs=25),
        },
        fixed=[
            FixedSlot(days=list(DAY_NAMES[:5]), start="09:00", end="11:00",
                      duration_minutes=120, portals=["LinkedIn", "Naukri"],
                      max_jobs=50, enabled=False),
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
                duration_minutes=int(b.get("duration_minutes", 60) or 60),
                duration_min=_opt_int(b.get("duration_min")),
                duration_max=_opt_int(b.get("duration_max")),
                run_probability=float(b.get("run_probability", 1.0) or 1.0),
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

    return ScheduleConfig(
        mode=mode,
        enabled_days=days,
        skip_probability=float(raw.get("skip_probability", 0.0) or 0.0),
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
    # Any other named batches
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


def plan_from_schedule(schedule: ScheduleConfig, now: datetime, rng,
                       keywords: list[str] | None = None):
    """Build a SessionPlan from operator schedule (batches/fixed) or legacy random."""
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

    if schedule.mode == "fixed":
        slot = active_fixed_slot(schedule, now)
        if slot is None:
            return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                               max_jobs=0, is_weekend=is_weekend, keywords=kw,
                               portals=[], idle_gaps=[])
        portals = list(slot.portals)
        gaps = [rng.randint(5, 12)] if len(portals) > 1 else []
        return SessionPlan(
            skip_today=False, window="fixed",
            duration_minutes=max(1, int(slot.duration_minutes)),
            max_jobs=max(1, int(slot.max_jobs)),
            is_weekend=is_weekend, keywords=kw, portals=portals, idle_gaps=gaps)

    # batches (default) — random duration / max_jobs within configured ranges
    batch = active_batch(schedule, now)
    if batch is None:
        return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    # “Sometime” windows (e.g. morning): skip this run even though clock matches.
    raw_prob = getattr(batch, "run_probability", 1.0)
    prob = 1.0 if raw_prob is None else float(raw_prob)
    if prob < 1.0 and rng.random() > prob:
        return SessionPlan(skip_today=True, window=f"{batch.name}_skipped",
                           duration_minutes=0, max_jobs=0,
                           is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    portals = list(batch.portals)
    gaps = [rng.randint(5, 12)] if len(portals) > 1 else []
    return SessionPlan(
        skip_today=False, window=batch.name,
        duration_minutes=batch.pick_duration(rng),
        max_jobs=batch.pick_max_jobs(rng),
        is_weekend=is_weekend, keywords=kw, portals=portals, idle_gaps=gaps)


def describe_schedule(schedule: ScheduleConfig) -> list[str]:
    """Human-readable lines for the dashboard HUD."""
    lines = [f"Mode: {schedule.mode}",
             f"Days: {', '.join(schedule.enabled_days)}"]
    if schedule.mode == "batches":
        for name, b in schedule.batches.items():
            flag = "ON" if b.enabled else "off"
            if b.duration_min is not None and b.duration_max is not None:
                dur = f"{b.duration_min}-{b.duration_max}m random"
            else:
                dur = f"{b.duration_minutes}m"
            sometime = ""
            if float(b.run_probability or 1) < 1:
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

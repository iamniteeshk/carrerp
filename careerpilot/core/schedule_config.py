"""Operator-configurable scan schedule (batches, fixed windows, per-day).

Modes
-----
* ``batches`` — named morning/lunch/evening (etc.) windows with duration + portals
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
    duration_minutes: int = 120   # how long a scan inside this batch may run
    portals: list[str] = field(default_factory=lambda: ["LinkedIn", "Naukri"])
    max_jobs: int = 40

    def as_dict(self) -> dict:
        return asdict(self)


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


def default_schedule() -> ScheduleConfig:
    """Sensible dry-run appliance defaults: morning 2h, evening 1h."""
    return ScheduleConfig(
        mode="batches",
        enabled_days=list(DAY_NAMES),
        skip_probability=0.0,
        batches={
            "morning": BatchWindow(
                name="morning", enabled=True,
                start="07:15", end="09:30", duration_minutes=120,
                portals=["LinkedIn"], max_jobs=40),
            "lunch": BatchWindow(
                name="lunch", enabled=True,
                start="12:00", end="13:30", duration_minutes=60,
                portals=["Naukri"], max_jobs=30),
            "evening": BatchWindow(
                name="evening", enabled=True,
                start="18:30", end="20:30", duration_minutes=60,
                portals=["LinkedIn", "Naukri"], max_jobs=50),
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
                portals=list(b.get("portals") or ["LinkedIn", "Naukri"]),
                max_jobs=int(b.get("max_jobs", 40) or 40),
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

    # batches (default)
    batch = active_batch(schedule, now)
    if batch is None:
        return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    portals = list(batch.portals)
    gaps = [rng.randint(5, 12)] if len(portals) > 1 else []
    return SessionPlan(
        skip_today=False, window=batch.name,
        duration_minutes=max(1, int(batch.duration_minutes)),
        max_jobs=max(1, int(batch.max_jobs)),
        is_weekend=is_weekend, keywords=kw, portals=portals, idle_gaps=gaps)


def describe_schedule(schedule: ScheduleConfig) -> list[str]:
    """Human-readable lines for the dashboard HUD."""
    lines = [f"Mode: {schedule.mode}",
             f"Days: {', '.join(schedule.enabled_days)}"]
    if schedule.mode == "batches":
        for name, b in schedule.batches.items():
            flag = "ON" if b.enabled else "off"
            lines.append(
                f"{name}: {flag} {b.start}-{b.end} / {b.duration_minutes}m "
                f"portals={','.join(b.portals)} max={b.max_jobs}")
    elif schedule.mode == "fixed":
        for i, s in enumerate(schedule.fixed):
            flag = "ON" if s.enabled else "off"
            lines.append(
                f"slot{i+1}: {flag} {','.join(s.days)} {s.start}-{s.end} "
                f"{s.duration_minutes}m")
    return lines

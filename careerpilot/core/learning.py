"""Session memory, good-job learning, and human-like session planning.

Three small, dependency-free, fully testable pieces used to make CareerPilot
behave more like a real person over time:

* ``SessionHistoryStore``  -> database/session_history.json (one entry per run)
* ``GoodJobsStore``        -> database/good_jobs.json (jobs the AI scored >= 80)
* ``plan_session``         -> a randomized, non-repeating per-run SessionPlan

All JSON writes are atomic (temp file + replace) and never raise: persistence
must never crash a scan.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)

# Minimum Gemini score for a job to be remembered as a "good job".
GOOD_JOB_SCORE = 80.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _JsonListStore:
    """A tiny append-oriented JSON list store with atomic writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read %s: %s", self.path, exc)
            return []

    def _write(self, data: list[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            logger.warning("Could not write %s: %s", self.path, exc)


class SessionHistoryStore(_JsonListStore):
    """Persist one record per scan so future runs can vary their behaviour."""

    def record(self, entry: dict) -> dict:
        with self._lock:
            data = self.all()
            entry = dict(entry)
            entry.setdefault("date", _now_iso())
            data.append(entry)
            self._write(data)
        logger.info("Session history recorded (%s total runs) -> %s",
                    len(data), self.path)
        return entry

    def last(self) -> dict | None:
        data = self.all()
        return data[-1] if data else None


class GoodJobsStore(_JsonListStore):
    """Remember high-scoring jobs (score >= GOOD_JOB_SCORE) to inform future
    scoring. De-duplicated on (title, company)."""

    def add(self, job_info: dict) -> bool:
        title = str(job_info.get("title", "")).strip().lower()
        company = str(job_info.get("company", "")).strip().lower()
        with self._lock:
            data = self.all()
            for e in data:
                if (str(e.get("title", "")).strip().lower() == title and
                        str(e.get("company", "")).strip().lower() == company):
                    return False    # already remembered
            entry = dict(job_info)
            entry.setdefault("saved_at", _now_iso())
            data.append(entry)
            self._write(data)
        logger.info("Good job remembered: %s @ %s (score=%s) [%s total]",
                    job_info.get("title"), job_info.get("company"),
                    job_info.get("score"), len(data))
        return True

    def summary(self, limit: int = 12) -> str:
        """A concise, human-readable digest of what has matched well before,
        for injection into the AI prompt so scoring improves over time."""
        data = self.all()
        if not data:
            return ""
        titles = Counter()
        industries = Counter()
        skills = Counter()
        for e in data:
            if e.get("title"):
                titles[str(e["title"]).strip()] += 1
            if e.get("industry"):
                industries[str(e["industry"]).strip()] += 1
            for s in (e.get("skills") or []):
                s = str(s).strip()
                if s:
                    skills[s] += 1
        parts = [f"{len(data)} previously strong matches."]
        if titles:
            parts.append("Common good titles: "
                         + ", ".join(t for t, _ in titles.most_common(limit)))
        if industries:
            parts.append("Common industries: "
                         + ", ".join(i for i, _ in industries.most_common(6)))
        if skills:
            parts.append("Recurring skills: "
                         + ", ".join(s for s, _ in skills.most_common(limit)))
        return " ".join(parts)


# ---- human-like session planning ----------------------------------------

@dataclass
class SessionPlan:
    """A single run's randomized shape. No two runs should be identical."""
    skip_today: bool
    window: str               # "morning" / "lunch" / "evening" / "weekend" / "off"
    duration_minutes: int
    max_jobs: int
    is_weekend: bool
    keywords: list[str] = field(default_factory=list)
    # v3.1.1: which portal(s) this session uses, in order, and idle-gap minutes
    # between them (so LinkedIn and Naukri are never opened simultaneously).
    portals: list[str] = field(default_factory=list)
    idle_gaps: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "skip_today": self.skip_today, "window": self.window,
            "duration_minutes": self.duration_minutes, "max_jobs": self.max_jobs,
            "is_weekend": self.is_weekend, "keywords": list(self.keywords),
            "portals": list(self.portals), "idle_gaps": list(self.idle_gaps),
        }


# Session windows a human might pick (start-hour ranges, local time).
WEEKDAY_WINDOWS = ("morning", "lunch", "afternoon", "night")
WEEKEND_WINDOWS = ("morning", "afternoon", "night")


def plan_session(rng, weekday: int, keywords: list[str] | None = None,
                 *, skip_probability: float = 0.12) -> SessionPlan:
    """Build a randomized SessionPlan.

    ``rng`` is a ``random.Random`` (seed it in tests; leave unseeded in prod so
    every run differs). ``weekday`` is 0=Mon .. 6=Sun. Weekends get longer
    sessions; some days are skipped entirely (humans don't search every day).
    Keyword order is shuffled so no two runs search in the same order.
    """
    is_weekend = weekday >= 5
    skip_today = rng.random() < skip_probability
    if is_weekend:
        window = rng.choice(WEEKEND_WINDOWS)
        duration = rng.randint(150, 210)          # 2.5-3.5 hours
    else:
        window = rng.choice(WEEKDAY_WINDOWS)
        duration = rng.randint(60, 150)           # ~1-2.5 hours
    # Sometimes finish after few jobs, sometimes many.
    max_jobs = rng.randint(25, 150)
    kw = list(keywords or [])
    rng.shuffle(kw)
    return SessionPlan(skip_today=skip_today, window=window,
                       duration_minutes=duration, max_jobs=max_jobs,
                       is_weekend=is_weekend, keywords=kw)


# Time-of-day session windows (local time, minutes since midnight). Humans do
# short morning scans, a lunch scan, and a longer evening session -- never one
# continuous 2-hour block.
MORNING_WINDOW = (7 * 60 + 15, 8 * 60 + 45)     # 07:15-08:45
LUNCH_WINDOW = (12 * 60, 13 * 60 + 30)          # 12:00-13:30
EVENING_WINDOW = (18 * 60 + 45, 20 * 60 + 55)   # 18:45-20:55


def _window_for(minutes: int) -> str:
    if MORNING_WINDOW[0] <= minutes <= MORNING_WINDOW[1]:
        return "morning"
    if LUNCH_WINDOW[0] <= minutes <= LUNCH_WINDOW[1]:
        return "lunch"
    if EVENING_WINDOW[0] <= minutes <= EVENING_WINDOW[1]:
        return "evening"
    return "off"


def plan_daily_session(rng, now, keywords: list[str] | None = None,
                       *, skip_probability: float = 0.12) -> SessionPlan:
    """Plan a realistic, time-of-day session (item 11/12).

    Depending on the local time in ``now`` (a datetime) the session is a short
    morning LinkedIn scan, a lunch Naukri scan, or a longer evening session that
    uses BOTH portals in a randomized order with an idle gap between them (never
    simultaneously). Weekends are longer. Outside any window the plan is "off".
    ``rng`` should be unseeded in production (every day differs) and seeded in
    tests.
    """
    is_weekend = now.weekday() >= 5
    minutes = now.hour * 60 + now.minute
    window = _window_for(minutes)
    kw = list(keywords or [])
    rng.shuffle(kw)
    if window == "off":
        return SessionPlan(skip_today=True, window="off", duration_minutes=0,
                           max_jobs=0, is_weekend=is_weekend, keywords=kw,
                           portals=[], idle_gaps=[])
    skip_today = rng.random() < skip_probability
    if is_weekend:
        duration = rng.randint(150, 210)            # 2.5-3.5h total
        max_jobs = rng.randint(60, 150)
        portals = ["LinkedIn", "Naukri"]; rng.shuffle(portals)
        idle_gaps = [rng.randint(10, 15)]
    elif window == "morning":
        duration = rng.randint(8, 18)               # quick scan
        max_jobs = rng.randint(5, 15)
        portals = ["LinkedIn"]; idle_gaps = []
    elif window == "lunch":
        duration = rng.randint(25, 40)
        max_jobs = rng.randint(20, 40)
        portals = ["Naukri"]; idle_gaps = []
    else:                                            # evening (main session)
        duration = rng.randint(45, 90)
        max_jobs = rng.randint(40, 120)
        portals = ["LinkedIn", "Naukri"]; rng.shuffle(portals)
        idle_gaps = [rng.randint(5, 15)]
    return SessionPlan(skip_today=skip_today, window=window,
                       duration_minutes=duration, max_jobs=max_jobs,
                       is_weekend=is_weekend, keywords=kw, portals=portals,
                       idle_gaps=idle_gaps)

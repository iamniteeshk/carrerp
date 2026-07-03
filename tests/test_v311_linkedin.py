"""v3.1.1 tests: time-of-day session + portal scheduling, LinkedIn card-first
pre-filtering, and no-retry-on-selector-failure in the JD extractor."""

from __future__ import annotations

import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.learning import plan_daily_session
from careerpilot.core.models import Job
from careerpilot.core.config import RuleConfig
from careerpilot.rules.rule_engine import RuleEngine
from careerpilot.browser.base_portal import collect_incrementally
from careerpilot.browser.job_detail import JobDetailExtractor


def _at(h, m, weekday=1):
    # A datetime on a weekday (Tue) or weekend depending on the date chosen.
    # 2026-07-07 is a Tuesday; 2026-07-11 is a Saturday.
    day = 7 if weekday < 5 else 11
    return datetime(2026, 7, day, h, m)


# ---- time-of-day session + portal scheduling (items 11, 12) --------------

def test_morning_is_short_linkedin_only():
    p = plan_daily_session(random.Random(1), _at(8, 0), ["a", "b"])
    assert p.window == "morning"
    assert p.portals == ["LinkedIn"]
    assert 8 <= p.duration_minutes <= 18


def test_lunch_is_naukri_only():
    p = plan_daily_session(random.Random(1), _at(12, 30), ["a", "b"])
    assert p.window == "lunch"
    assert p.portals == ["Naukri"]
    assert 25 <= p.duration_minutes <= 40


def test_evening_uses_both_portals_with_idle_gap():
    p = plan_daily_session(random.Random(3), _at(19, 30), ["a", "b"])
    assert p.window == "evening"
    assert sorted(p.portals) == ["LinkedIn", "Naukri"]     # both, some order
    assert 45 <= p.duration_minutes <= 90
    assert p.idle_gaps and p.idle_gaps[0] >= 5              # gap between portals


def test_off_window_is_skipped():
    p = plan_daily_session(random.Random(1), _at(3, 0), ["a"])
    assert p.window == "off" and p.skip_today and p.portals == []


def test_weekend_is_longer_and_uses_both():
    p = plan_daily_session(random.Random(2), _at(19, 0, weekday=6), ["a", "b"])
    assert p.is_weekend and 150 <= p.duration_minutes <= 210
    assert sorted(p.portals) == ["LinkedIn", "Naukri"]


# ---- LinkedIn card-first filtering (item 1) ------------------------------

def _rule_config(**ov):
    base = dict(minimum_salary=0, salary_currency="INR", minimum_experience=0,
                accepted_employment_types=[], rejected_shifts=[],
                preferred_locations=[], accepted_titles=["director", "head",
                "infrastructure", "digital workplace", "euc"],
                rejected_titles=[], blacklist_companies=[], required_keywords=[],
                nice_to_have_keywords=[])
    base.update(ov)
    return RuleConfig(**base)


class _Page:
    url = "https://www.linkedin.com/jobs/search"
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass


def test_linkedin_rejects_offdomain_cards_before_opening():
    """The card Rule Engine must skip Social Media / Video Editor / AI Engineer
    cards WITHOUT opening them -- filtering happens on the card, pre-open."""
    engine = RuleEngine(_rule_config())
    cards = [
        Job(portal="LinkedIn", job_title="Head - Digital Workplace", job_url="u1"),
        Job(portal="LinkedIn", job_title="Social Media Manager", job_url="u2"),
        Job(portal="LinkedIn", job_title="Video Editor", job_url="u3"),
        Job(portal="LinkedIn", job_title="AI Engineer", job_url="u4"),
        Job(portal="LinkedIn", job_title="Director - IT Infrastructure", job_url="u5"),
    ]
    def parse_fn(page, _c=[0]):
        if _c[0]:
            return []
        _c[0] = 1
        return list(cards)
    opened = []
    out = collect_incrementally(
        _Page(), parse_fn, scroll_passes=0,
        on_job=lambda j: None,
        detail_fn=lambda j: opened.append(j.job_title),
        should_open=lambda j: engine.prefilter(j).accepted)
    assert len(out) == 5                                # all collected
    assert "Social Media Manager" not in opened         # never opened
    assert "Video Editor" not in opened
    assert "AI Engineer" not in opened
    assert set(opened) == {"Head - Digital Workplace",
                           "Director - IT Infrastructure"}


# ---- no retry on selector failure (item 3) -------------------------------

class _DetailPage:
    def __init__(self):
        self.url = "https://www.linkedin.com/jobs/view/1"
        self.attempts = 0
    def bring_to_front(self): self.attempts += 1
    def goto(self, url, wait_until=None): self.url = url
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass
    def evaluate(self, *a, **k): return 800
    def query_selector(self, sel): return None            # nothing matches -> empty
    def query_selector_all(self, sel): return []
    def content(self): return ""


def test_selector_failure_is_not_retried():
    ex = JobDetailExtractor(humanizer=None, job_cache=None)
    page = _DetailPage()
    job = Job(portal="LinkedIn", job_title="Director - IT Infrastructure",
              job_url="https://www.linkedin.com/jobs/view/1")
    out = ex.open_and_extract(page, job, networkidle_timeout_ms=10,
                              render_settle_ms=0)
    assert page.attempts == 1                    # opened exactly once, NO retry
    assert out.read_status == "PARTIAL"
    assert "selector failure" in (out.failure_detail or "").lower()


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); passed += 1; print(f"PASS {name}")
            except Exception:
                failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

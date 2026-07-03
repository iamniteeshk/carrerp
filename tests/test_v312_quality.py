"""v3.1.2 tests: junior/seniority rejection, COMPLETE-only cache reuse,
idle human mouse drift, and highlight-then-deselect."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.config import RuleConfig
from careerpilot.core.enums import RejectionReason
from careerpilot.core.models import Job
from careerpilot.rules.rule_engine import RuleEngine
from careerpilot.browser.humanize import Humanizer, HumanConfig


def _rule_config(**ov):
    base = dict(minimum_salary=0, salary_currency="INR", minimum_experience=0,
                accepted_employment_types=["Full Time", "Permanent"],
                rejected_shifts=[], preferred_locations=[],
                accepted_titles=["director", "head", "vp", "infrastructure",
                                 "digital workplace", "euc", "manager"],
                rejected_titles=[], blacklist_companies=[],
                required_keywords=["infrastructure", "digital workplace"],
                nice_to_have_keywords=[])
    base.update(ov)
    return RuleConfig(**base)


def _job(**kw):
    d = dict(portal="LinkedIn", company="Acme", job_title="Director - IT Infrastructure",
             location="Chennai", experience="20 years", employment_type="Full Time",
             job_description="IT infrastructure and digital workplace leadership")
    d.update(kw)
    return Job(**d)


# ---- item 4: junior / entry-level rejection ------------------------------

def test_rejects_junior_and_entry_titles():
    engine = RuleEngine(_rule_config())
    for title in ("Fresher", "Software Intern", "Graduate Trainee",
                  "Junior System Administrator", "IT Executive",
                  "Desk Coordinator", "L1 Engineer", "Executive Assistant"):
        pre = engine.prefilter(_job(job_title=title))
        assert not pre.accepted and pre.reason == RejectionReason.INVALID_JOB_TITLE, title
        assert not engine.evaluate(_job(job_title=title)).accepted, title


def test_strong_senior_term_rescues_ambiguous_word():
    # 'Executive Director' / 'Chief ...' keep their strong senior term.
    engine = RuleEngine(_rule_config())
    assert engine.prefilter(_job(job_title="Executive Director - Infrastructure")).accepted
    assert engine.evaluate(_job(job_title="Executive Director - Infrastructure")).accepted
    assert engine.prefilter(_job(job_title="Associate Director - Digital Workplace")).accepted


def test_fresher_is_rejected_even_with_domain_keyword():
    # A domain keyword must NOT rescue a junior title (unlike off-domain terms).
    engine = RuleEngine(_rule_config())
    r = engine.evaluate(_job(job_title="Fresher - Infrastructure Support"))
    assert not r.accepted and r.reason == RejectionReason.INVALID_JOB_TITLE


# ---- item 6: COMPLETE-only cache reuse -----------------------------------

def test_partial_cache_is_reextracted_not_trusted():
    from careerpilot.browser.job_detail import JobDetailExtractor
    from careerpilot.core.job_cache import JobCache
    d = tempfile.mkdtemp()
    cache = JobCache(os.path.join(d, "cache"))
    url = "https://www.linkedin.com/jobs/view/partial"
    cache.put({"job_url": url, "job_title": "Director", "company": "Acme"})  # no JD

    class _Page:
        def __init__(self, u): self.opened = 0; self.url = u
        def bring_to_front(self): self.opened += 1
        def goto(self, u, wait_until=None): self.url = u
        def wait_for_load_state(self, *a, **k): pass
        def wait_for_timeout(self, *a, **k): pass
        def evaluate(self, *a, **k): return 800
        def query_selector(self, s): return None
        def query_selector_all(self, s): return []
        def content(self): return ""
    page = _Page(url)
    ex = JobDetailExtractor(humanizer=None, job_cache=cache)
    job = Job(portal="LinkedIn", job_title="Director", job_url=url)
    ex.open_and_extract(page, job, networkidle_timeout_ms=10, render_settle_ms=0)
    assert page.opened >= 1          # re-opened instead of trusting partial cache


def test_complete_cache_is_reused_without_opening():
    from careerpilot.browser.job_detail import JobDetailExtractor
    from careerpilot.core.job_cache import JobCache
    d = tempfile.mkdtemp()
    cache = JobCache(os.path.join(d, "cache"))
    url = "https://www.linkedin.com/jobs/view/complete"
    cache.put({"job_url": url, "job_title": "Director - IT Infra",
               "company": "Acme", "job_description": "x" * 400, "location": "Chennai"})

    class _Boom:
        def __init__(self, u): self.url = u
        def bring_to_front(self): raise AssertionError("should NOT re-open a COMPLETE cache")
    ex = JobDetailExtractor(humanizer=None, job_cache=cache)
    job = Job(portal="LinkedIn", job_title="Director - IT Infra", job_url=url)
    out = ex.open_and_extract(_Boom(url), job)
    assert out.read_status == "COMPLETE"


# ---- items 1,2: idle mouse drift + highlight-then-deselect ---------------

class _MousePage:
    def __init__(self):
        self.moves = []; self.downs = 0; self.ups = 0; self.clicks = 0
    class _M:
        def __init__(self, o): self.o = o
        def move(self, x, y, steps=None): self.o.moves.append((round(x), round(y)))
        def down(self): self.o.downs += 1
        def up(self): self.o.ups += 1
        def click(self, x, y): self.o.clicks += 1
        def wheel(self, x, y): pass
    @property
    def mouse(self): return _MousePage._M(self)
    def wait_for_timeout(self, ms): pass
    def evaluate(self, *a, **k): return 800


def test_human_idle_produces_multiple_non_static_moves():
    h = Humanizer(HumanConfig(enabled=True, seed=1))
    page = _MousePage()
    n = h.human_idle(page)
    assert n >= 1 and len(page.moves) > n     # several curved intermediate points
    xs = [m[0] for m in page.moves]; ys = [m[1] for m in page.moves]
    assert max(xs) != min(xs) or max(ys) != min(ys)   # not perfectly still


def test_human_idle_noop_when_disabled():
    assert Humanizer(HumanConfig(enabled=False)).human_idle(_MousePage()) == 0


def test_maybe_highlight_then_deselects_with_click():
    h = Humanizer(HumanConfig(enabled=True, seed=1, highlight_chance=1.0))
    page = _MousePage()
    assert h.maybe_highlight(page, {"x": 5, "y": 5, "width": 120, "height": 20})
    assert page.downs == 1 and page.ups == 1      # drag-selected
    assert page.clicks == 1                        # then clicked empty space to deselect


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

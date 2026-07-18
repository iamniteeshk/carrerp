"""v3.1.0 tests: session memory, good-job learning, session planning,
per-portal reports + summary, human-behaviour helpers, and the session cap."""

from __future__ import annotations

import os
import random
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.learning import (GoodJobsStore, SessionHistoryStore,
                                       plan_session, GOOD_JOB_SCORE)
from careerpilot.browser.humanize import Humanizer, HumanConfig
from careerpilot.reports.streaming_csv import StreamingCSVReporter
from careerpilot.reports.csv_reporter import CSVReporter
from careerpilot.db.database import Database
from careerpilot.db.services import JobService
from careerpilot.core.models import Job
from careerpilot.core.enums import JobStatus


# ---- session history -----------------------------------------------------

def test_session_history_records_and_reads_back():
    with tempfile.TemporaryDirectory() as tmp:
        s = SessionHistoryStore(Path(tmp) / "session_history.json")
        s.record({"runtime_seconds": 100, "jobs_found": 20})
        s.record({"runtime_seconds": 200, "jobs_found": 40})
        assert len(s.all()) == 2
        assert s.last()["jobs_found"] == 40
        assert "date" in s.last()            # timestamp added automatically


# ---- good jobs -----------------------------------------------------------

def test_good_jobs_dedupes_and_summarizes():
    with tempfile.TemporaryDirectory() as tmp:
        g = GoodJobsStore(Path(tmp) / "good_jobs.json")
        assert g.add({"title": "Director - IT Infrastructure", "company": "Acme",
                      "skills": ["ITSM", "EUC"], "score": 92})
        # Same (title, company) is not stored twice.
        assert g.add({"title": "director - it infrastructure", "company": "ACME",
                      "score": 90}) is False
        assert g.add({"title": "Head IT", "company": "Globex",
                      "skills": ["ITSM"], "score": 88})
        assert len(g.all()) == 2
        summ = g.summary()
        assert "2 previously strong matches" in summ and "ITSM" in summ


def test_good_jobs_summary_empty_when_no_history():
    with tempfile.TemporaryDirectory() as tmp:
        assert GoodJobsStore(Path(tmp) / "good_jobs.json").summary() == ""


# ---- session planning ----------------------------------------------------

def test_plan_session_weekend_is_longer_than_weekday():
    wd = plan_session(random.Random(1), weekday=2, keywords=["a", "b"])
    we = plan_session(random.Random(1), weekday=6, keywords=["a", "b"])
    assert not wd.is_weekend and we.is_weekend
    assert 60 <= wd.duration_minutes <= 150
    assert 150 <= we.duration_minutes <= 210
    assert 25 <= wd.max_jobs <= 150


def test_plan_session_shuffles_keywords_and_is_reproducible():
    kws = ["Director", "Infrastructure", "IT Head", "Digital Workplace", "EUC"]
    a = plan_session(random.Random(7), 1, kws)
    b = plan_session(random.Random(7), 1, kws)
    assert a.keywords == b.keywords              # same seed -> same order
    assert sorted(a.keywords) == sorted(kws)     # no keyword lost
    # Different seeds usually produce a different order (not identical runs).
    c = plan_session(random.Random(99), 1, kws)
    assert isinstance(c.keywords, list) and len(c.keywords) == len(kws)


def test_plan_session_can_skip_a_day():
    # With probability 1.0 the day is always skipped; with 0.0 never.
    assert plan_session(random.Random(1), 3, [], skip_probability=1.0).skip_today
    assert not plan_session(random.Random(1), 3, [], skip_probability=0.0).skip_today


# ---- per-portal streaming reports ---------------------------------------

def test_streaming_reports_split_by_portal():
    with tempfile.TemporaryDirectory() as tmp:
        r = StreamingCSVReporter(tmp, per_portal=True)
        nk = Job(portal="Naukri", company="A", job_title="Director - Infra",
                 job_url="u1")
        li = Job(portal="LinkedIn", company="B", job_title="Head IT",
                 job_url="u2")
        r.found(nk); r.matched(nk, 90, "Infrastructure")
        r.found(li); r.rejected(li, "Domain Mismatch")
        assert (Path(tmp) / "naukri" / "FoundJobs.csv").exists()
        assert (Path(tmp) / "naukri" / "MatchedJobs.csv").exists()
        assert (Path(tmp) / "linkedin" / "FoundJobs.csv").exists()
        assert (Path(tmp) / "linkedin" / "RejectedJobs.csv").exists()
        # Naukri and LinkedIn never mix.
        assert not (Path(tmp) / "naukri" / "RejectedJobs.csv").exists()


def test_summary_csv_has_one_row_per_portal():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "cp.db")); db.initialize()
        jobs = JobService(db)
        j1 = Job(portal="Naukri", company="A", job_title="Director - Infra",
                 job_url="n1", job_description="x" * 200, read_status="COMPLETE")
        j1.reading_ms = 40000
        jid = jobs.insert(j1)
        jobs.update_status(jid, JobStatus.MATCHED, match_score=90,
                           selected_resume="Infrastructure")
        j2 = Job(portal="LinkedIn", company="B", job_title="Head IT",
                 job_url="l1", job_description="y" * 200, read_status="COMPLETE")
        j2.reading_ms = 20000
        jid2 = jobs.insert(j2)
        jobs.update_status(jid2, JobStatus.REJECTED, match_score=15,
                           rejection_reason="low")
        rep = CSVReporter(db, tmp)
        path = rep.generate_summary(runtime_seconds=123)
        body = Path(path).read_text()
        assert "Portal,Found,Opened,Rejected,Matched,Applied,Failed" in body
        assert "Naukri" in body and "LinkedIn" in body
        db.close()


# ---- human behaviour helpers --------------------------------------------

def test_reading_time_bands_scale_with_jd_length():
    h = Humanizer(HumanConfig(enabled=True, seed=1))
    tiny = h.jd_reading_seconds("word " * 30)
    medium = h.jd_reading_seconds("word " * 300)
    large = h.jd_reading_seconds("word " * 900)
    assert 10 <= tiny <= 20
    assert 20 <= medium <= 45
    assert 45 <= large <= 90


class _KeyPage:
    def __init__(self): self.keys = []; self.downs = 0; self.ups = 0; self.moves = []
    class _KB:
        def __init__(self, o): self.o = o
        def press(self, key): self.o.keys.append(key)
    class _M:
        def __init__(self, o): self.o = o
        def move(self, x, y, steps=None): self.o.moves.append((round(x), round(y)))
        def down(self): self.o.downs += 1
        def up(self): self.o.ups += 1
        def wheel(self, x, y): pass
    @property
    def keyboard(self): return _KeyPage._KB(self)
    @property
    def mouse(self): return _KeyPage._M(self)
    def wait_for_timeout(self, ms): pass
    def evaluate(self, *a, **k): return 800


def test_keyboard_scroll_presses_a_key():
    h = Humanizer(HumanConfig(enabled=True, seed=2))
    page = _KeyPage()
    key = h.keyboard_scroll(page)
    assert key in ("PageDown", "ArrowDown")
    assert page.keys and page.keys[0] == key


def test_maybe_break_only_when_enabled_and_probable():
    assert Humanizer(HumanConfig(enabled=False)).maybe_break(_KeyPage()) == 0
    h = Humanizer(HumanConfig(enabled=True, seed=1, break_chance=1.0))
    assert h.maybe_break(_KeyPage()) > 0            # always breaks at prob 1.0
    h2 = Humanizer(HumanConfig(enabled=True, seed=1, break_chance=0.0))
    assert h2.maybe_break(_KeyPage()) == 0          # never breaks at prob 0.0


def test_highlight_drag_selects_with_mouse_down_up():
    h = Humanizer(HumanConfig(enabled=True, seed=1))
    page = _KeyPage()
    h.highlight(page, 10, 20, 200, 20)
    assert page.downs == 1 and page.ups == 1        # pressed then released
    assert page.moves and page.moves[-1] == (200, 20)


def test_maybe_highlight_respects_probability_and_box():
    page = _KeyPage()
    h = Humanizer(HumanConfig(enabled=True, seed=1, highlight_chance=1.0))
    assert h.maybe_highlight(page, {"x": 5, "y": 5, "width": 100, "height": 20})
    assert not h.maybe_highlight(page, None)
    h0 = Humanizer(HumanConfig(enabled=True, seed=1, highlight_chance=0.0))
    assert not h0.maybe_highlight(page, {"x": 5, "y": 5, "width": 100, "height": 20})


# ---- pipeline session cap ------------------------------------------------

def test_session_cap_stops_processing_new_jobs():
    import tests.test_read_gate as g
    p = g._pipeline()
    p.session_max_jobs = 1
    p.session_deadline = None
    p._found = 0
    counts = g._counts()
    for i in range(3):
        j = Job(portal="Naukri", job_title="Director - IT Infrastructure",
                company="Acme", job_url=f"u{i}", job_description="x" * 300,
                read_status="COMPLETE")
        p._process_job(j, counts, dry_run=True)
    assert counts["found"] == 1                      # cap honoured
    assert counts["skipped"] >= 2                    # the rest are skipped


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

"""Tests for the v2.8.5 Human Browser Automation gate.

The central fix: the Rule and AI engines must NEVER decide on card-only data.
A job that was not opened (UNREAD) or only partially read (PARTIAL) is marked
Partial Data and never selected/rejected-for-fit. This directly prevents the
observed bug where an unrelated CFO role was *selected from the card* without
ever being opened.
"""

from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.job_detail import assess_completeness
from careerpilot.core.enums import JobStatus
from careerpilot.core.models import Job


# ---- completeness assessor ----------------------------------------------

def test_assess_complete_when_jd_substantive():
    j = Job(portal="naukri", job_title="Director", job_description="x" * 300,
            company="Acme", salary="50 LPA", experience="18y",
            employment_type="Full time")
    status, missing = assess_completeness(j)
    assert status == "COMPLETE" and missing == []


def test_assess_partial_when_jd_missing_or_short():
    j = Job(portal="naukri", job_title="Director", job_description="too short")
    status, missing = assess_completeness(j)
    assert status == "PARTIAL" and "job_description" in missing


# ---- the pipeline gate ---------------------------------------------------

class _Jobs:
    def __init__(self):
        self.status_by_id = {}
        self._id = 0
    def exists(self, job): return False
    def insert(self, job):
        self._id += 1
        return self._id
    def update_status(self, jid, status, rejection_reason=None, **kwargs):
        self.status_by_id[jid] = (status, rejection_reason)


class _Rules:
    def __init__(self): self.called_with = []
    def evaluate(self, job):
        self.called_with.append(job)
        return types.SimpleNamespace(
            accepted=True, reason=types.SimpleNamespace(value="ok"))


class _AI:
    def __init__(self): self.called = 0
    def evaluate_job(self, job):
        self.called += 1
        return types.SimpleNamespace(match_score=90, career_profile="Infra",
                                     confidence=95, reason="fit", apply=False,
                                     provider="x", model="m", tokens_used=1,
                                     execution_time=0.1, raw_response="{}")


class _Stream:
    def __init__(self): self.events = []
    def found(self, j): self.events.append(("found", j.job_title))
    def rejected(self, j, r): self.events.append(("rejected", r))
    def selected(self, j): self.events.append(("selected", j.job_title))
    def matched(self, j, s, p): self.events.append(("matched", j.job_title))
    def applied(self, j, d): self.events.append(("applied", j.job_title))
    def failed(self, j, r): self.events.append(("failed", r))


class _Failed:
    def __init__(self): self.records = []
    def record(self, job_id, reason, retry_count=0, screenshot=""):
        self.records.append((job_id, reason))


class _Apply:
    def dry_run(self, job, ev):
        return types.SimpleNamespace(success=True)
    def apply_to_job(self, job, ev):
        return types.SimpleNamespace(success=True)


def _pipeline():
    from careerpilot.core.pipeline import ScanPipeline
    p = ScanPipeline.__new__(ScanPipeline)
    p.jobs = _Jobs(); p.rules = _Rules(); p.ai = _AI(); p.stream = _Stream()
    p.failed_jobs = _Failed(); p.apply_engine = _Apply()
    p.diagnostics = None; p.status_sink = None; p.notifier = None
    p._job_seq = 0; p._ai_notified = False; p._run_log = []
    return p


def _counts():
    return {"found": 0, "rejected": 0, "matched": 0, "applied": 0,
            "skipped": 0, "partial": 0, "failed": 0}


def test_unread_cfo_job_is_never_selected():
    """The exact observed bug: a CFO card must not be selected without opening,
    and it must NOT be stranded -- it lands in failed_jobs.csv with a reason."""
    p = _pipeline()
    counts = _counts()
    cfo = Job(portal="naukri", job_title="Chief Financial Officer (CFO)",
              company="Acme", job_url="u", read_status="UNREAD")
    p._process_job(cfo, counts, dry_run=True)
    assert counts["partial"] == 1
    assert counts["matched"] == 0
    assert counts["failed"] == 1                # terminal outcome recorded
    assert p.rules.called_with == []           # Rule Engine NEVER ran on the card
    assert p.ai.called == 0                     # AI NEVER ran on the card
    status, reason = p.jobs.status_by_id[1]
    assert status == JobStatus.PARTIAL_DATA
    assert "never opened" in reason
    assert p.failed_jobs.records and "PARTIAL_DATA" in p.failed_jobs.records[0][1]
    assert ("failed", p.failed_jobs.records[0][1]) in p.stream.events


def test_no_job_is_stranded_each_reaches_one_terminal():
    """Found jobs must each end in exactly one terminal outcome."""
    p = _pipeline()
    counts = _counts()
    # one unread (-> failed), one complete (-> matched)
    p._process_job(Job(portal="naukri", job_title="CFO", job_url="u1",
                       read_status="UNREAD"), counts, dry_run=True)
    p._process_job(Job(portal="naukri", job_title="Director - Infra", job_url="u2",
                       job_description="x" * 300, read_status="COMPLETE"),
                   counts, dry_run=True)
    # 'applied' is a sub-outcome of 'matched', so distinct terminals are
    # rejected / matched / failed. Every found job must hit exactly one.
    terminal = counts["rejected"] + counts["matched"] + counts["failed"]
    assert counts["found"] == 2
    assert terminal == 2                        # every found job ended somewhere


def test_partial_read_job_is_marked_partial_not_decided():
    p = _pipeline()
    counts = _counts()
    j = Job(portal="naukri", job_title="Director", company="Acme", job_url="u",
            read_status="PARTIAL", missing_fields=["job_description"])
    p._process_job(j, counts, dry_run=True)
    assert counts["partial"] == 1 and counts["matched"] == 0
    assert p.rules.called_with == [] and p.ai.called == 0
    assert p.jobs.status_by_id[1][0] == JobStatus.PARTIAL_DATA


def test_complete_job_reaches_rule_and_ai():
    p = _pipeline()
    counts = _counts()
    j = Job(portal="naukri", job_title="Director - IT Infrastructure",
            company="Acme", job_url="u", job_description="x" * 300,
            read_status="COMPLETE")
    p._process_job(j, counts, dry_run=True)
    assert len(p.rules.called_with) == 1       # Rule ran on the FULL job
    assert p.ai.called == 1                     # AI ran on the FULL job
    assert counts["partial"] == 0
    assert ("selected", j.job_title) in p.stream.events



def test_incremental_read_scales_with_content():
    from careerpilot.browser.humanize import Humanizer, HumanConfig
    class FakePage:
        def __init__(s): s.scrolls=0
        def evaluate(s,*a,**k): s.scrolls+=1; return None
        def wait_for_timeout(s,ms): pass
        @property
        def mouse(s):
            class M:
                def move(self,*a,**k): pass
            return M()
    h=Humanizer(HumanConfig(enabled=True, seed=1))
    short=h.incremental_read(FakePage(), "word "*30)
    long=h.incremental_read(FakePage(), "word "*800)
    assert long["passes"] > short["passes"]      # longer JD = more passes
    assert short["passes"] >= 1
    assert all("ms" in t for t in long["timeline"])


def test_incremental_read_noop_when_disabled():
    from careerpilot.browser.humanize import Humanizer, HumanConfig
    h=Humanizer(HumanConfig(enabled=False))
    out=h.incremental_read(object(), "anything")
    assert out["passes"] == 0

def test_cache_hit_sets_read_status_complete():
    """A cached job with a substantive JD must come back COMPLETE on a cache hit
    (not UNREAD) -- otherwise the gate wrongly marks it Partial Data forever."""
    import tempfile, os
    from careerpilot.browser.job_detail import JobDetailExtractor
    from careerpilot.core.job_cache import JobCache
    d = tempfile.mkdtemp()
    cache = JobCache(os.path.join(d, "cache"))
    url = "https://www.naukri.com/job/xyz"
    # Seed the cache with a fully-read job.
    cache.put({"job_url": url, "job_title": "Director - IT Infra",
               "company": "Acme", "job_description": "x" * 400,
               "location": "Chennai"})
    ex = JobDetailExtractor(humanizer=None, job_cache=cache)
    job = Job(portal="naukri", job_title="Director - IT Infra", job_url=url)
    # page is never touched on a cache hit -> pass a dummy.
    out = ex.open_and_extract(object(), job)
    assert out.read_status == "COMPLETE"


def test_cache_hit_partial_when_jd_missing():
    import tempfile, os
    from careerpilot.browser.job_detail import JobDetailExtractor
    from careerpilot.core.job_cache import JobCache
    d = tempfile.mkdtemp()
    cache = JobCache(os.path.join(d, "cache"))
    url = "https://www.naukri.com/job/abc"
    cache.put({"job_url": url, "job_title": "Director",
               "company": "Acme"})  # no JD
    ex = JobDetailExtractor(humanizer=None, job_cache=cache)
    job = Job(portal="naukri", job_title="Director", job_url=url)
    out = ex.open_and_extract(object(), job)
    assert out.read_status != "COMPLETE"


def test_run_log_md_written():
    """run_once writes a markdown run-log with the per-job stage trace."""
    import tempfile, types, glob, os
    from careerpilot.core.pipeline import ScanPipeline
    p = ScanPipeline.__new__(ScanPipeline)
    d = tempfile.mkdtemp()
    p.reporter = types.SimpleNamespace(report_dir=d)
    p._run_log = ["Job #1 | CARD_DETECTED | x", "Job #1 | JOB_FINISHED | MATCHED"]
    p._write_run_log_md({"found": 1, "matched": 1, "rejected": 0, "failed": 0,
                         "applied": 1, "skipped": 0}, 1.5)
    files = glob.glob(os.path.join(d, "run_log_*.md"))
    assert files, "no run_log markdown written"
    body = open(files[0]).read()
    assert "CARD_DETECTED" in body and "Terminal coverage: 1/1" in body


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



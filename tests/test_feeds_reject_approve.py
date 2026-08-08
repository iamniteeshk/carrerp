"""Feeds-first search, rejected content recheck, and dashboard manual approve."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.linkedin_portal import LinkedInPortal
from careerpilot.browser.naukri_portal import NaukriPortal
from careerpilot.core.enums import JobStatus
from careerpilot.core.models import AIEvaluation, Job
from careerpilot.core.pipeline import ScanPipeline
from careerpilot.dashboard.app import create_dashboard
from careerpilot.db.database import Database
from careerpilot.db.services import (JobService, RETRIABLE_STATUSES,
                                     material_field_changes)


class FakePage:
    def __init__(self, start="about:blank"):
        self.url = start
        self.gotos = []

    def goto(self, url, **kwargs):
        self.url = url
        self.gotos.append(url)

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def wait_for_selector(self, *a, **k):
        pass

    def evaluate(self, script):
        if "innerHeight" in script:
            return 800
        return None

    def query_selector(self, sel):
        return object()

    def query_selector_all(self, sel):
        return []


class FakeSession:
    def __init__(self, page):
        self.page = page
        self.manager = type("M", (), {"cfg": type("C", (), {
            "networkidle_timeout_ms": 10, "render_settle_ms": 0,
            "scroll_passes": 1, "open_jobs": False,
        })()})()
        self.profile_dir = tempfile.mkdtemp()

    def screenshot(self, path):
        return path


def test_linkedin_feeds_before_categories():
    page = FakePage()
    portal = LinkedInPortal(FakeSession(page), candidate=None, easy_apply_only=True)
    portal.search_include_easy_apply_feed = True
    portal.search_include_recommended = True
    portal.search_include_all_feed = True
    portal.search_nationwide = False
    portal._parse_result_cards = lambda p: []
    portal.search(["Director"], ["Chennai"])
    assert "f_AL=true" in page.gotos[0]
    assert "recommended" in page.gotos[1]
    assert page.gotos[2].rstrip("/").endswith("/jobs")
    assert any("keywords=Director" in u and "location=Chennai" in u
               for u in page.gotos)


def test_naukri_easy_apply_and_recommended_dedupe():
    page = FakePage(start="https://www.naukri.com/mnjuser/homepage")
    portal = NaukriPortal(FakeSession(page), candidate=None)
    portal.search_include_easy_apply_feed = True
    portal.search_include_recommended = True
    portal.search_include_all_feed = False
    portal.search_nationwide = False
    portal._parse_result_cards = lambda p: []
    portal.search(["Director"], ["Chennai"])
    # Same URL for easy-apply + recommended → one feed visit, then category.
    feed = [u for u in page.gotos if "recommendedjobs" in u]
    assert len(feed) == 1
    assert "recommendedjobs" in page.gotos[0]
    assert any("jobs-in-chennai" in u for u in page.gotos)


def test_material_field_changes_ignores_empty_new_jd():
    existing = {"job_title": "Director IT", "company": "Acme",
                "location": "Chennai", "salary": "50 LPA",
                "experience": "15", "job_description": "long jd text"}
    job = Job(portal="LinkedIn", company="Acme", job_title="Director IT",
              location="Chennai", salary="50 LPA", experience="15",
              job_description="")  # card has no JD yet
    assert material_field_changes(existing, job) == []
    job.salary = "60 LPA"
    assert material_field_changes(existing, job) == ["salary"]


def test_approve_rejected_job_and_retriable():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        svc = JobService(db)
        j = Job(portal="LinkedIn", company="GoodCo", job_title="Head IT",
                location="Chennai", job_url="https://example.com/j/1",
                job_description="Lead IT for GCC", salary="40 LPA")
        jid = svc.insert(j)
        svc.update_status(jid, JobStatus.REJECTED,
                          rejection_reason="Domain Mismatch")
        assert svc.exists(j)
        assert svc.approve(jid)["status"] == JobStatus.APPROVED.value
        j2 = Job(portal="LinkedIn", company="GoodCo", job_title="Head IT",
                 location="Chennai", job_url="https://example.com/j/1")
        assert not svc.exists(j2)  # APPROVED is retriable / not terminal
        assert JobStatus.APPROVED.value in RETRIABLE_STATUSES
        assert svc.approve(jid) is None  # only REJECTED can be approved
        db.close()


def test_rejected_unchanged_skipped_changed_rechecks():
    """Pipeline skips REJECTED duplicates unless salary/JD/etc. changed."""
    class Jobs:
        def __init__(self):
            self.rows = {}
            self.status_by_id = {}

        def find_existing(self, job):
            return self.rows.get(job.job_url)

        def exists(self, job):
            return job.job_url in self.rows

        def insert(self, job):
            jid = len(self.rows) + 1
            self.rows[job.job_url] = {
                "job_id": jid, "status": "FOUND",
                "job_title": job.job_title, "company": job.company,
                "location": job.location, "salary": job.salary,
                "experience": job.experience,
                "job_description": job.job_description,
            }
            job.job_id = jid
            return jid

        def update_status(self, jid, status, rejection_reason=None, **kw):
            self.status_by_id[jid] = (status, rejection_reason)
            for row in self.rows.values():
                if row["job_id"] == jid:
                    row["status"] = status.value if hasattr(status, "value") else status
                    if rejection_reason is not None:
                        row["rejection_reason"] = rejection_reason

        def update_material_fields(self, jid, job):
            for row in self.rows.values():
                if row["job_id"] == jid:
                    row["salary"] = job.salary
                    row["job_description"] = job.job_description or row.get(
                        "job_description", "")

    class Stream:
        def found(self, *a, **k): pass
        def rejected(self, *a, **k): pass
        def selected(self, *a, **k): pass
        def matched(self, *a, **k): pass
        def applied(self, *a, **k): pass
        def failed(self, *a, **k): pass

    class Rules:
        def evaluate(self, job):
            return type("R", (), {"accepted": False,
                                  "reason": type("E", (), {"value": "Domain Mismatch"})()})()

    p = ScanPipeline.__new__(ScanPipeline)
    p.jobs = Jobs()
    p.stream = Stream()
    p.rules = Rules()
    p.failed_jobs = type("F", (), {"record": lambda *a, **k: None})()
    p.ai = None
    p.apply_engine = None
    p.notifier = None
    p._run_log = []
    p._job_seq = 0
    p._found = 0
    p._status = lambda **k: None
    p._metric = lambda *a, **k: None
    p._stage = lambda *a, **k: None
    p._session_limit_reached = lambda: False
    p.min_match_score = 0

    url = "https://example.com/recheck/1"
    job = Job(portal="LinkedIn", company="Acme", job_title="Director",
              location="Chennai", salary="40 LPA", job_url=url,
              job_description="full jd here", read_status="COMPLETE",
              is_easy_apply=True)
    jid = p.jobs.insert(job)
    p.jobs.update_status(jid, JobStatus.REJECTED, rejection_reason="Domain Mismatch")
    p.jobs.rows[url]["status"] = "REJECTED"
    p.jobs.rows[url]["salary"] = "40 LPA"
    p.jobs.rows[url]["job_description"] = "full jd here"

    counts = {"found": 0, "rejected": 0, "matched": 0, "applied": 0, "skipped": 0}
    same = Job(portal="LinkedIn", company="Acme", job_title="Director",
               location="Chennai", salary="40 LPA", job_url=url,
               job_description="full jd here", read_status="COMPLETE")
    p._process_job(same, counts, dry_run=True)
    assert counts["skipped"] == 1

    changed = Job(portal="LinkedIn", company="Acme", job_title="Director",
                  location="Chennai", salary="55 LPA", job_url=url,
                  job_description="full jd here UPDATED", read_status="COMPLETE")
    # Will re-enter rules and reject again — proves recheck ran (not skip).
    counts2 = {"found": 0, "rejected": 0, "matched": 0, "applied": 0, "skipped": 0}
    p._process_job(changed, counts2, dry_run=True)
    assert counts2["skipped"] == 0
    assert counts2["found"] == 1
    assert counts2["rejected"] == 1


def test_manual_approval_applies_on_pipeline_pass():
    class Jobs:
        def __init__(self, rows):
            self._rows = rows
            self.status_by_id = {}

        def list_by_status(self, status):
            return [r for r in self._rows
                    if r["status"] == (status.value if hasattr(status, "value")
                                       else status)]

        def job_from_row(self, row):
            return JobService.job_from_row(row)

        def update_status(self, jid, status, **kw):
            self.status_by_id[jid] = status

    class ApplyEngine:
        def __init__(self):
            self.calls = []

        def dry_run(self, job, evaluation):
            self.calls.append(("dry", job.job_id, evaluation.reason))
            return type("R", (), {"success": True, "status": JobStatus.MATCHED})()

        def apply_to_job(self, job, evaluation):
            self.calls.append(("live", job.job_id))
            return type("R", (), {"success": True, "status": JobStatus.APPLIED})()

    row = {
        "job_id": 9, "portal": "LinkedIn", "company": "Acme",
        "job_title": "Head IT", "location": "Chennai", "salary": "50",
        "experience": "15", "employment_type": "", "shift": "",
        "job_url": "https://example.com/approved/1",
        "job_description": "Lead digital workplace", "is_easy_apply": 1,
        "status": "APPROVED", "match_score": 88, "selected_resume": "General",
        "rejection_reason": "Low Match Score", "source_id": "", "reading_ms": 0,
    }
    p = ScanPipeline.__new__(ScanPipeline)
    p.jobs = Jobs([row])
    p.apply_engine = ApplyEngine()
    p.stream = type("S", (), {"applied": lambda *a, **k: None})()
    p.cfg = type("C", (), {"default_career_profile": "General"})()
    p._run_log = []
    p._job_seq = 0
    p._found = 0
    p._stage = lambda *a, **k: None
    p._session_limit_reached = lambda: False
    counts = {"found": 0, "matched": 0, "applied": 0}
    p._process_manual_approvals(counts, dry_run=True)
    assert p.apply_engine.calls and p.apply_engine.calls[0][0] == "dry"
    assert counts["applied"] == 1
    assert counts["matched"] == 1


def test_dashboard_approve_requires_admin():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        svc = JobService(db)
        j = Job(portal="Naukri", company="Co", job_title="Director EUC",
                location="Chennai", job_url="https://example.com/d/1",
                job_description="EUC leadership")
        jid = svc.insert(j)
        svc.update_status(jid, JobStatus.REJECTED, rejection_reason="test")
        app = create_dashboard(db, refresh_seconds=5)
        client = app.test_client()
        # Public can list rejected
        r = client.get("/api/rejected")
        assert r.status_code == 200
        assert r.get_json()[0]["job_title"] == "Director EUC"
        # Approve without login → 401
        r = client.post(f"/api/jobs/{jid}/approve")
        assert r.status_code == 401
        # Login then approve
        os.environ["DASHBOARD_USER"] = "Admin"
        os.environ["DASHBOARD_PASSWORD"] = "Adming"
        r = client.post("/login", data={"username": "Admin", "password": "Adming"},
                        follow_redirects=False)
        assert r.status_code in (302, 200)
        r = client.post(f"/api/jobs/{jid}/approve")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["job"]["status"] == "APPROVED"
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

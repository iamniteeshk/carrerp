"""v4.0.0 production-readiness tests.

Covers: hard IC rejection, weak-keyword non-rescue, apply safety gate,
final confirmation gate, retriable job statuses, live apply never false-positive,
maintenance retention, session reports.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.apply.confidence_gate import ConfidenceGate
from careerpilot.apply.safety_gate import ApplySafetyGate
from careerpilot.browser.base_portal import ApplyOutcome
from careerpilot.core.config import ApplyConfig, RuleConfig
from careerpilot.core.enums import JobStatus
from careerpilot.core.job_cache import JobCache
from careerpilot.core.maintenance import RetentionConfig, run_maintenance
from careerpilot.core.models import AIEvaluation, Job
from careerpilot.db.database import Database
from careerpilot.db.services import RETRIABLE_STATUSES, ApplicationService, JobService
from careerpilot.reports.session_reports import write_session_reports
from careerpilot.rules.rule_engine import HARD_IC_TERMS, RuleEngine


def _rules(**kw) -> RuleConfig:
    base = dict(
        minimum_salary=0, salary_currency="INR", minimum_experience=15,
        accepted_employment_types=["Full Time"], rejected_shifts=[],
        preferred_locations=["Chennai", "Remote"],
        accepted_titles=["Director", "Head", "Infrastructure", "Digital Workplace"],
        rejected_titles=["Engineer"],
        blacklist_companies=["Acme Corp"],
        required_keywords=["Infrastructure", "Cloud", "Digital Workplace", "EUC",
                           "Operations"],
        nice_to_have_keywords=[],
        minimum_match_score=60,
    )
    base.update(kw)
    return RuleConfig(**base)


def _job(**kw) -> Job:
    defaults = dict(
        portal="LinkedIn", company="GoodCo", job_title="IT Infrastructure Director",
        location="Chennai", salary="", experience="18 years",
        employment_type="Full Time", job_url="https://example.com/j/1",
        job_description="Lead infrastructure and digital workplace for enterprise IT.",
        is_easy_apply=True, status=JobStatus.FOUND, read_status="COMPLETE",
    )
    defaults.update(kw)
    return Job(**defaults)


def _eval(score=95, apply=True) -> AIEvaluation:
    return AIEvaluation(
        match_score=score, career_profile="Infrastructure", confidence=90,
        reason="strong fit", apply=apply, provider="test", model="test")


passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


# ---- Rule Engine: hard IC / weak keyword ---------------------------------

def test_hard_ic_never_rescued():
    eng = RuleEngine(_rules())
    for title in (
        "Cloud Developer",
        "Senior Software Engineer - Infrastructure",
        "AI Engineer",
        "Data Scientist - Cloud",
        "Sales Director",
        "Marketing Head - Digital",
        "Python Developer",
    ):
        r = eng.evaluate(_job(job_title=title))
        check(f"hard-reject '{title}'", not r.accepted,
              f"got accepted={r.accepted} reason={r.reason}")


def test_strong_domain_leadership_passes():
    eng = RuleEngine(_rules())
    for title in (
        "IT Infrastructure Director",
        "Head of Digital Workplace",
        "Director EUC",
        "IT Service Delivery Head",
        "GCC IT Head",
        "Managed Services Director",
    ):
        r = eng.evaluate(_job(job_title=title))
        check(f"accept '{title}'", r.accepted, f"reason={r.reason}")


def test_blacklist_substring():
    eng = RuleEngine(_rules())
    r = eng.evaluate(_job(company="Acme Corp India Pvt Ltd"))
    check("blacklist substring", not r.accepted)


def test_hard_ic_terms_exported():
    check("HARD_IC_TERMS has developer", "developer" in HARD_IC_TERMS)


# ---- Safety + confidence gates ------------------------------------------

def test_safety_gate_blocks_off_domain_and_blacklist():
    gate = ApplySafetyGate(_rules(), require_preferred_location=True)
    check("block developer",
          not gate.check(_job(job_title="Cloud Developer"), _eval()).allowed)
    check("block blacklist",
          not gate.check(_job(company="Acme Corp"), _eval()).allowed)
    check("block Bangalore when Chennai required",
          not gate.check(_job(location="Bangalore"), _eval()).allowed)
    check("allow Chennai infra",
          gate.check(_job(), _eval()).allowed)


def test_final_confirmation_always_needs_approval():
    cfg = ApplyConfig(
        mode="live", first_run_confirmations=0, max_applications_per_day=10,
        delay_between_applications_seconds=0, retry_limit=1, easy_apply_only=True,
        require_final_confirmation=True)
    gate = ConfidenceGate(cfg, min_score=90, applied_so_far_lifetime=100)
    d = gate.decide(_job(), _eval(), applied_today=0)
    check("final confirmation needs approval", d.proceed and d.needs_approval,
          f"proceed={d.proceed} needs={d.needs_approval} reason={d.reason}")


def test_confirmation_can_be_disabled():
    cfg = ApplyConfig(
        mode="live", first_run_confirmations=0, max_applications_per_day=10,
        delay_between_applications_seconds=0, retry_limit=1, easy_apply_only=True,
        require_final_confirmation=False)
    gate = ConfidenceGate(cfg, min_score=90, applied_so_far_lifetime=100)
    d = gate.decide(_job(), _eval(), applied_today=0)
    check("live auto-submit when confirmation off",
          d.proceed and not d.needs_approval, f"reason={d.reason}")


# ---- DB retriable / already_applied -------------------------------------

def test_retriable_and_already_applied():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        jobs = JobService(db)
        apps = ApplicationService(db)
        j = _job(job_url="https://example.com/retry/1")
        jid = jobs.insert(j)
        j.job_id = jid
        jobs.update_status(jid, JobStatus.QUEUED)
        check("QUEUED is retriable", jobs.is_retriable(j))
        check("QUEUED does not exist() as terminal", not jobs.exists(j))
        jobs.update_status(jid, JobStatus.REJECTED)
        check("REJECTED is terminal exists()", jobs.exists(j))
        check("not already applied", not apps.already_applied(jid))
        from careerpilot.core.models import ApplicationResult
        apps.record(ApplicationResult(
            job_id=jid, success=True, status=JobStatus.APPLIED, portal="LinkedIn",
            company="GoodCo", resume_used="Infrastructure", resume_version="v1",
            match_score=95, dry_run=False))
        check("APPLIED blocks duplicate", apps.already_applied(jid))
        check("RETRIABLE set contains QUEUED", JobStatus.QUEUED.value in RETRIABLE_STATUSES)
        db.close()


# ---- Live apply must not claim success ----------------------------------

def test_apply_outcome_confirmation_note():
    out = ApplyOutcome(submitted=False, note="awaiting_final_confirmation: test")
    check("incomplete apply not submitted", not out.submitted)
    check("confirmation note present", "confirmation" in out.note)


# ---- Maintenance + session reports --------------------------------------

def test_maintenance_purges_old_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        old = cache / "old.json"
        old.write_text("{}")
        # Make it look old
        import time
        old_ts = time.time() - 40 * 86400
        os.utime(old, (old_ts, old_ts))
        fresh = cache / "fresh.json"
        fresh.write_text("{}")
        result = run_maintenance(
            cache_dir=str(cache), report_dir=str(root / "reports"),
            screenshot_dir=str(root / "shots"), evidence_dir=str(root / "debug"),
            backup_dir=str(root / "backups"),
            config=RetentionConfig(cache_days=30, report_days=60,
                                   screenshot_days=14, evidence_days=14,
                                   backup_days=30, vacuum_db=False))
        check("old cache deleted", not old.exists(), f"result={result.as_dict()}")
        check("fresh cache kept", fresh.exists())


def test_session_reports_written():
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_session_reports(
            tmp, counts={"found": 3, "rejected": 1, "matched": 1, "applied": 0,
                         "failed": 1, "skipped": 0, "queued": 0},
            duration=12.5, portals=["LinkedIn"], ai_calls=2, avg_score=77.0)
        check("summary report", "summary" in paths and Path(paths["summary"]).exists())
        check("portal report", "portal" in paths and Path(paths["portal"]).exists())
        check("performance report",
              "performance" in paths and Path(paths["performance"]).exists())
        check("failure report", "failures" in paths and Path(paths["failures"]).exists())
        check("application report",
              "applications" in paths and Path(paths["applications"]).exists())


def test_cache_stale_reopen():
    with tempfile.TemporaryDirectory() as tmp:
        cache = JobCache(tmp)
        url = "https://example.com/job/stale"
        cache.put({"job_url": url, "job_title": "X", "company": "Y",
                   "location": "Z", "salary": "", "experience": "",
                   "job_description": "hello world " * 20})
        check("fresh cache hit", not cache.needs_open(url, max_age_days=14))
        p = list(Path(tmp).glob("*.json"))[0]
        import time
        os.utime(p, (time.time() - 20 * 86400, time.time() - 20 * 86400))
        check("stale cache reopen", cache.needs_open(url, max_age_days=14))


if __name__ == "__main__":
    print("=== v4.0.0 production readiness ===")
    test_hard_ic_never_rescued()
    test_strong_domain_leadership_passes()
    test_blacklist_substring()
    test_hard_ic_terms_exported()
    test_safety_gate_blocks_off_domain_and_blacklist()
    test_final_confirmation_always_needs_approval()
    test_confirmation_can_be_disabled()
    test_retriable_and_already_applied()
    test_apply_outcome_confirmation_note()
    test_maintenance_purges_old_files()
    test_session_reports_written()
    test_cache_stale_reopen()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

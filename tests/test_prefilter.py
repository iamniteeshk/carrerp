"""Tests for the card pre-filter (open/skip) — v2.8.7 search-narrowing fix."""
from __future__ import annotations
import os, sys, types
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from careerpilot.core.models import Job
from careerpilot.core.enums import JobStatus


class _RuleCfg:
    minimum_salary = 0; salary_currency = "INR"; minimum_experience = 0
    accepted_employment_types = []; rejected_shifts = []; preferred_locations = []
    accepted_titles = ["director", "head", "infrastructure", "euc", "gcc",
                       "digital workplace", "contact centre"]
    rejected_titles = []   # rely on the built-in off-domain denylist
    blacklist_companies = []; required_keywords = []; nice_to_have_keywords = []


def test_prefilter_skips_clearly_offdomain_titles():
    from careerpilot.rules.rule_engine import RuleEngine
    r = RuleEngine(_RuleCfg())
    # The built-in off-domain denylist skips obvious non-IT-leadership roles.
    for bad in ("Chief Financial Officer (CFO)", "Regional Sales Manager",
                "Finance Controller", "Plant Maintenance Manager",
                "Senior Legal Counsel", "Construction Site Supervisor"):
        assert r.prefilter(Job(portal="naukri", job_title=bad)).accepted is False


def test_prefilter_skips_ai_ml_titles_despite_leadership_word():
    """v3.0.0: 'Director - AI' / ML / data-science titles must be skipped at the
    card stage even though they contain a leadership word."""
    from careerpilot.rules.rule_engine import RuleEngine
    r = RuleEngine(_RuleCfg())
    for bad in ("Director - AI", "Director - AI/ML", "Head of Machine Learning",
                "Head of Data Science", "AI Research Director"):
        assert r.prefilter(Job(portal="naukri", job_title=bad)).accepted is False


def test_prefilter_opens_target_titles():
    from careerpilot.rules.rule_engine import RuleEngine
    r = RuleEngine(_RuleCfg())
    for good in ("Director - IT Infrastructure", "Head of Digital Workplace",
                 "GCC Centre Head", "Director EUC & Contact Centre"):
        assert r.prefilter(Job(portal="naukri", job_title=good)).accepted is True


def test_prefilter_is_fail_open_for_ambiguous_titles():
    """CRITICAL: a title that is neither clearly off-domain nor an exact accepted
    phrase must STILL be opened (judged on the full JD). Requiring an accepted
    match here was the root cause of 'never opened'."""
    from careerpilot.rules.rule_engine import RuleEngine
    r = RuleEngine(_RuleCfg())
    for amb in ("Senior Manager - Technology Operations", "VP Engineering",
                "Service Delivery Lead", "Some Ambiguous Role"):
        assert r.prefilter(Job(portal="naukri", job_title=amb)).accepted is True


def test_pipeline_rejects_skipped_prefilter_card_terminally():
    """A card marked SKIPPED_PREFILTER must end as REJECTED (not opened, not
    stranded, never sent to Rule/AI)."""
    from careerpilot.core.pipeline import ScanPipeline
    # reuse the harness fakes from test_read_gate
    import tests.test_read_gate as g
    p = g._pipeline()
    counts = g._counts()
    card = Job(portal="naukri", job_title="CFO", job_url="u",
               read_status="SKIPPED_PREFILTER")
    p._process_job(card, counts, dry_run=True)
    assert counts["rejected"] == 1 and counts["matched"] == 0
    assert counts["failed"] == 0                 # skip-open is a reject, not a fail
    assert p.rules.called_with == [] and p.ai.called == 0
    assert p.jobs.status_by_id[1][0] == JobStatus.REJECTED


def test_naukri_search_url_has_experience_filter():
    from careerpilot.browser.naukri_portal import NaukriPortal
    np = NaukriPortal.__new__(NaukriPortal)
    url = NaukriPortal._search_url(np, "it infrastructure director", "chennai")
    assert "experience=" in url and "chennai" in url


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try: fn(); passed += 1; print(f"PASS {name}")
            except Exception: failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

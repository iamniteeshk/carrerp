"""Tests for the Portal Completion Checklist (v2.9.0)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.diagnostics import portal_checklist as pc
from careerpilot.diagnostics.portal_checklist import State


def test_checklists_cover_user_specified_items():
    cls = pc.build_checklists()
    ln = [i.name for i in cls["linkedin"].items]
    nk = [i.name for i in cls["naukri"].items]
    # LinkedIn has Recommended jobs; Naukri does not (per the spec).
    assert "Recommended jobs" in ln and "Recommended jobs" not in nk
    for must in ("Login detection", "Session persistence", "Search", "Filters",
                 "Job card parsing", "Job detail extraction",
                 "Rule Engine integration", "AI integration", "Apply workflow",
                 "Resume upload", "Stability", "Recovery", "Diagnostics coverage"):
        assert must in ln and must in nk, must


def test_every_item_has_a_valid_state():
    for cl in pc.build_checklists().values():
        for i in cl.items:
            assert isinstance(i.state, State)


def test_score_is_weighted_percentage():
    cls = pc.build_checklists()
    s = cls["linkedin"].score()
    assert 0 <= s <= 100
    # baseline is partial (foundations tested, live items pending), not 100.
    assert 30 <= s <= 70


def test_baseline_filters_not_started_diagnostics_ready():
    ln = pc.build_checklists()["linkedin"]
    assert ln.get("Filters").state == State.NOT_STARTED
    assert ln.get("Diagnostics coverage").state == State.PRODUCTION_READY


def test_evidence_promotes_items_from_session_report():
    with tempfile.TemporaryDirectory() as tmp:
        # A real run produced jobs, AI matches and an application.
        (Path(tmp) / "session_report_1.json").write_text(json.dumps({
            "counts": {"found": 20, "matched": 8, "applied": 1}}))
        cls = pc.apply_evidence(pc.build_checklists(), tmp)
        ln = cls["linkedin"]
        assert ln.get("Search").state == State.TESTED            # found>0
        assert ln.get("Job card parsing").state == State.TESTED
        assert ln.get("AI integration").state == State.TESTED    # matched>0
        assert ln.get("Apply workflow").state == State.TESTED     # applied>0
        assert ln.get("Resume upload").state == State.TESTED


def test_evidence_promotes_detail_extraction_from_job_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        jdir = Path(tmp) / "session" / "naukri" / "jobs" / "job_001"
        jdir.mkdir(parents=True)
        (jdir / "parsed.json").write_text(json.dumps(
            [{"job_title": "Director", "job_description": "Lead the org. " * 20}]))
        cls = pc.apply_evidence(pc.build_checklists(), tmp)
        # already Tested at baseline; evidence keeps it Tested (note updates)
        assert cls["naukri"].get("Job detail extraction").state == State.TESTED


def test_promotion_never_demotes():
    cls = pc.build_checklists()
    ln = cls["linkedin"]
    ln.get("Diagnostics coverage").promote_to(State.IN_PROGRESS, "should not drop")
    assert ln.get("Diagnostics coverage").state == State.PRODUCTION_READY


def test_render_markdown_has_overall_and_portals():
    md = pc.render_markdown(pc.build_checklists())
    assert "Portal Completion Checklist" in md
    assert "Overall portal completion" in md
    assert "LinkedIn" in md and "Naukri" in md


def test_generate_writes_file_and_returns_scores():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "checklist.md"
        result = pc.generate(debug_dir=tmp, write_to=out)
        assert out.exists()
        assert "overall" in result
        assert set(result["portals"]) == {"linkedin", "naukri"}



def test_coverage_percentages_present_and_sane():
    cl = pc.build_checklists()["linkedin"]
    cov = cl.coverage()
    for k in ("started_pct", "tested_or_better_pct", "production_ready_pct",
              "evidence_coverage_pct", "items_total"):
        assert k in cov
    assert 0 <= cov["tested_or_better_pct"] <= 100
    assert cov["evidence_coverage_pct"] == 0   # baseline has no live evidence yet


def test_quantitative_metrics_from_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "session_report_1.json").write_text(json.dumps({
            "counts": {"found": 20, "rejected": 12, "matched": 8, "applied": 2}}))
        jdir = Path(tmp) / "session" / "naukri" / "jobs" / "job_001"
        jdir.mkdir(parents=True)
        (jdir / "parsed.json").write_text(json.dumps(
            [{"job_title": "Director", "job_description": "Lead. " * 30}]))
        cls = pc.apply_evidence(pc.build_checklists(), tmp)
        m = pc.quantitative_metrics(cls, tmp)
        assert m["run"]["match_rate_pct"] == 40      # 8/20
        assert m["run"]["apply_rate_pct"] == 10      # 2/20
        assert m["run"]["session_reports"] == 1
        assert m["portals"]["naukri"]["jobs_with_full_jd"] == 1
        assert m["portals"]["naukri"]["jd_capture_rate_pct"] == 100
        # evidence raised live-evidence coverage above zero
        assert cls["naukri"].coverage()["evidence_coverage_pct"] > 0


def test_items_track_evidence_count_and_timestamp():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "session_report_1.json").write_text(json.dumps({
            "counts": {"found": 5, "matched": 1, "applied": 0}}))
        cls = pc.apply_evidence(pc.build_checklists(), tmp)
        search = cls["linkedin"].get("Search")
        assert search.evidence_count >= 1
        assert search.last_verified  # timestamp recorded

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

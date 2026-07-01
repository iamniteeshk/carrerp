"""Tests for v2.8.1 autonomous diagnostics: every analyzer plugin + session
report + plugin registry."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.diagnostics.analyzers import (
    FailureAnalyzer, SelectorAnalyzer, DomDiffAnalyzer, HumanBehaviourAnalyzer,
    PerformanceAnalyzer, TimelineAnalyzer, default_analyzers)
from careerpilot.diagnostics.analyzers.base import Analyzer, AnalysisResult
from careerpilot.diagnostics.session_report import SessionReporter
from careerpilot.diagnostics.metrics import RunMetrics


# ---- #1/#4 failure & navigation -----------------------------------------

def test_failure_analyzer_ranks_captcha_first():
    r = FailureAnalyzer().analyze({"signals": {
        "has_captcha": True, "has_login_form": True, "url": "x/login"}})
    assert r.severity == "error"
    assert "CAPTCHA" in r.summary
    causes = [c["cause"] for c in r.data["ranked_causes"]]
    assert causes[0].startswith("CAPTCHA")          # ranked highest


def test_failure_analyzer_zero_results_suggests_dom_check():
    r = FailureAnalyzer().analyze({"signals": {
        "results_count": 0, "expected_results": True, "networkidle_reached": True}})
    assert any("DOM" in f or "zero" in f.lower() for f in r.findings)
    assert any("Selector" in rec or "DOM Diff" in rec for rec in r.recommendations)


def test_failure_analyzer_no_signals_is_info():
    r = FailureAnalyzer().analyze({"signals": {}})
    assert r.severity == "info"


# ---- #2 selector learning -----------------------------------------------

def test_selector_analyzer_suggests_closest():
    r = SelectorAnalyzer().analyze({
        "expected_selector": "div.job-card",
        "candidates": [
            {"selector": ".srp-jobtuple-wrapper", "count": 22, "sample_text": "Dir"},
            {"selector": ".footer-link", "count": 2, "sample_text": "About"},
            {"selector": ".job-card-shell", "count": 20, "sample_text": "Dir"}]})
    # The token-similar, plausibly-counted candidate should win.
    assert r.data["closest"]["selector"] == ".job-card-shell"
    assert "CONSIDER replacing" in r.recommendations[0]
    # never auto-applies
    assert "not auto-applied" in r.recommendations[0]


# ---- #3 DOM diff ---------------------------------------------------------

def test_dom_diff_detects_broken_selector_and_renamed_class():
    base = {"tag_counts": {"div": 100}, "classes": {"job-card": 22},
            "selector_counts": {"job_card": 22}}
    cur = {"tag_counts": {"div": 100}, "classes": {"srp-jobtuple-wrapper": 22},
           "selector_counts": {"job_card": 0}}
    r = DomDiffAnalyzer().analyze({"baseline_snapshot": base,
                                   "current_snapshot": cur})
    assert r.severity == "error"
    assert any("22 -> 0" in f for f in r.findings)
    assert any("srp-jobtuple-wrapper" in f for f in r.findings)


def test_dom_diff_no_change_is_info():
    snap = {"tag_counts": {"div": 10}, "classes": {"a": 1},
            "selector_counts": {"job_card": 5}}
    r = DomDiffAnalyzer().analyze({"baseline_snapshot": snap,
                                   "current_snapshot": dict(snap)})
    assert r.severity == "info"


# ---- #5 human behaviour score -------------------------------------------

def test_human_score_rewards_varied_realistic_interactions():
    events = []
    t = 0.0
    for i in range(20):
        t += 0.3 + (i % 5) * 0.2
        events.append({"t": t, "kind": "mouse_move", "x": i, "y": i})
    for i in range(4):
        t += 1.5 + i
        events.append({"t": t, "kind": "scroll", "y": 300 + i * 120})
    r = HumanBehaviourAnalyzer().analyze({"events": events})
    assert 0 <= r.data["score"] <= 100
    assert r.data["subscores"]["mouse_realism"] > 50


def test_human_score_no_events_is_info():
    r = HumanBehaviourAnalyzer().analyze({"events": []})
    assert r.severity == "info"


# ---- #6 performance ------------------------------------------------------

def test_performance_flags_bottlenecks():
    m = {"jobs_opened": 10, "jobs_parsed": 2, "timeouts": 3, "avg_ai_ms": 12000}
    r = PerformanceAnalyzer().analyze({"metrics": m})
    assert r.severity == "warning"
    assert any("timeout" in b.lower() for b in r.data["bottlenecks"])
    assert any("parse yield" in b.lower() for b in r.data["bottlenecks"])


# ---- #8 timeline ---------------------------------------------------------

def test_timeline_builds_milestones_only():
    events = [{"t": 1, "kind": "navigate", "url": "x/jobs"},
              {"t": 2, "kind": "mouse_move", "x": 1, "y": 1},  # skipped
              {"t": 3, "kind": "transition", "state": "RESULTS_VISIBLE"},
              {"t": 65, "kind": "wait", "reason": "render", "ms": 800}]
    r = TimelineAnalyzer().analyze({"events": events})
    assert r.data["milestone_count"] == 3       # mouse_move excluded
    assert any("00:01:05" in line for line in r.data["timeline"])  # clock fmt


# ---- #9 plugin registry --------------------------------------------------

def test_custom_analyzer_plugs_in_without_core_change():
    class MyAnalyzer(Analyzer):
        name = "Custom"
        def analyze(self, ctx):
            return AnalysisResult(self.name, summary="custom ran", severity="info")
    with tempfile.TemporaryDirectory() as tmp:
        rep = SessionReporter(base_dir=tmp, analyzers=[])
        rep.register(MyAnalyzer())
        results = rep.run_analyzers({})
        assert results[0].summary == "custom ran"


def test_default_analyzer_set_has_all_six():
    assert len(default_analyzers()) == 6


# ---- #7 session report ---------------------------------------------------

def test_session_report_written_with_findings():
    with tempfile.TemporaryDirectory() as tmp:
        m = RunMetrics()
        m.searches = ["Director"]; m.locations = ["Chennai"]
        m.jobs_parsed = 20; m.jobs_opened = 20; m.timeouts = 1
        m.incr("selectors_failed", 2)
        rep = SessionReporter(base_dir=tmp)
        path = rep.generate(metrics=m.as_dict(),
                            counts={"found": 20, "rejected": 12, "matched": 8,
                                    "applied": 0})
        text = Path(path).read_text()
        assert "Session Report" in text
        assert "Jobs discovered: 20" in text
        assert "Analyzer findings" in text
        assert Path(path.replace(".md", ".json")).exists()


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

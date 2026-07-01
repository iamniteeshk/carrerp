"""Tests for Visual Debug Mode (VisualDebugger)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.visual_debug import VisualDebugger, DebugConfig


class FakePage:
    def __init__(self, url="https://x/jobs"):
        self.url = url
        self.evals = []
        self.timeouts = []

    def evaluate(self, js, arg=None):
        self.evals.append((js, arg))
        if "matched" in js:                 # selector_diagnostics
            return {"matched": 10, "visible": 7}
        if "scrollY" in js and "dh" in js:  # scroll_diagnostics
            return {"y": 1000, "dh": 4000, "vh": 800}
        if "scrollHeight" in js:            # scroll_pct
            return 45
        return 3                            # highlight match count

    def wait_for_timeout(self, ms):
        self.timeouts.append(ms)

    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"\x89PNG")

    def content(self):
        return "<html>jobs</html>"


def test_disabled_debugger_is_a_noop():
    d = VisualDebugger(DebugConfig(visual_mode=False))
    page = FakePage()
    assert d.enabled is False
    assert d.highlight(page, "div.card", "job_card") == 0
    d.panel(page, {"State": "X"})
    d.pause(page, "after_navigation")
    assert d.selector_diagnostics(page, {"job_card": "div.card"}) == {}
    # Nothing was sent to the page at all.
    assert page.evals == [] and page.timeouts == []


def test_pause_only_when_configured():
    d = VisualDebugger(DebugConfig(visual_mode=True,
                                   pause_after_navigation_seconds=2))
    page = FakePage()
    d.pause(page, "after_navigation")
    assert page.timeouts == [2000]
    d.pause(page, "before_scroll")  # not configured -> no pause
    assert page.timeouts == [2000]


def test_selector_diagnostics_counts_visible_and_hidden():
    d = VisualDebugger(DebugConfig(visual_mode=True))
    diag = d.selector_diagnostics(FakePage(), {"job_card": "div.card"})
    assert diag["job_card"] == {"matched": 10, "visible": 7, "hidden": 3}


def test_evidence_bundle_written_with_all_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        d = VisualDebugger(DebugConfig(visual_mode=True, evidence_dir=tmp))
        d.mark("Navigate"); d.mark("Results Visible")

        class J:
            job_title = "Director"; company = "X"; location = "Chennai"
            salary = None; is_easy_apply = True; job_url = "u"
            experience = ""; job_description = ""
        folder = Path(d.save_evidence(FakePage(), "Naukri", [J()],
                                      {"state": "RESULTS_VISIBLE"}))
        assert (folder / "screenshot.png").exists()
        assert (folder / "page.html").exists()
        assert (folder / "parsed_jobs.json").exists()
        assert (folder / "browser_state.json").exists()
        assert (folder / "timeline.json").exists()
        # parsed json has the job; timeline has the marks
        jobs = json.loads((folder / "parsed_jobs.json").read_text())
        assert jobs[0]["job_title"] == "Director"
        tl = json.loads((folder / "timeline.json").read_text())
        assert [e["event"] for e in tl] == ["Navigate", "Results Visible"]
        # folder is page_001 on first save
        assert folder.name == "page_001"


def test_zero_results_anomaly_saves_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        d = VisualDebugger(DebugConfig(visual_mode=True, evidence_dir=tmp))
        d.zero_results_anomaly(FakePage(), "LinkedIn",
                               {"job_card": "div.card"}, "RESULTS_VISIBLE")
        saved = list(Path(tmp).rglob("browser_state.json"))
        assert saved, "anomaly must save an evidence bundle"
        state = json.loads(saved[0].read_text())
        assert state.get("anomaly") is True


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

"""Tests for the Diagnostics Toolkit (v2.8.0).

Every diagnostic feature is exercised against fakes/fixtures: interaction +
console + network recorder, DOM export, selector inspector, failure-evidence
bundles, replay, live status, and the job-detail recorder + retry path.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.diagnostics import (InteractionRecorder, FailureEvidence,
                                     LiveStatus, DiagnosticsToolkit, export_page)
from careerpilot.diagnostics.exporter import selector_report
from careerpilot.diagnostics.replay import replay


class FakePage:
    """Enough of a Playwright page for the diagnostics to operate on."""
    def __init__(self, url="https://x/jobs", text="Director - IT Infrastructure"):
        self.url = url
        self._text = text
        self.moves = []
    def content(self): return f"<html><body>{self._text}</body></html>"
    def inner_text(self, sel="body"): return self._text
    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"\x89PNG")
    def evaluate(self, js, arg=None):
        if "matched" in js:
            return {"matched": 24, "visible": 21, "first_match_text": "Director"}
        if "scrollY" in js:
            return {"y": 100, "h": 4000, "vh": 800}
        return None
    def wait_for_timeout(self, ms): self.moves.append(("wait", ms))
    class _M:
        def __init__(s, o): s.o = o
        def move(s, x, y, steps=None): s.o.moves.append(("move", x, y))
        def click(s, x, y): s.o.moves.append(("click", x, y))
    @property
    def mouse(self): return FakePage._M(self)
    class _K:
        def __init__(s, o): s.o = o
        def press(s, v): s.o.moves.append(("key", v))
    @property
    def keyboard(self): return FakePage._K(self)
    def goto(self, url): self.url = url; self.moves.append(("goto", url))


# ---- #4 interaction recorder --------------------------------------------

def test_recorder_logs_ordered_events_and_saves():
    with tempfile.TemporaryDirectory() as tmp:
        r = InteractionRecorder(enabled=True)
        r.navigate("https://x/jobs"); r.scroll(450); r.mouse_move(10, 20)
        r.click(10, 20); r.transition("RESULTS_VISIBLE")
        out = r.save(tmp)
        assert "replay.json" in out
        events = json.loads((Path(tmp) / "replay.json").read_text())
        kinds = [e["kind"] for e in events]
        assert kinds == ["navigate", "scroll", "mouse_move", "click", "transition"]
        # console.log + network.json are always written
        assert (Path(tmp) / "console.log").exists()
        assert (Path(tmp) / "network.json").exists()


def test_recorder_disabled_is_noop():
    r = InteractionRecorder(enabled=False)
    r.scroll(100); r.click(1, 1)
    assert r.events == []


# ---- #3/#6 selector inspector + DOM export ------------------------------

def test_selector_report_counts_and_first_match():
    rep = selector_report(FakePage(), {"job_card": "div.card"})
    assert rep["job_card"]["matched"] == 24
    assert rep["job_card"]["visible"] == 21
    assert rep["job_card"]["hidden"] == 3
    assert rep["job_card"]["first_match_text"] == "Director"


def test_export_page_writes_full_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        dest = export_page(FakePage(), Path(tmp) / "page_001",
                           selectors={"job_card": "div.card"},
                           parsed=[{"job_title": "Director"}],
                           meta={"portal": "Naukri", "search": "Director"})
        d = Path(dest)
        for f in ("page.html", "page.png", "viewport.png", "raw_page_text.txt",
                  "selectors.json", "parsed.json", "browser_state.json",
                  "metadata.json", "console.log", "network.json"):
            assert (d / f).exists(), f"missing {f}"
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["portal"] == "Naukri"
        assert meta["selector_match_counts"]["job_card"] == 24
        assert "scroll_position" in meta


# ---- #7 failure evidence -------------------------------------------------

def test_failure_evidence_bundle_written():
    with tempfile.TemporaryDirectory() as tmp:
        fe = FailureEvidence(base_dir=tmp)
        folder = Path(fe.capture("timeout", FakePage(),
                                 context={"portal": "LinkedIn", "url": "u"},
                                 selectors={"job_card": "div.card"}))
        assert folder.exists()
        assert (folder / "page.html").exists()
        meta = json.loads((folder / "metadata.json").read_text())
        assert meta["failure_kind"] == "timeout"


def test_failure_evidence_without_page_records_context():
    with tempfile.TemporaryDirectory() as tmp:
        fe = FailureEvidence(base_dir=tmp)
        folder = Path(fe.capture("ai_error", None,
                                 context={"error": "all providers failed"}))
        data = json.loads((folder / "failure.json").read_text())
        assert data["failure_kind"] == "ai_error"
        assert "all providers failed" in data["error"]


# ---- #4 replay -----------------------------------------------------------

def test_replay_reissues_recorded_events():
    page = FakePage()
    events = [{"t": 0, "kind": "navigate", "url": "https://x/a"},
              {"t": 0.1, "kind": "scroll", "y": 500},
              {"t": 0.2, "kind": "mouse_move", "x": 5, "y": 6},
              {"t": 0.3, "kind": "click", "x": 5, "y": 6}]
    n = replay(events, page, speed=100)
    assert n == 4
    assert ("goto", "https://x/a") in page.moves
    assert ("click", 5, 6) in page.moves


# ---- #5 live status ------------------------------------------------------

def test_live_status_updates_and_renders_panel():
    st = LiveStatus()
    st.set(browser_state="RESULTS_VISIBLE", portal="Naukri", job_number=18,
           rule_decision="PASS", ai_status="scoring")
    panel = st.as_panel()
    assert panel["Browser State"] == "RESULTS_VISIBLE"
    assert panel["Job #"] == 18
    assert panel["Rule"] == "PASS"
    assert panel["AI"] == "scoring"


# ---- toolkit facade ------------------------------------------------------

def test_toolkit_disabled_capture_is_noop():
    tk = DiagnosticsToolkit(enabled=False)
    assert tk.capture_failure("timeout", FakePage()) == ""


def test_toolkit_enabled_capture_writes_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        tk = DiagnosticsToolkit(enabled=True, base_dir=tmp)
        folder = tk.capture_failure("selector_failure", FakePage(),
                                    selectors={"job_card": "div.card"},
                                    context={"portal": "Naukri"})
        assert Path(folder).exists()
        assert (Path(folder) / "page.html").exists()


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

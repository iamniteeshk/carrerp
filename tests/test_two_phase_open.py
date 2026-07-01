"""v2.9.1: collect-all-then-open-each-in-same-tab + packaging validator."""
from __future__ import annotations
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from careerpilot.core.models import Job
from careerpilot.browser.base_portal import collect_incrementally


class _Page:
    url = "https://naukri.com/results"
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, *a, **k): pass


def test_collect_opens_only_prefiltered_jobs_and_streams_all():
    cards = [Job(portal="naukri", job_title="Director - IT Infra", job_url="u1"),
             Job(portal="naukri", job_title="CFO", job_url="u2"),
             Job(portal="naukri", job_title="Head of Digital Workplace", job_url="u3")]
    parsed = {"done": False}
    def parse_fn(page):
        if parsed["done"]:
            return []
        parsed["done"] = True
        return list(cards)

    opened, streamed = [], []
    def detail_fn(j): opened.append(j.job_title); j.read_status = "COMPLETE"
    def on_job(j): streamed.append(j.job_title)
    # skip CFO, open the rest
    def should_open(j): return "cfo" not in j.job_title.lower()

    out = collect_incrementally(_Page(), parse_fn, scroll_passes=0,
                                on_job=on_job, detail_fn=detail_fn,
                                should_open=should_open)
    assert len(out) == 3                       # all collected
    assert set(streamed) == {"Director - IT Infra", "CFO",
                             "Head of Digital Workplace"}  # all streamed
    assert "CFO" not in opened                 # CFO never opened
    assert set(opened) == {"Director - IT Infra", "Head of Digital Workplace"}
    cfo = [c for c in cards if c.job_title == "CFO"][0]
    assert cfo.read_status == "SKIPPED_PREFILTER"


def test_collect_marks_partial_when_open_fails():
    card = Job(portal="naukri", job_title="Director", job_url="u1")
    def parse_fn(page, _c=[0]):
        if _c[0]:
            return []
        _c[0] = 1
        return [card]
    def detail_fn(j): raise RuntimeError("navigation timeout")
    streamed = []
    out = collect_incrementally(_Page(), parse_fn, scroll_passes=0,
                                on_job=lambda j: streamed.append(j),
                                detail_fn=detail_fn, should_open=lambda j: True)
    assert len(out) == 1 and streamed            # still streamed (terminal)
    assert card.read_status == "PARTIAL"         # open failure -> PARTIAL, not UNREAD
    assert card.missing_fields                    # has a precise reason


def test_packaging_validator_flags_runtime_artifacts():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "database"))
    open(os.path.join(d, "database", "careerpilot.db"), "w").close()
    r = subprocess.run([sys.executable, "scripts/validate_clean.py", d],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FAILED" in r.stdout


def test_packaging_validator_passes_when_clean():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "README.md"), "w").write("ok")
    r = subprocess.run([sys.executable, "scripts/validate_clean.py", d],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "PASSED" in r.stdout


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try: fn(); passed += 1; print(f"PASS {name}")
            except Exception: failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

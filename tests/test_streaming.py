"""Tests for the event-driven streaming pipeline (v2.6.0)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.base_portal import collect_incrementally, _gradual_scroll
from careerpilot.reports.streaming_csv import StreamingCSVReporter


# ---- streaming: on_job fires per job DURING collection -------------------

class Job:
    def __init__(self, url, title="Director"):
        self.job_url = url
        self.job_title = title
        self.job_description = ""


class StreamPage:
    """Reveals more cards on each scroll, like infinite scroll."""
    def __init__(self):
        self.url = "https://x/jobs"
        self._revealed = 1
    def evaluate(self, js):
        if "innerHeight" in js:
            return 800
        if "scrollBy" in js:
            self._revealed = min(self._revealed + 1, 3)
        return None
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, ms): pass


def test_on_job_fires_incrementally_not_at_end():
    page = StreamPage()
    fired = []

    def parse(_p):
        # Visible cards grow as we scroll; new ones get streamed.
        return [Job(f"https://x/job/{i}") for i in range(page._revealed)]

    result = collect_incrementally(page, parse, scroll_passes=3, settle_ms=0,
                                   networkidle_timeout_ms=10,
                                   on_job=lambda j: fired.append(j.job_url))
    # Each distinct job streamed exactly once, as discovered.
    assert fired == ["https://x/job/0", "https://x/job/1", "https://x/job/2"]
    assert len(result) == 3


def test_gradual_scroll_is_multiple_small_steps():
    calls = []
    class P:
        def evaluate(self, js):
            calls.append(js); return 800 if "innerHeight" in js else None
        def wait_for_timeout(self, ms): pass
    _gradual_scroll(P())
    scrolls = [c for c in calls if "scrollBy" in c]
    assert len(scrolls) >= 3                      # several steps, never one jump
    assert all("scrollHeight" not in c for c in scrolls)  # not a full-height leap


# ---- streaming CSV: live append per state --------------------------------

def test_streaming_csv_appends_live_per_state():
    with tempfile.TemporaryDirectory() as tmp:
        r = StreamingCSVReporter(tmp)
        j = Job("https://x/job/1")
        j.portal = "Naukri"; j.company = "Acme"; j.location = "Chennai"
        j.salary = ""; j.experience = ""; j.job_id = 7
        r.found(j)
        r.rejected(j, "SALARY_BELOW_THRESHOLD")
        # Files exist immediately (not only at scan end).
        assert (Path(tmp) / "FoundJobs.csv").exists()
        assert (Path(tmp) / "RejectedJobs.csv").exists()
        found = (Path(tmp) / "FoundJobs.csv").read_text()
        assert "Director" in found and "FOUND" in found
        rej = (Path(tmp) / "RejectedJobs.csv").read_text()
        assert "SALARY_BELOW_THRESHOLD" in rej


def test_streaming_csv_appends_multiple_rows():
    with tempfile.TemporaryDirectory() as tmp:
        r = StreamingCSVReporter(tmp)
        for i in range(3):
            j = Job(f"https://x/job/{i}", title=f"Role{i}")
            j.portal = "LinkedIn"; j.company = "C"; j.location = "L"
            j.salary = ""; j.experience = ""; j.job_id = i
            r.found(j)
        lines = (Path(tmp) / "FoundJobs.csv").read_text().strip().splitlines()
        assert len(lines) == 4   # header + 3 rows


# ---- crash recovery: already-seen jobs are skipped -----------------------

def test_pipeline_skips_already_processed_jobs():
    from careerpilot.core.pipeline import ScanPipeline
    # Minimal stand-ins; we only exercise _process_job's skip path.
    class Jobs:
        def exists(self, job): return True   # already in DB (prior run)
    pipe = ScanPipeline.__new__(ScanPipeline)
    pipe.jobs = Jobs()
    pipe._job_seq = 0
    counts = {"found": 0, "rejected": 0, "matched": 0, "applied": 0, "skipped": 0}
    j = Job("https://x/job/144"); j.portal = "Naukri"
    pipe._process_job(j, counts, dry_run=True)
    assert counts["skipped"] == 1 and counts["found"] == 0


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

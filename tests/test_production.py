"""Tests for v2.7.0 production-readiness pieces."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.ai.gemini import GeminiProvider
from careerpilot.browser.base_portal import BrowserState, collect_incrementally
from careerpilot.browser.job_detail import JobDetailExtractor


# ---- Gemini dynamic model resolution (no hardcoded names) ----------------

def test_resolve_keeps_valid_model():
    g = GeminiProvider(["k"], "gemini-2.5-flash")
    g.list_models = lambda timeout=20: ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert g.resolve_model() == "gemini-2.5-flash"


def test_resolve_auto_selects_newest_flash_when_configured_missing():
    g = GeminiProvider(["k"], "gemini-1.5-flash")   # the 404 model
    g.list_models = lambda timeout=20: [
        "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro",
        "text-embedding-004"]
    chosen = g.resolve_model()
    assert chosen == "gemini-2.5-flash"   # newest flash, not pro, not embedding
    assert g.model == "gemini-2.5-flash"


def test_resolve_survives_api_failure():
    from careerpilot.ai.provider_base import AIProviderError
    g = GeminiProvider(["k"], "gemini-x")
    def boom(timeout=20): raise AIProviderError("network down")
    g.list_models = boom
    assert g.resolve_model() == "gemini-x"   # unchanged, no crash


def test_newest_flash_ranking():
    assert GeminiProvider._newest_flash(
        ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash"]
    ) == "gemini-2.5-flash"
    assert GeminiProvider._newest_flash(["gemini-2.5-pro"]) == ""  # no flash


# ---- new browser states --------------------------------------------------

def test_job_centric_states_exist():
    for name in ("OPENING_JOB", "READING_JOB", "SCROLLING_JOB", "EXTRACTING",
                 "WAITING_AI", "RETURNING_RESULTS", "HOME_PAGE", "RESULTS_READY"):
        assert hasattr(BrowserState, name), name


# ---- job detail extractor (fake page) ------------------------------------

class El:
    def __init__(self, text): self._t = text
    def inner_text(self): return self._t
    def get_attribute(self, k): return None


class DetailPage:
    def __init__(self, desc):
        self.url = "https://www.naukri.com/job-listings-director-1"
        self._desc = desc
        self.navigated = []
    def query_selector(self, sel):
        # description/container selectors resolve to the JD element
        if "desc" in sel or "dang" in sel:
            return El(self._desc)
        return None
    def query_selector_all(self, sel): return []
    def goto(self, url, **k): self.navigated.append(url)
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_selector(self, *a, **k): pass
    def wait_for_timeout(self, ms): pass
    def content(self): return f"<html>{self._desc}</html>"


class Job:
    def __init__(self):
        self.portal = "naukri"
        self.job_title = "Director"
        self.job_url = "https://www.naukri.com/job-listings-director-1"
        self.job_description = ""           # empty card -> filled from detail
        self.salary = "50 LPA"              # good card value -> must NOT be lost
        self.experience = ""
        self.employment_type = ""
        self.company_description = ""
        self.posted_date = ""
        self.raw_html = ""
        self.external_apply_url = ""


def test_detail_extractor_fills_full_jd_and_caches():
    with tempfile.TemporaryDirectory() as tmp:
        from careerpilot.core.job_cache import JobCache
        cache = JobCache(tmp)
        ext = JobDetailExtractor(job_cache=cache)
        job = Job()
        long_desc = "Lead the infrastructure org. " * 40
        page = DetailPage(long_desc)
        out = ext.open_and_extract(page, job, networkidle_timeout_ms=10,
                                   render_settle_ms=0)
        assert long_desc.strip() in out.job_description       # full JD captured
        assert out.salary == "50 LPA"                          # card value kept
        assert out.raw_html                                    # complete HTML stored
        # cached -> a second pass skips opening
        page2 = DetailPage(long_desc); page2.navigated = []
        ext.open_and_extract(page2, Job(), networkidle_timeout_ms=10)
        assert page2.navigated == []                           # cache hit, no reopen


def test_detail_extractor_keeps_card_data_on_failure():
    ext = JobDetailExtractor()
    job = Job(); job.salary = "60 LPA"
    class Boom:
        url = "u"
        def query_selector(self, s): raise RuntimeError("dom gone")
        def goto(self, u, **k): pass
        def wait_for_load_state(self, *a, **k): pass
        def wait_for_timeout(self, ms): pass
    out = ext.open_and_extract(Boom(), job, networkidle_timeout_ms=10)
    assert out.salary == "60 LPA"   # untouched; scan continues


# ---- detail_fn hook in the collect loop ----------------------------------

class StreamPage:
    def __init__(self): self.url = "https://x/jobs"
    def evaluate(self, js): return 800 if "innerHeight" in js else None
    def wait_for_load_state(self, *a, **k): pass
    def wait_for_timeout(self, ms): pass


def test_detail_fn_runs_before_on_job():
    order = []
    page = StreamPage()
    j = type("J", (), {"job_url": "u1", "job_title": "T", "job_description": ""})()
    collect_incrementally(page, lambda p: [j], scroll_passes=1, settle_ms=0,
                          networkidle_timeout_ms=10,
                          detail_fn=lambda job: order.append("detail"),
                          on_job=lambda job: order.append("process"))
    assert order[:2] == ["detail", "process"]   # JD extracted before pipeline


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

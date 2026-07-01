"""v2.9.6: browser lifecycle instrumentation and navigation helpers."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.base_portal import (
    _looks_like_job_page, _wait_for_job_open, _page_alive)
from careerpilot.browser.session import LifecycleInstrumenter


class _Ctx:
    def __init__(self, pages):
        self.pages = pages
        self._handlers = {}
    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)


class _Pg:
    def __init__(self, url):
        self.url = url
        self._closed = False
    def is_closed(self):
        return self._closed
    def wait_for_load_state(self, *a, **k):
        pass


def test_looks_like_job_page_matches_naukri_urls():
    assert _looks_like_job_page(
        "https://www.naukri.com/job-listings-director-it-chennai-123",
        "https://www.naukri.com/job-listings-director-it-chennai-123")
    assert not _looks_like_job_page(
        "https://www.naukri.com/director-jobs-in-chennai", "")


def test_wait_for_job_open_detects_same_tab_navigation():
    page = _Pg("https://naukri.com/results")
    ctx = _Ctx([page])
    page.url = "https://naukri.com/job-listings-xyz"
    job_url = "https://naukri.com/job-listings-xyz"
    out = _wait_for_job_open(page, ctx, "https://naukri.com/results", 1, 2000,
                             job_url=job_url)
    assert out.opened and out.mode == "click_same_tab"


def test_lifecycle_instrumenter_wires_handlers():
    ctx = _Ctx([_Pg("https://x")])
    LifecycleInstrumenter("naukri").attach_context(ctx)
    assert "close" in ctx._handlers
    assert "page" in ctx._handlers


def test_page_alive_treats_missing_is_closed_as_alive():
    assert _page_alive(object())

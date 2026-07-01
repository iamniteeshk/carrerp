"""v2.9.7: URL-based job evaluation -- collect URLs, goto each, no go_back."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.models import Job
from careerpilot.browser.base_portal import collect_incrementally


class _Page:
    def __init__(self):
        self.url = "https://naukri.com/director-jobs-in-chennai"
        self.navigated = []

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, *a, **k):
        pass

    def is_closed(self):
        return False


def test_phase2_uses_url_navigation_without_go_back():
    cards = [
        Job(portal="naukri", job_title="Director - IT", job_url="https://naukri.com/j1"),
        Job(portal="naukri", job_title="Head Infra", job_url="https://naukri.com/j2"),
    ]
    seen = {"done": False}

    def parse_fn(page):
        if seen["done"]:
            return []
        seen["done"] = True
        return list(cards)

    opened_urls = []

    def detail_fn(j):
        opened_urls.append(j.job_url)
        j.read_status = "COMPLETE"
        j.job_description = "x" * 150

    streamed = []

    out = collect_incrementally(
        _Page(), parse_fn, scroll_passes=0,
        on_job=lambda j: streamed.append(j.job_url),
        detail_fn=detail_fn,
        should_open=lambda j: True,
    )
    assert len(out) == 2
    assert opened_urls == ["https://naukri.com/j1", "https://naukri.com/j2"]
    assert streamed == opened_urls

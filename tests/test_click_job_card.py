"""v2.9.2: real click-based opening (move -> hover -> click), not page.goto().

Root cause: hover_then_click existed in the humanizer but was NEVER called by
the pipeline; every 'open' was a raw page.goto(url). These tests prove the new
click_job_card() finds the card's own link and performs a real click, falling
back to direct navigation only when the element truly can't be found.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from careerpilot.browser.base_portal import click_job_card
from careerpilot.core.models import Job


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages


class _FakeEl:
    def __init__(self, href="", text="", box=(10, 10, 100, 20)):
        self.href = href; self.text = text; self._box = box
        self.clicked = False; self.hovered = False
    def get_attribute(self, name): return self.href if name == "href" else None
    def inner_text(self): return self.text
    def scroll_into_view_if_needed(self, timeout=0): pass
    def bounding_box(self):
        x, y, w, h = self._box
        return {"x": x, "y": y, "width": w, "height": h}
    def hover(self, timeout=0): self.hovered = True
    def click(self, timeout=0, **kwargs):  # noqa: ARG002
        self.clicked = True
        self._page._url = self._page._target_url   # simulate same-tab navigation


class _FakeLocator:
    def __init__(self, els, page): self._els = els; self._page = page
    def count(self): return len(self._els)
    def nth(self, i):
        el = self._els[i]; el._page = self._page
        return el
    def filter(self, has_text=None):
        matches = [e for e in self._els if has_text and has_text in e.text]
        for e in matches:
            e._page = self._page
        return _FakeLocator(matches, self._page)
    @property
    def first(self): return self._els[0]


class _FakePage:
    def __init__(self, els, target_url=""):
        self._els = els; self._url = "https://naukri.com/results"
        self._target_url = target_url or "https://naukri.com/job/xyz"
        self.context = _FakeContext([self])
    @property
    def url(self): return self._url
    def locator(self, sel): return _FakeLocator(self._els, self)
    def wait_for_timeout(self, ms): pass
    def evaluate(self, *a, **k): return False
    def query_selector_all(self, sel): return []
    def is_closed(self): return False
    def bring_to_front(self): pass


def test_click_finds_element_by_href_and_clicks():
    url = "https://naukri.com/job/xyz"
    el = _FakeEl(href=url, text="Director - IT Infra")
    page = _FakePage([el], target_url=url)
    job = Job(portal="naukri", job_title="Director - IT Infra", job_url=url)
    ok = click_job_card(page, job, "a.title")
    assert ok and el.clicked and el.hovered


def test_click_falls_back_to_text_when_no_href_match():
    el = _FakeEl(href="", text="Director - IT Infra")
    page = _FakePage([el], target_url="https://naukri.com/job/xyz")
    job = Job(portal="naukri", job_title="Director - IT Infra",
             job_url="https://naukri.com/job/xyz")
    ok = click_job_card(page, job, "a.title")
    assert ok and el.clicked


def test_click_returns_false_when_no_matching_element():
    el = _FakeEl(href="https://naukri.com/job/OTHER", text="Some Other Role")
    page = _FakePage([el])
    job = Job(portal="naukri", job_title="Director - IT Infra",
             job_url="https://naukri.com/job/xyz")
    assert not click_job_card(page, job, "a.title") and not el.clicked


def test_click_returns_false_when_no_selector_given():
    page = _FakePage([])
    job = Job(portal="naukri", job_title="Director", job_url="u")
    assert not click_job_card(page, job, "")


def test_open_and_extract_uses_url_navigation_directly():
    """open_and_extract navigates directly to the job URL (no card click)."""
    from careerpilot.browser.job_detail import JobDetailExtractor
    import careerpilot.browser.job_detail as jd

    calls = {"navigate": 0, "urls": []}
    orig_navigate = jd.navigate
    orig_wait = jd.wait_for_ready
    def _nav(page, url, **kw):
        calls["navigate"] += 1
        calls["urls"].append(url)
    jd.navigate = _nav
    jd.wait_for_ready = lambda *a, **k: None
    try:
        ex = JobDetailExtractor(humanizer=None, job_cache=None)
        page = _FakePage([], target_url="https://naukri.com/job/xyz")
        page.bring_to_front = lambda: None
        page.query_selector = lambda *a, **k: None
        page.content = lambda: ""
        job_url = "https://naukri.com/job/xyz"
        job = Job(portal="naukri", job_title="Director", job_url=job_url)
        ex.open_and_extract(page, job, max_retries=0)
        assert calls["navigate"] == 1
        assert calls["urls"] == [job_url]
        assert job.open_mode == "url_navigate"
    finally:
        jd.navigate = orig_navigate
        jd.wait_for_ready = orig_wait


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try: fn(); passed += 1; print(f"PASS {name}")
            except Exception: failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

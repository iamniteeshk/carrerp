"""Tests for the navigation-stabilization fixes (live-run bugs):
* navigate() reuses the page when already on the target URL (no reload loop)
* search() builds ONE distinct URL per (title, location) and never repeats one
* the LinkedIn timeout / Naukri refresh root cause (re-goto same URL) is gone

These use a fake page that records every goto, so we assert on real navigation
behaviour without a browser.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.base_portal import navigate, same_url
from careerpilot.browser.linkedin_portal import LinkedInPortal
from careerpilot.browser.naukri_portal import NaukriPortal


class FakePage:
    """Records goto calls and tracks the 'current' URL like a real page."""
    def __init__(self, start="about:blank"):
        self.url = start
        self.gotos: list[str] = []
        self.scrolls = 0

    def goto(self, url, wait_until=None):
        self.gotos.append(url)
        self.url = url

    # --- methods wait_for_ready / human_scroll rely on (no-ops for tests) ---
    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def wait_for_selector(self, selector, state=None, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        self.scrolls += 1

    def query_selector(self, sel):
        return object()        # results container present

    def query_selector_all(self, sel):
        return []              # generic parser finds no cards in the fake DOM


class _Cfg:
    networkidle_timeout_ms = 8000
    render_settle_ms = 0   # keep tests instant
    scroll_passes = 2


class _Manager:
    cfg = _Cfg()


class FakeSession:
    def __init__(self, page):
        self._page = page
        self.profile_dir = "/tmp/x"
        self.manager = _Manager()

    @property
    def page(self):
        return self._page


# ---- navigate() guard ----------------------------------------------------

def test_same_url_normalizes_trailing_slash_and_fragment():
    assert same_url("https://x.com/jobs", "https://x.com/jobs/")
    assert same_url("https://x.com/a?b=1", "https://x.com/a?b=1#frag")
    assert not same_url("https://x.com/a", "https://x.com/b")


def test_navigate_reuses_page_when_already_there():
    page = FakePage(start="https://www.linkedin.com/jobs/search/?keywords=Director")
    moved = navigate(page, "https://www.linkedin.com/jobs/search/?keywords=Director",
                     reason="same")
    assert moved is False
    assert page.gotos == []  # NO navigation -- page reused


def test_navigate_goes_when_url_differs():
    page = FakePage(start="https://www.linkedin.com/feed/")
    moved = navigate(page, "https://www.linkedin.com/jobs/search/?keywords=Head",
                     reason="new search")
    assert moved is True
    assert len(page.gotos) == 1


# ---- LinkedIn search: distinct URLs, no repeated base-page navigation -----

def test_linkedin_plan_recommended_first_then_preferred_then_all():
    page = FakePage(start="https://www.linkedin.com/feed/")
    portal = LinkedInPortal(FakeSession(page), candidate=None, easy_apply_only=True)
    portal.search_include_recommended = True
    portal.search_nationwide = True
    portal.search(["Director", "Head"], ["Chennai", "Bangalore"])
    gotos = page.gotos
    # 1) recommended jobs is FIRST
    assert "collections/recommended" in gotos[0], gotos
    # 2) preferred-location searches (with location=) come before all-locations
    loc_searches = [u for u in gotos if "location=" in u]
    all_searches = [u for u in gotos if "keywords=" in u and "location=" not in u]
    assert loc_searches and all_searches
    assert gotos.index(loc_searches[-1]) < gotos.index(all_searches[0])
    # easy-apply filter preserved; no duplicate URLs
    assert any("f_AL=true" in u for u in gotos)
    assert len(set(gotos)) == len(gotos)


def test_linkedin_plan_dedupes_identical_pairs():
    page = FakePage(start="https://www.linkedin.com/feed/")
    portal = LinkedInPortal(FakeSession(page), candidate=None, easy_apply_only=False)
    portal.search_include_recommended = True
    portal.search_nationwide = True
    portal.search(["Director", "Director"], ["Chennai"])
    # recommended + Director/Chennai + Director/all = 3 distinct, no repeats.
    assert len(page.gotos) == len(set(page.gotos)) == 3, page.gotos


# ---- Naukri search: the refresh-loop root cause is gone -------------------

def test_naukri_search_does_not_reload_same_page():
    page = FakePage(start="https://www.naukri.com/mnjuser/homepage")
    portal = NaukriPortal(FakeSession(page), candidate=None)
    portal.search_include_recommended = True
    portal.search_nationwide = True
    portal.search(["Director"], ["Chennai", "Bangalore"])
    # recommended + 2 preferred-location searches + 1 all-locations = 4 distinct.
    assert len(page.gotos) == len(set(page.gotos)) == 4, page.gotos
    # recommended jobs first; no bare homepage reload loop.
    assert "recommendedjobs" in page.gotos[0]
    assert "https://www.naukri.com/" not in page.gotos
    # preferred-location searches use the -jobs-in- slug pattern.
    assert any("jobs-in-chennai" in u for u in page.gotos)


def test_naukri_chennai_only_quality_search_plan():
    """v2.9.4: default is quality-first -- no recommended feed, no nationwide."""
    page = FakePage(start="https://www.naukri.com/mnjuser/homepage")
    portal = NaukriPortal(FakeSession(page), candidate=None)
    portal.search(["Director", "Head"], ["Chennai"])
    gotos = page.gotos
    assert len(gotos) == 2
    assert all("jobs-in-chennai" in u for u in gotos)
    assert not any("recommendedjobs" in u for u in gotos)
    portal = NaukriPortal(FakeSession(FakePage()), candidate=None)
    url = portal._search_url("Contact Centre Head", "New Delhi")
    # Slug is unchanged; an experience filter is appended to narrow the search.
    assert url.startswith(
        "https://www.naukri.com/contact-centre-head-jobs-in-new-delhi")
    assert "experience=" in url


# ---- readiness wait: the SPA "instant URL hop" fix ------------------------

from careerpilot.browser.base_portal import wait_for_ready, human_scroll


class RecordingPage:
    """Records the ordered sequence of readiness waits."""
    def __init__(self, url="https://www.naukri.com/x-jobs", idle_raises=False,
                 selector_raises=False):
        self.url = url
        self.events: list[str] = []
        self.idle_raises = idle_raises
        self.selector_raises = selector_raises
        self.scrolls = 0
        self.scroll_passes = 0

    def wait_for_load_state(self, state=None, timeout=None):
        if state == "networkidle":
            if self.idle_raises:
                raise TimeoutError("networkidle timeout")
            self.events.append("networkidle")
        else:
            self.events.append("load")

    def wait_for_selector(self, selector, state=None, timeout=None):
        if self.selector_raises:
            raise TimeoutError("no results")
        self.events.append(f"selector:{state}")

    def wait_for_timeout(self, ms):
        self.events.append(f"settle:{ms}")

    def evaluate(self, script):
        self.scrolls += 1
        if "innerHeight" in script:
            self.scroll_passes += 1   # _gradual_scroll reads innerHeight once/pass
            return 800
        return None


def test_wait_for_ready_waits_load_then_networkidle_then_settle():
    page = RecordingPage()
    ok = wait_for_ready(page, networkidle_timeout_ms=5000, render_settle_ms=500)
    # Order matters: full load BEFORE networkidle BEFORE the paint-settle.
    assert page.events == ["load", "networkidle", "settle:500"], page.events
    assert ok is True  # no selector configured -> treated as confirmed


def test_wait_for_ready_tolerates_networkidle_timeout_without_crashing():
    page = RecordingPage(idle_raises=True)
    # Busy sites may never go idle -- must proceed, not raise, not hang.
    wait_for_ready(page, networkidle_timeout_ms=1000, render_settle_ms=0)
    assert "networkidle" not in page.events  # it raised, we moved on
    assert "load" in page.events


def test_wait_for_ready_waits_for_results_selector_when_configured():
    page = RecordingPage()
    ok = wait_for_ready(page, results_selector="div.srp-jobtuple-wrapper",
                        render_settle_ms=0)
    assert "selector:visible" in page.events
    assert ok is True


def test_wait_for_ready_reports_unconfirmed_when_selector_missing():
    page = RecordingPage(selector_raises=True)
    ok = wait_for_ready(page, results_selector="div.missing", render_settle_ms=0)
    assert ok is False  # empty page / wrong selector -> caller knows


def test_human_scroll_scrolls_requested_passes():
    page = RecordingPage()
    n = human_scroll(page, passes=4, settle_ms=0)
    assert n == 4 and page.scrolls == 4


def test_search_waits_before_parsing():
    """search() must wait_for_ready BEFORE the first extraction, then collect
    incrementally (read visible -> scroll -> read new)."""
    order = []

    class P(FakePage):
        def wait_for_load_state(self, state=None, timeout=None):
            order.append("wait")
        def evaluate(self, script):
            order.append("scroll")

    portal = NaukriPortal(FakeSession(P(start="https://www.naukri.com/feed")),
                          candidate=None)
    portal._parse_result_cards = lambda page: order.append("parse") or []
    portal.search(["Director"], ["Chennai"])
    # Ready-wait happens before the first extraction.
    assert order.index("wait") < order.index("parse")
    # Incremental: more than one extraction pass, with a scroll interleaved.
    assert order.count("parse") >= 2
    assert "scroll" in order


# ---- incremental collect + state observation -----------------------------

from careerpilot.browser.base_portal import (collect_incrementally,
                                             observe_state, BrowserState)


class Job:
    def __init__(self, url):
        self.job_url = url


def test_collect_incrementally_accumulates_new_and_dedupes():
    # Page "loads" 2 jobs, then 2 more after a scroll, with one duplicate.
    batches = [
        [Job("a"), Job("b")],
        [Job("a"), Job("b"), Job("c")],   # c is new after scroll
        [Job("a"), Job("b"), Job("c")],   # nothing new
        [Job("a"), Job("b"), Job("c")],   # nothing new -> end of results
    ]
    calls = {"i": 0}

    class P(RecordingPage):
        def __init__(self):
            super().__init__()
        def _next(self):
            b = batches[min(calls["i"], len(batches) - 1)]; calls["i"] += 1; return b

    page = P()
    out = collect_incrementally(page, lambda pg: page._next(), scroll_passes=5,
                                settle_ms=0, max_no_new=2)
    keys = sorted(j.job_url for j in out)
    assert keys == ["a", "b", "c"], keys      # de-duplicated union
    assert page.scrolls >= 1                   # it scrolled to load more


def test_collect_incrementally_stops_at_end_of_results():
    page = RecordingPage()
    # Always empty -> after max_no_new passes it must stop (not scroll forever).
    out = collect_incrementally(page, lambda pg: [], scroll_passes=20,
                                settle_ms=0, max_no_new=2)
    assert out == []
    assert page.scroll_passes <= 2  # stopped early, did NOT scroll all 20 times


def test_observe_state_detects_login_and_results():
    class LoginPage:
        url = "https://www.naukri.com/nlogin/login"
    assert observe_state(LoginPage()) == BrowserState.LOGIN_PAGE

    class ResultsPage:
        url = "https://www.naukri.com/director-jobs-in-chennai"
        def query_selector(self, sel):
            return object()  # results container present
    assert observe_state(ResultsPage(), results_selector="div.x") == \
        BrowserState.RESULTS_VISIBLE

    class EmptyPage:
        url = "https://www.naukri.com/director-jobs-in-chennai"
        def query_selector(self, sel):
            return None
    assert observe_state(EmptyPage(), results_selector="div.x") == \
        BrowserState.EMPTY_RESULTS


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

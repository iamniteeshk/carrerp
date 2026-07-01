"""Tests for v2.4.0: config-driven card parser, human-like browsing, validator."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.browser.humanize import Humanizer, HumanConfig
from careerpilot.browser.naukri_portal import NaukriPortal
from careerpilot.core.pipeline_validator import (validate_pipeline, StageResult)


# ---- config-driven parser (no browser; fake DOM handles) -----------------

class El:
    def __init__(self, text="", attrs=None):
        self._t = text
        self._a = attrs or {}
    def inner_text(self):
        return self._t
    def get_attribute(self, k):
        return self._a.get(k)


class Card:
    def __init__(self, mapping):
        self._m = mapping  # selector -> El
    def query_selector(self, sel):
        # match on first comma-separated alternative that exists
        for part in sel.split(","):
            part = part.strip()
            if part in self._m:
                return self._m[part]
        return None


class CardsPage:
    def __init__(self, cards):
        self.url = "https://www.naukri.com/director-jobs-in-chennai"
        self._cards = cards
    def query_selector_all(self, sel):
        return self._cards


class _Mgr:
    class cfg:
        networkidle_timeout_ms = 1000
        render_settle_ms = 0
        scroll_passes = 1


class _Sess:
    def __init__(self, page):
        self._p = page
        self.manager = _Mgr()
    @property
    def page(self):
        return self._p


def test_parser_extracts_fields_from_cards():
    cards = [
        Card({"a.title": El("Director - Infra", {"href": "/job/1"}),
              "a.comp-name": El("Acme"), "span.locWdth": El("Chennai"),
              "span.sal": El("50 LPA")}),
        Card({"a.title": El("Head DWP", {"href": "/job/2"}),
              "a.comp-name": El("Globex"), "span.locWdth": El("Bangalore")}),
    ]
    page = CardsPage(cards)
    portal = NaukriPortal(_Sess(page), candidate=None)
    jobs = portal._parse_result_cards(page)
    assert len(jobs) == 2
    assert jobs[0].job_title == "Director - Infra"
    assert jobs[0].company == "Acme"
    assert jobs[0].location == "Chennai"
    assert jobs[0].job_url.endswith("/job/1")


def test_parser_skips_cards_without_title_or_url():
    cards = [Card({"a.comp-name": El("NoTitleCo")})]  # no title/url
    page = CardsPage(cards)
    portal = NaukriPortal(_Sess(page), candidate=None)
    assert portal._parse_result_cards(page) == []  # never invents data


def test_parser_returns_empty_when_selector_unset():
    page = CardsPage([])
    portal = NaukriPortal(_Sess(page), candidate=None,
                          parse_config={"results_selector": ""})
    portal.results_selector = ""  # explicitly unset
    assert portal._parse_result_cards(page) == []


# ---- humanizer (deterministic with a seed) -------------------------------

class ScrollPage:
    def __init__(self):
        self.calls = []
    def evaluate(self, js):
        self.calls.append(js)
        if "innerHeight" in js:
            return 800
        return None
    def wait_for_timeout(self, ms):
        self.calls.append(f"wait:{ms}")


def test_humanizer_disabled_is_single_scroll():
    h = Humanizer(HumanConfig(enabled=False))
    page = ScrollPage()
    h.scroll_one_screen(page)
    scrolls = [c for c in page.calls if "scrollBy" in str(c)]
    assert len(scrolls) == 1  # legacy single jump


def test_humanizer_enabled_scrolls_gradually_with_pauses():
    h = Humanizer(HumanConfig(enabled=True, seed=42))
    page = ScrollPage()
    info = h.scroll_one_screen(page)
    scrolls = [c for c in page.calls if "scrollBy" in str(c)]
    pauses = [c for c in page.calls if str(c).startswith("wait:")]
    assert info["mode"] == "human"
    assert len(scrolls) >= 2     # multiple small steps, not one jump
    assert len(pauses) >= 2      # pauses between steps


def test_reading_pause_scales_with_content():
    h = Humanizer(HumanConfig(enabled=True, seed=1))
    short = h.reading_pause_ms("one two three")
    long = h.reading_pause_ms(" ".join(["word"] * 800))
    assert long > short
    assert h.reading_pause_ms("") >= h.cfg.min_read_ms  # bounded


def test_humanizer_deterministic_with_seed():
    a = Humanizer(HumanConfig(enabled=True, seed=7))
    b = Humanizer(HumanConfig(enabled=True, seed=7))
    pa, pb = ScrollPage(), ScrollPage()
    a.scroll_one_screen(pa)
    b.scroll_one_screen(pb)
    assert pa.calls == pb.calls  # same seed -> identical behaviour


# ---- pipeline validator --------------------------------------------------

class _FakePilot:
    def __init__(self, found):
        self._found = found
        outer = self
        class P:
            def run_once(self_):
                return {"found": outer._found, "rejected": 1, "matched": 2,
                        "applied": 0}
            portals = [1, 2]
        class JS:
            def count_by_status(self_):
                return {"FOUND": outer._found}
        class R:
            def generate_all(self_):
                return ["a.csv"]
        self.pipeline = P(); self.job_service = JS(); self.reporter = R()


def test_validator_flags_zero_jobs_stage():
    ok, results = validate_pipeline(_FakePilot(found=0))
    assert ok is False
    bc = next(r for r in results if r.name == "Browser/Collector")
    assert not bc.ok and "0 jobs" in bc.detail


def test_validator_passes_when_jobs_flow():
    ok, results = validate_pipeline(_FakePilot(found=5))
    assert ok is True
    assert all(r.ok for r in results)


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

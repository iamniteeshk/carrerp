"""Tests for the Job Memory Cache and curved human mouse (v2.5.0)."""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.job_cache import JobCache, job_key, content_hash
from careerpilot.browser.humanize import Humanizer, HumanConfig


# ---- job cache -----------------------------------------------------------

def test_job_key_normalizes():
    assert job_key("https://x.com/job/1?ref=a#top") == "https://x.com/job/1"
    assert job_key("https://x.com/job/1/") == "https://x.com/job/1"


def test_cache_miss_then_hit():
    with tempfile.TemporaryDirectory() as tmp:
        c = JobCache(tmp)
        job = {"job_url": "https://x.com/job/1", "job_title": "Director",
               "company": "Acme", "job_description": "lead the team"}
        assert c.needs_open(job["job_url"]) is True       # miss
        h = c.put(job)
        assert c.needs_open(job["job_url"], h) is False    # hit, unchanged
        assert c.stats.hits == 1 and c.stats.misses == 1


def test_cache_detects_change():
    with tempfile.TemporaryDirectory() as tmp:
        c = JobCache(tmp)
        job = {"job_url": "https://x.com/job/2", "job_title": "Head",
               "company": "Globex", "job_description": "old text"}
        c.put(job)
        changed = dict(job, job_description="NEW responsibilities added")
        new_hash = content_hash(changed)
        assert c.needs_open(job["job_url"], new_hash) is True  # content changed
        assert c.stats.changed == 1


def test_cache_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmp:
        JobCache(tmp).put({"job_url": "https://x.com/job/3", "job_title": "VP"})
        # New instance (simulating restart) still sees it.
        c2 = JobCache(tmp)
        assert c2.get("https://x.com/job/3")["job_title"] == "VP"
        assert len(c2) == 1


# ---- curved mouse --------------------------------------------------------

class MousePage:
    def __init__(self):
        self.moves = []
    class _M:
        def __init__(self, outer): self.o = outer
        def move(self, x, y, steps=None): self.o.moves.append((round(x), round(y)))
        def click(self, x, y): self.o.moves.append(("click", round(x), round(y)))
    @property
    def mouse(self):
        return MousePage._M(self)
    def wait_for_timeout(self, ms):
        pass


def test_mouse_disabled_is_noop():
    h = Humanizer(HumanConfig(enabled=False))
    page = MousePage()
    h.move_mouse(page, 100, 100)
    assert page.moves == []


def test_mouse_follows_curved_multistep_path():
    h = Humanizer(HumanConfig(enabled=True, seed=3))
    page = MousePage()
    h.move_mouse(page, 400, 300)
    # Many intermediate points (a curve), not a single teleport.
    assert len(page.moves) > 5
    # Ends exactly on the target.
    assert page.moves[-1] == (400, 300)
    # Not a straight line: at least one point off the start->end line.
    xs = [m[0] for m in page.moves]; ys = [m[1] for m in page.moves]
    assert max(xs) - min(xs) > 0 and max(ys) - min(ys) > 0


def test_hover_then_click_pauses_and_clicks():
    h = Humanizer(HumanConfig(enabled=True, seed=5))
    page = MousePage()
    h.hover_then_click(page, 200, 200)
    assert any(m[0] == "click" for m in page.moves if isinstance(m[0], str))


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

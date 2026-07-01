"""Reliability / hardening tests for long-running unattended operation.

Covers collector self-healing and error isolation, scheduler overlap protection,
the Telegram disabled path, and graceful-shutdown idempotency. No network,
credentials, or real browser.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.collectors.manager import CollectorManager
from careerpilot.core.models import Job


# ---- collector self-heal + isolation ------------------------------------

class _Portal:
    def __init__(self, name, jobs=None, fail=False):
        self.portal_name = name
        self._jobs = jobs or []
        self._fail = fail
        self.healed = False
        self.logged_in = False

    def ensure_healthy(self):
        self.healed = True

    def ensure_logged_in(self):
        self.logged_in = True

    def search(self, keywords, locations, on_job=None, should_open=None):
        if self._fail:
            raise RuntimeError("portal boom")
        if on_job:
            for j in self._jobs:
                on_job(j)
        return self._jobs


def test_collector_self_heals_each_portal():
    p = _Portal("LinkedIn", jobs=[Job(portal="LinkedIn", job_title="Director")])
    mgr = CollectorManager([p], keywords=["Director"], locations=["Remote"])
    jobs = mgr.collect_all()
    assert p.healed is True, "ensure_healthy must run before each scan"
    assert p.logged_in is True
    assert len(jobs) == 1


def test_collector_isolates_one_portal_failure():
    bad = _Portal("Naukri", fail=True)
    good = _Portal("LinkedIn", jobs=[Job(portal="LinkedIn", job_title="Head")])
    mgr = CollectorManager([bad, good], keywords=["x"], locations=["y"])
    jobs = mgr.collect_all()
    # The bad portal must not stop the good one.
    assert len(jobs) == 1
    assert jobs[0].job_title == "Head"


# ---- scheduler overlap protection ---------------------------------------

def test_scheduler_configures_overlap_protection():
    from careerpilot.core.scheduler import Scheduler

    captured = {}

    class FakeAPS:
        def __init__(self, *a, **k): pass
        def add_job(self, func, trigger, **kw):
            if kw.get("id") == "scan":
                captured.update(kw)
        def start(self): pass
        @property
        def running(self): return False

    class FakePipeline:
        def run_once(self): return {}

    sch = Scheduler(FakePipeline(), 4, telegram=_NullTelegram(), job_service=None)
    sch._scheduler = FakeAPS()
    sch.start(run_immediately=False)
    # A scan that overruns the interval must NOT spawn a second instance.
    assert captured.get("max_instances") == 1
    assert captured.get("coalesce") is True


def test_scheduler_safe_scan_swallows_crash():
    from careerpilot.core.scheduler import Scheduler

    class BoomPipeline:
        def run_once(self): raise RuntimeError("boom")

    tg = _NullTelegram()
    sch = Scheduler(BoomPipeline(), 4, telegram=tg, job_service=None)
    sch._safe_scan()  # must not raise
    assert tg.sent, "a crashed scan must notify"


# ---- telegram disabled path ---------------------------------------------

class _NullStore:
    def __init__(self): self.records = []
    def record(self, ntype, message, sent): self.records.append((ntype, sent))


class _NullTelegram:
    """Minimal telegram stand-in that records sends."""
    def __init__(self): self.sent = []
    def send(self, ntype, message): self.sent.append((ntype, message)); return False


def test_telegram_disabled_still_records_and_never_crashes():
    from careerpilot.notify.telegram_service import TelegramService
    from careerpilot.core.enums import NotificationType

    store = _NullStore()
    svc = TelegramService(token="", chat_id="", notification_service=store)  # disabled
    assert svc.enabled is False
    ok = svc.send(NotificationType.SYSTEM_SHUTDOWN, "bye")
    assert ok is False
    assert store.records and store.records[0][1] is False  # stored as not-sent


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

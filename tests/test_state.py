"""Tests for the State Engine and Human Interaction Engine."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.state import (StateMachine, WorkflowState,
                                     InvalidTransition)
from careerpilot.core.human_interaction import HumanInteractionEngine


# ---- State Engine --------------------------------------------------------

def test_happy_path_transitions():
    sm = StateMachine(strict=True)
    sm.to(WorkflowState.COLLECTING, "start")
    sm.to(WorkflowState.SHORTLISTING, "collected")
    sm.to(WorkflowState.APPLYING, "have matches")
    sm.to(WorkflowState.COMPLETED, "done")
    assert sm.is_terminal()
    assert len(sm.history) == 4


def test_waiting_can_interrupt_any_active_state():
    sm = StateMachine(initial=WorkflowState.SEARCHING, strict=True)
    sm.to(WorkflowState.WAITING_FOR_CAPTCHA, "captcha appeared")
    assert sm.is_waiting()
    # ...and resume back into active work
    sm.to(WorkflowState.SEARCHING, "user cleared captcha")
    assert sm.state == WorkflowState.SEARCHING


def test_invalid_transition_raises_in_strict_mode():
    sm = StateMachine(strict=True)
    try:
        sm.to(WorkflowState.APPLYING, "skip everything")  # STARTING->APPLYING not allowed
        assert False, "should have raised"
    except InvalidTransition:
        pass


def test_invalid_transition_is_logged_not_raised_by_default():
    sm = StateMachine(strict=False)
    # Must NOT raise -- production never gets a new crash path from state checks.
    sm.to(WorkflowState.APPLYING, "unexpected")
    assert sm.state == WorkflowState.APPLYING  # still records the move
    assert sm.history[-1].frm == WorkflowState.STARTING


def test_terminal_states_have_no_exits():
    sm = StateMachine(initial=WorkflowState.COMPLETED, strict=True)
    assert not sm.can(WorkflowState.COLLECTING)


# ---- Human Interaction Engine -------------------------------------------

class FakePage:
    def __init__(self):
        self.url = "https://www.naukri.com/nlogin/login"
    def screenshot(self, path):
        Path(path).write_bytes(b"\x89PNG\r\n")
    def content(self):
        return "<html>login</html>"


def test_pause_saves_bundle_and_notifies():
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        eng = HumanInteractionEngine(diagnostics_dir=tmp, notify=notes.append)
        bundle = eng.pause(FakePage(), "captcha", "captcha on search", portal="Naukri")
        assert bundle.state == WorkflowState.WAITING_FOR_CAPTCHA
        assert Path(bundle.screenshot_path).exists()
        assert Path(bundle.html_path).exists()
        assert Path(bundle.meta_path).exists()
        assert notes and "CAPTCHA" in notes[0]


def test_pause_tolerates_capture_failure():
    class BadPage:
        url = "x"
        def screenshot(self, path): raise RuntimeError("no display")
        def content(self): raise RuntimeError("detached")
    with tempfile.TemporaryDirectory() as tmp:
        eng = HumanInteractionEngine(diagnostics_dir=tmp)
        bundle = eng.pause(BadPage(), "otp", "otp needed")  # must not raise
        assert bundle.state == WorkflowState.WAITING_FOR_OTP
        assert bundle.screenshot_path == ""  # capture failed, gracefully


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

"""State Engine -- CareerPilot always knows exactly where it is.

This is the deterministic state machine the architecture calls for: explicit
states, explicit transitions, every change logged with a reason. It holds NO
browser, AI, or rule logic -- it only tracks and validates *where* the workflow
is, so behaviour is never hidden or assumed.

Design choice: an unexpected transition is *logged as a warning*, not raised, in
normal operation -- surfacing the problem without introducing a new crash path
into a live scan. Tests use ``strict=True`` to assert the transition map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time

from .logging_setup import get_logger

logger = get_logger(__name__)


class WorkflowState(str, Enum):
    STARTING = "STARTING"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    HOME_PAGE = "HOME_PAGE"
    SEARCH_PAGE = "SEARCH_PAGE"
    SEARCHING = "SEARCHING"
    COLLECTING = "COLLECTING"
    PARSING = "PARSING"
    SHORTLISTING = "SHORTLISTING"
    APPLYING = "APPLYING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    WAITING_FOR_CAPTCHA = "WAITING_FOR_CAPTCHA"
    WAITING_FOR_OTP = "WAITING_FOR_OTP"
    WAITING_FOR_LOGIN = "WAITING_FOR_LOGIN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Allowed transitions. "Waiting" states can be entered from any active state
# (a CAPTCHA/OTP/login can interrupt anything) and return to where work resumes.
_ACTIVE = {
    WorkflowState.STARTING, WorkflowState.HOME_PAGE, WorkflowState.SEARCH_PAGE,
    WorkflowState.SEARCHING, WorkflowState.COLLECTING, WorkflowState.PARSING,
    WorkflowState.SHORTLISTING, WorkflowState.APPLYING,
}
_WAITING = {
    WorkflowState.WAITING_FOR_USER, WorkflowState.WAITING_FOR_CAPTCHA,
    WorkflowState.WAITING_FOR_OTP, WorkflowState.WAITING_FOR_LOGIN,
    WorkflowState.LOGIN_REQUIRED,
}
_TERMINAL = {WorkflowState.COMPLETED, WorkflowState.FAILED}

_ALLOWED: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.STARTING: {WorkflowState.HOME_PAGE, WorkflowState.LOGIN_REQUIRED,
                             WorkflowState.COLLECTING, WorkflowState.FAILED},
    WorkflowState.LOGIN_REQUIRED: {WorkflowState.WAITING_FOR_LOGIN,
                                   WorkflowState.HOME_PAGE, WorkflowState.FAILED},
    WorkflowState.HOME_PAGE: {WorkflowState.SEARCH_PAGE, WorkflowState.SEARCHING,
                              WorkflowState.COLLECTING, WorkflowState.FAILED},
    WorkflowState.SEARCH_PAGE: {WorkflowState.SEARCHING, WorkflowState.COLLECTING,
                                WorkflowState.FAILED},
    WorkflowState.SEARCHING: {WorkflowState.COLLECTING, WorkflowState.PARSING,
                              WorkflowState.SEARCH_PAGE, WorkflowState.FAILED},
    WorkflowState.COLLECTING: {WorkflowState.PARSING, WorkflowState.SHORTLISTING,
                               WorkflowState.SEARCHING, WorkflowState.COMPLETED,
                               WorkflowState.FAILED},
    WorkflowState.PARSING: {WorkflowState.SHORTLISTING, WorkflowState.COLLECTING,
                            WorkflowState.FAILED},
    WorkflowState.SHORTLISTING: {WorkflowState.APPLYING, WorkflowState.COMPLETED,
                                 WorkflowState.FAILED},
    WorkflowState.APPLYING: {WorkflowState.SHORTLISTING, WorkflowState.COMPLETED,
                             WorkflowState.COLLECTING, WorkflowState.FAILED},
    # Waiting states resume back into active work.
    WorkflowState.WAITING_FOR_USER: _ACTIVE | _TERMINAL,
    WorkflowState.WAITING_FOR_CAPTCHA: _ACTIVE | _TERMINAL,
    WorkflowState.WAITING_FOR_OTP: _ACTIVE | _TERMINAL,
    WorkflowState.WAITING_FOR_LOGIN: _ACTIVE | _TERMINAL,
    WorkflowState.COMPLETED: set(),
    WorkflowState.FAILED: set(),
}

# Any active state may be interrupted by a waiting state.
for _s in _ACTIVE:
    _ALLOWED.setdefault(_s, set()).update(_WAITING)


@dataclass
class Transition:
    frm: WorkflowState
    to: WorkflowState
    reason: str
    at: float = field(default_factory=time)


class StateMachine:
    """Tracks the current workflow state and validates every transition."""

    def __init__(self, initial: WorkflowState = WorkflowState.STARTING,
                 strict: bool = False):
        self.state = initial
        self.strict = strict
        self.history: list[Transition] = []

    def can(self, to: WorkflowState) -> bool:
        return to in _ALLOWED.get(self.state, set())

    def to(self, to: WorkflowState, reason: str = "") -> WorkflowState:
        if to == self.state:
            return self.state
        if not self.can(to):
            msg = (f"Unexpected state transition {self.state.value} -> {to.value} "
                   f"({reason or 'no reason given'})")
            if self.strict:
                raise InvalidTransition(msg)
            logger.warning(msg)  # visible, never hidden -- but no crash
        else:
            logger.info("State %s -> %s | reason=%s",
                        self.state.value, to.value, reason or "-")
        self.history.append(Transition(self.state, to, reason))
        self.state = to
        return self.state

    def is_waiting(self) -> bool:
        return self.state in _WAITING

    def is_terminal(self) -> bool:
        return self.state in _TERMINAL


class InvalidTransition(Exception):
    """Raised only in strict mode when a transition is not allowed."""

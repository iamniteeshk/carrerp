"""What to do with a saved approval when the process is running again.

The browser page from the previous process is gone. ``submit`` means re-open
the same job and submit. ``wait`` means leave it untouched. ``ask`` means
fill once and send Telegram.
"""

from __future__ import annotations


def pending_state_may_submit(state: str | None, note: str | None = "") -> bool:
    """A saved proceed submits only when Telegram wrote it.

    A dashboard Apply used to store ``proceed`` with a dashboard note. That
    note is not a Telegram Proceed and must not submit.
    """
    if (state or "").strip().lower() != "proceed":
        return False
    if "dashboard" in (note or "").lower():
        return False
    return True


def next_pending_action(state: str | None, reply: str | None,
                        note: str | None = "") -> str:
    state = (state or "").strip().lower()
    reply = (reply or "").strip().lower()
    if reply == "proceed" or pending_state_may_submit(state, note):
        return "submit"
    if state == "reject" or reply == "reject":
        return "reject"
    if state == "waiting" or "dashboard" in (note or "").lower():
        return "wait"
    return "ask"

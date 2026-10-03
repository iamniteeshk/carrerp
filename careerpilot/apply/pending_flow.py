"""What to do with a saved approval when the process is running again.

The browser page from the previous process is gone. ``submit`` means re-open
the same job and submit. ``wait`` means leave it untouched. ``ask`` means
fill once and send Telegram.
"""

from __future__ import annotations


def next_pending_action(state: str | None, reply: str | None) -> str:
    state = (state or "").strip().lower()
    reply = (reply or "").strip().lower()
    if state == "proceed" or reply == "proceed":
        return "submit"
    if state == "reject" or reply == "reject":
        return "reject"
    if state == "waiting":
        return "wait"
    return "ask"

"""Live status sink for the Browser Inspector.

A single shared object that both the Browser Engine and the pipeline write to,
so the on-page debug panel (and logs) can show everything happening right now --
browser state, workflow state, search, location, job number/title, mouse, scroll,
cards, current open job, rule decision, AI status, resume, CSV/DB status, retry
count, portal, URL, wait reason.

Writers update fields they own; the panel renders the whole dict. Keeping it a
plain shared sink preserves engine separation (no engine imports another).
"""

from __future__ import annotations

from threading import Lock


_FIELDS = [
    "stage", "browser_state", "workflow_state", "search", "location", "job_number",
    "job_title", "mouse", "hover_target", "scroll", "visible_cards",
    "parsed_cards", "open_job", "reading_section", "reading_ms",
    "extracted_fields", "missing_fields", "rule_decision", "ai_status",
    "resume", "csv_status", "db_status", "retry_count", "portal", "url",
    "wait_reason",
]


class LiveStatus:
    def __init__(self):
        self._lock = Lock()
        self._data = {f: "-" for f in _FIELDS}

    def set(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                self._data[k] = v

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def as_panel(self) -> dict:
        """Human-titled view for the on-page panel."""
        d = self.get()
        titles = {
            "stage": "Current Stage",
            "browser_state": "Browser State", "workflow_state": "Workflow",
            "search": "Search", "location": "Location",
            "job_number": "Job #", "job_title": "Job Title", "mouse": "Mouse",
            "hover_target": "Hover", "scroll": "Scroll",
            "visible_cards": "Cards Visible", "parsed_cards": "Cards Parsed",
            "open_job": "Open Job", "reading_section": "Reading Section",
            "reading_ms": "Time Reading (ms)", "extracted_fields": "Extracted",
            "missing_fields": "Missing Fields", "rule_decision": "Rule",
            "ai_status": "AI", "resume": "Resume", "csv_status": "CSV",
            "db_status": "DB", "retry_count": "Retries", "portal": "Portal",
            "url": "URL", "wait_reason": "Wait Reason",
        }
        return {titles.get(k, k): d.get(k, "-") for k in _FIELDS}

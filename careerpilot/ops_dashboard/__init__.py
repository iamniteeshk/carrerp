"""CareerPilot Operations Dashboard (FastAPI + Jinja2 + HTMX).

Read-mostly Mission Control over the local network. Reuses the existing
database, logs, reports, scheduler, browser, and AI runtime — it does not
re-implement the CareerPilot engine.
"""

from .app import create_ops_dashboard, start_ops_dashboard_thread

__all__ = ["create_ops_dashboard", "start_ops_dashboard_thread"]

"""HTML page routes (Jinja2 + HTMX fragments)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import AuthConfig, get_csrf, is_authenticated, login_user, logout_user
from .. import queries
from ..runtime import HUB

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["pages"])


def _ctx(request: Request, **extra) -> dict:
    cfg = HUB.config
    return {
        "csrf": get_csrf(request),
        "phase": HUB.current_phase(),
        "paused": HUB.paused,
        "app_name": getattr(cfg, "app_name", "CareerPilot") if cfg else "CareerPilot",
        "apply_mode": getattr(getattr(cfg, "apply", None), "mode", "") if cfg else "",
        **extra,
    }


def _render(request: Request, name: str, status_code: int = 200, **extra):
    """Starlette ≥1.x: TemplateResponse(request, name, context=...)."""
    return templates.TemplateResponse(
        request, name, context=_ctx(request, **extra), status_code=status_code)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    auth: AuthConfig = request.app.state.auth
    if is_authenticated(request, auth):
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html", error="", auth_required=auth.auth_required)


@router.post("/login")
async def login_submit(request: Request, password: str = Form(""),
                       next: str = Form("/")):
    auth: AuthConfig = request.app.state.auth
    if auth.verify(password):
        login_user(request)
        dest = next if next.startswith("/") else "/"
        return RedirectResponse(dest, status_code=303)
    return _render(request, "login.html", status_code=401,
                   error="Invalid password", auth_required=True)


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def mission_control(request: Request):
    return _render(request, "mission.html", page="mission")


@router.get("/home", response_class=HTMLResponse)
async def home(request: Request):
    return _render(request, "home.html", page="home")


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return _render(request, "jobs.html", page="jobs")


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: int):
    db = HUB.db
    data = queries.get_job(db, job_id) if db else None
    return _render(request, "job_detail.html", page="jobs", data=data, job_id=job_id)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return _render(request, "reports.html", page="reports")


@router.get("/csv", response_class=HTMLResponse)
async def csv_page(request: Request, path: str = ""):
    return _render(request, "csv.html", page="csv", selected=path)


@router.get("/ai", response_class=HTMLResponse)
async def ai_page(request: Request):
    return _render(request, "ai.html", page="ai")


@router.get("/profiles", response_class=HTMLResponse)
async def profiles_page(request: Request):
    return _render(request, "profiles.html", page="profiles")


@router.get("/config", response_class=HTMLResponse)
async def config_summary_page(request: Request):
    return _render(request, "config_summary.html", page="config")


@router.get("/config/health", response_class=HTMLResponse)
async def config_health_page(request: Request):
    return _render(request, "config_health.html", page="config_health")


@router.get("/browser", response_class=HTMLResponse)
async def browser_page(request: Request):
    return _render(request, "browser.html", page="browser")


@router.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request):
    return _render(request, "scheduler.html", page="scheduler")


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    return _render(request, "health.html", page="health")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return _render(request, "settings.html", page="settings")


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request):
    return _render(request, "notifications.html", page="notifications")


@router.get("/partials/feed", response_class=HTMLResponse)
async def partial_feed(request: Request):
    from ..activity import FEED
    events = FEED.recent(80)
    if not events and HUB.db:
        events = queries.activity_from_db(HUB.db, 80)
    return _render(request, "partials/feed.html", events=events)

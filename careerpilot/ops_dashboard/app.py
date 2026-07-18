"""FastAPI Operations Dashboard factory + threaded uvicorn launcher."""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from ..core.logging_setup import get_logger
from .auth import AuthConfig, AuthGateMiddleware, configured_password, is_loopback
from .activity import FEED
from .runtime import HUB

logger = get_logger(__name__)

_PKG = Path(__file__).resolve().parent
_STATIC = _PKG / "static"
_TEMPLATES = _PKG / "templates"


def create_ops_dashboard(
    *,
    db=None,
    config=None,
    host: str | None = None,
    port: int | None = None,
    refresh_seconds: int = 5,
    password: str | None = None,
    session_hours: int = 12,
) -> FastAPI:
    """Build the ops dashboard app. Runtime objects may be bound later via HUB."""
    if db is not None or config is not None:
        HUB.bind(config=config or HUB.config, db=db or HUB.db)
        if db is not None:
            FEED.bind_db(db)

    bind_host = host or (getattr(config, "dashboard_host", None) if config else None) or "0.0.0.0"
    bind_port = port or (getattr(config, "dashboard_port", None) if config else None) or 8006
    pwd = password if password is not None else configured_password(
        getattr(config, "dashboard_password_env", "DASHBOARD_PASSWORD")
        if config else "DASHBOARD_PASSWORD")
    auth = AuthConfig(
        password=pwd,
        session_hours=int(getattr(config, "dashboard_session_hours", session_hours)
                          if config else session_hours),
        bind_host=bind_host,
    )
    if auth.require_password_for_lan and not is_loopback(bind_host) and not pwd:
        logger.warning(
            "Ops dashboard binds to %s without DASHBOARD_PASSWORD — "
            "refusing open LAN access. Set DASHBOARD_PASSWORD in .env.",
            bind_host)
        # Force auth gate on; login will always fail until password is set.
        auth = AuthConfig(password="__unset__", session_hours=session_hours,
                          bind_host=bind_host)
        # Override verify to always fail until real password configured.
        auth.verify = lambda _c: False  # type: ignore

    app = FastAPI(title="CareerPilot Ops", docs_url="/api/docs", redoc_url=None)
    app.state.auth = auth
    app.state.refresh_seconds = int(
        getattr(config, "dashboard_refresh_seconds", refresh_seconds)
        if config else refresh_seconds)
    app.state.bind_host = bind_host
    app.state.bind_port = int(bind_port)

    secret = os.getenv("DASHBOARD_SESSION_SECRET") or secrets.token_hex(32)
    # Middleware is applied in reverse order of addition: Session must wrap Auth.
    app.add_middleware(AuthGateMiddleware, auth=auth)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="cp_ops_session",
        max_age=auth.session_hours * 3600,
        same_site="lax",
        https_only=False,
    )

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    from .api import router as api_router
    from .routes import router as pages_router
    from .websocket import router as ws_router

    app.include_router(pages_router)
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "phase": HUB.current_phase()}

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Ops dashboard error on %s: %s", request.url.path, exc)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse({"error": "internal error"}, status_code=500)

    return app


def start_ops_dashboard_thread(
    *,
    db=None,
    config=None,
    host: str | None = None,
    port: int | None = None,
    **kwargs,
) -> threading.Thread:
    """Run uvicorn in a daemon thread (same pattern as the legacy Flask dashboard)."""
    import uvicorn

    app = create_ops_dashboard(db=db, config=config, host=host, port=port, **kwargs)
    bind_host = app.state.bind_host
    bind_port = app.state.bind_port

    def _run():
        try:
            uvicorn.run(
                app, host=bind_host, port=bind_port,
                log_level="warning", access_log=False)
        except Exception:  # noqa: BLE001
            logger.exception("Ops dashboard server crashed")

    t = threading.Thread(target=_run, name="ops-dashboard", daemon=True)
    t.start()
    logger.info("Ops dashboard at http://%s:%s", bind_host, bind_port)
    return t

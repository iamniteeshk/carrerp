"""Session auth + CSRF for the ops dashboard.

Password comes from env (DASHBOARD_PASSWORD by default). Empty password is only
allowed when binding to loopback; LAN binds require a password.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware


def password_hash(password: str, salt: str = "") -> str:
    material = f"{salt}:{password}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def configured_password(env_name: str = "DASHBOARD_PASSWORD") -> str:
    return (os.getenv(env_name) or os.getenv("CAREERPILOT_DASHBOARD_PASSWORD") or "").strip()


def is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


class AuthConfig:
    def __init__(self, *, password: str, session_hours: int = 12,
                 require_password_for_lan: bool = True, bind_host: str = "127.0.0.1"):
        self.password = password
        self.session_hours = max(1, int(session_hours))
        self.require_password_for_lan = require_password_for_lan
        self.bind_host = bind_host
        self.salt = secrets.token_hex(8)
        self._expected = password_hash(password, self.salt) if password else ""

    @property
    def auth_required(self) -> bool:
        if self.password:
            return True
        if self.require_password_for_lan and not is_loopback(self.bind_host):
            return True
        return False

    def verify(self, candidate: str) -> bool:
        if not self.password:
            return not self.auth_required
        got = password_hash(candidate, self.salt)
        return hmac.compare_digest(got, self._expected)


def get_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def require_csrf(request: Request, csrf_token: str = Form(...)) -> None:
    expected = request.session.get("csrf")
    if not expected or not hmac.compare_digest(str(csrf_token), str(expected)):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def is_authenticated(request: Request, auth: AuthConfig) -> bool:
    if not auth.auth_required:
        return True
    try:
        return bool(request.session.get("authenticated"))
    except AssertionError:
        return False


def login_user(request: Request) -> None:
    request.session["authenticated"] = True
    request.session["login_at"] = secrets.token_hex(4)
    get_csrf(request)


def logout_user(request: Request) -> None:
    request.session.clear()


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated browser requests to /login; JSON 401 for /api."""

    PUBLIC_PREFIXES = (
        "/login", "/logout", "/static/", "/healthz", "/favicon",
    )

    def __init__(self, app, auth: AuthConfig):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not self.auth.auth_required:
            return await call_next(request)
        if any(path.startswith(p) for p in self.PUBLIC_PREFIXES):
            return await call_next(request)
        if is_authenticated(request, self.auth):
            return await call_next(request)
        accept = request.headers.get("accept") or ""
        if path.startswith("/api/") or path.startswith("/ws/"):
            if "text/html" in accept:
                return RedirectResponse(url="/login", status_code=303)
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse(url=f"/login?next={path}", status_code=303)

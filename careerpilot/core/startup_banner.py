"""Startup banner — version / git / runtime fingerprint for support."""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _git(cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            ["git", *cmd], capture_output=True, text=True, timeout=5,
            cwd=str(Path.cwd()))
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def _playwright_version() -> str:
    try:
        import playwright
        return getattr(playwright, "__version__", "?")
    except Exception:  # noqa: BLE001
        return "(not installed)"


def _chrome_version(channel: str = "chrome") -> str:
    try:
        from .windows_env import find_browser
        ok, path = find_browser(channel or "")
        if not ok or "bundled" in path.lower():
            return path if ok else "(not found)"
        # Best-effort version via --version (Chrome on Windows often ignores it;
        # still try).
        r = subprocess.run([path, "--version"], capture_output=True, text=True,
                           timeout=8)
        out = (r.stdout or r.stderr or "").strip()
        return out or path
    except Exception:  # noqa: BLE001
        return "(unknown)"


def _schema_version(db_path: str) -> str:
    try:
        from ..db.database import Database
        db = Database(db_path)
        conn = db.connect()
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        db.close()
        return str(row["v"] if row and row["v"] is not None else 0)
    except Exception:  # noqa: BLE001
        return "(n/a)"


def build_banner(config=None) -> str:
    from .. import __version__
    channel = ""
    db_path = "database/careerpilot.db"
    provider = "(none)"
    mode = "(n/a)"
    cfg_path = "config/config.yaml"
    if config is not None:
        channel = getattr(getattr(config, "browser", None), "channel", "") or ""
        db_path = getattr(config, "database_path", db_path)
        provider = getattr(getattr(config, "ai", None), "active_provider", "") or "(none)"
        mode = getattr(getattr(config, "apply", None), "mode", "") or "(n/a)"
        cfg_path = getattr(config, "source_path", cfg_path) or cfg_path

    commit = _git(["rev-parse", "--short", "HEAD"]) or "(unknown)"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "(unknown)"
    dirty = _git(["status", "--porcelain"])
    if dirty:
        commit += " (dirty)"

    lines = [
        "========== CareerPilot STARTUP ==========",
        f"version           = {__version__}",
        f"git commit        = {commit}",
        f"git branch        = {branch}",
        f"python            = {sys.version.split()[0]} ({platform.system()} "
        f"{platform.release()})",
        f"playwright        = {_playwright_version()}",
        f"browser channel   = {channel or '(bundled chromium)'}",
        f"chrome/edge       = {_chrome_version(channel)}",
        f"config            = {cfg_path}",
        f"apply mode        = {mode}",
        f"AI provider       = {provider}",
        f"database schema   = v{_schema_version(db_path)}",
        f"startup time      = {datetime.now(timezone.utc).isoformat()}",
        "========================================",
    ]
    return "\n".join(lines)

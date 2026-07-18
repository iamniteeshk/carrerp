"""Host environment checks for production deployment (esp. Windows).

Used by the doctor. Pure detection helpers -- no Playwright browser launch
(that belongs in doctor browser checks). Safe to import on Linux/macOS; Windows-
specific probes return SKIP/None off-platform.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path


MIN_PYTHON = (3, 10)
MIN_DISK_GB = 2.0
DASHBOARD_PORT_DEFAULT = 5000


def is_windows() -> bool:
    return sys.platform.startswith("win")


def python_version_ok() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PYTHON
    msg = f"{v.major}.{v.minor}.{v.micro} (need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)"
    return ok, msg


def git_installed() -> tuple[bool, str]:
    path = shutil.which("git")
    if not path:
        return False, "git not found on PATH"
    return True, path


def pip_working() -> tuple[bool, str]:
    try:
        import pip  # noqa: F401
        return True, f"pip {getattr(pip, '__version__', '?')}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def venv_active_or_present(root: Path | None = None) -> tuple[bool, str]:
    """True if running inside a venv, or a .venv exists next to the project."""
    in_venv = (hasattr(sys, "real_prefix")
               or sys.prefix != getattr(sys, "base_prefix", sys.prefix))
    if in_venv:
        return True, f"active ({sys.prefix})"
    root = root or Path.cwd()
    for name in (".venv", "venv"):
        d = root / name
        if is_windows():
            py = d / "Scripts" / "python.exe"
        else:
            py = d / "bin" / "python"
        if py.exists():
            return True, f"present at {d} (not activated in this process)"
    return False, "no .venv found — run setup_windows.ps1 or python -m venv .venv"


def chrome_install_paths() -> list[Path]:
    """Candidate Google Chrome executable paths (Windows + common others)."""
    paths: list[Path] = []
    if is_windows():
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        for base in (pf, pf86, local):
            if not base:
                continue
            paths.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        paths.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            w = shutil.which(name)
            if w:
                paths.append(Path(w))
    return paths


def edge_install_paths() -> list[Path]:
    paths: list[Path] = []
    if is_windows():
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        for base in (pf, pf86):
            paths.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return paths


def find_browser(channel: str = "chrome") -> tuple[bool, str]:
    """Locate system Chrome or Edge for Playwright channel= chrome|msedge.

    An empty / chromium channel means bundled Playwright Chromium — always OK.
    """
    raw = "" if channel is None else str(channel)
    channel = raw.strip().lower()
    if channel in ("", "chromium"):
        return True, "bundled Chromium (Playwright) — no system browser required"
    candidates = chrome_install_paths() if channel.startswith("chrome") else edge_install_paths()
    for p in candidates:
        if p.exists():
            return True, str(p)
    # Also honour PATH lookups.
    which_names = {
        "chrome": ["chrome", "google-chrome", "google-chrome-stable"],
        "msedge": ["msedge", "microsoft-edge"],
    }
    for name in which_names.get(channel, which_names.get("chrome", [])):
        w = shutil.which(name)
        if w:
            return True, w
    label = "Google Chrome" if channel.startswith("chrome") else "Microsoft Edge"
    return False, (f"{label} not found (install it, or set browser.channel: \"\" "
                   f"for bundled Chromium)")


def windows_version() -> tuple[bool, str]:
    if not is_windows():
        return True, f"{platform.system()} {platform.release()} (not Windows)"
    ver = platform.version()
    release = platform.release()
    # Windows 10 = 10.0; Windows 11 still reports release "10" with build >= 22000.
    build = 0
    try:
        # platform.version() often looks like '10.0.22631'
        parts = ver.split(".")
        if len(parts) >= 3:
            build = int(parts[2])
    except ValueError:
        pass
    ok = release in ("10", "11") or build >= 19041
    label = "Windows 11" if build >= 22000 else f"Windows {release}"
    return ok, f"{label} (build {build or '?'})"


def disk_free_gb(path: str | Path = ".") -> tuple[bool, str]:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        ok = free_gb >= MIN_DISK_GB
        return ok, f"{free_gb:.1f} GB free (need >= {MIN_DISK_GB:.0f} GB)"
    except OSError as exc:
        return False, str(exc)


def port_available(host: str = "127.0.0.1", port: int = DASHBOARD_PORT_DEFAULT) -> tuple[bool, str]:
    """True if we can bind the port (or it is already ours — treat as OK with warn)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return True, f"{host}:{port} available"
            except OSError:
                # Something is listening — may be a prior CareerPilot instance.
                return False, (f"{host}:{port} is in use — stop the other process "
                               f"or change dashboard.port in config")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def internet_ok(timeout: float = 5.0) -> tuple[bool, str]:
    """Lightweight connectivity check (DNS + TCP to a public HTTPS endpoint)."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://www.google.com/generate_204", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if code in (204, 200):
                return True, "HTTPS reachability OK"
            return True, f"reachable (HTTP {code})"
    except Exception as exc:  # noqa: BLE001
        # Fallback: raw TCP to 1.1.1.1:443
        try:
            with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
                return True, "TCP 443 OK (HTTPS probe failed: %s)" % exc
        except Exception as exc2:  # noqa: BLE001
            return False, f"no internet: {exc2}"


def path_writable(path: str | Path) -> tuple[bool, str]:
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".careerpilot_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, str(p.resolve())
    except OSError as exc:
        return False, f"cannot write to {p}: {exc}"


def playwright_browser_installed() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return False, f"playwright import failed: {exc}"
    try:
        with sync_playwright() as pw:
            exe = pw.chromium.executable_path
        if exe and Path(exe).exists():
            return True, exe
        return False, "chromium executable missing — run: python -m playwright install chromium"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc} — run: python -m playwright install chromium"

"""Browser layer: a single Playwright instance for the whole process.

ROOT-CAUSE NOTE. Playwright's Sync API binds an asyncio event loop to the thread
that starts it. Starting ``sync_playwright()`` a *second* time on the same thread
(e.g. once per portal) makes the second call raise
"Playwright Sync API inside the asyncio loop". The fix is structural: exactly one
``BrowserManager`` owns exactly one ``sync_playwright()`` instance for the whole
process and hands out one persistent context per portal. Portals never start
Playwright themselves.

Persistent login is preserved via one on-disk user-data-dir per portal, so logins
survive restarts even though the framework keeps a single browser engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.logging_setup import get_logger

logger = get_logger(__name__)

try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - import guard for environments w/o PW
    _PLAYWRIGHT_AVAILABLE = False

_VALID_ENGINES = ("chromium", "firefox", "webkit")
_CHROMIUM_CHANNELS = ("msedge", "chrome", "chrome-beta", "msedge-beta", "msedge-dev")


@dataclass
class BrowserConfig:
    """Configuration-driven browser settings (no hardcoded engine)."""

    engine: str = "chromium"          # chromium | firefox | webkit
    channel: str = "msedge"           # msedge | chrome | "" (bundled Chromium)
    headless: bool = False
    viewport_width: int = 1366
    viewport_height: int = 900
    profiles_path: str = "profiles_browser"
    timeout_seconds: int = 30
    # Page-readiness waiting (SPA-aware). domcontentloaded is NOT "ready" for a
    # JS site -- these control how long we wait for the page to actually render.
    networkidle_timeout_ms: int = 8000   # max wait for network to go quiet
    render_settle_ms: int = 800          # small final paint margin (tunable)
    scroll_passes: int = 3               # natural scrolls to trigger lazy-load
    open_jobs: bool = True              # open each job's page to read full JD

    def normalized_engine(self) -> str:
        engine = (self.engine or "chromium").strip().lower()
        return engine if engine in _VALID_ENGINES else "chromium"


def build_launch_plan(cfg: BrowserConfig, user_data_dir: str | Path) -> tuple[str, dict]:
    """Return (engine_attr_name, launch_kwargs) for launch_persistent_context.

    Pure function -- no Playwright needed -- so it is unit-testable. ``channel``
    and the anti-automation arg apply only to the chromium engine.
    """
    engine = cfg.normalized_engine()
    kwargs: dict[str, Any] = {
        "user_data_dir": str(user_data_dir),
        "headless": bool(cfg.headless),
        "viewport": {"width": int(cfg.viewport_width),
                     "height": int(cfg.viewport_height)},
    }
    if engine == "chromium":
        kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
        channel = (cfg.channel or "").strip().lower()
        if channel:
            if channel not in _CHROMIUM_CHANNELS:
                logger.warning("Unknown chromium channel '%s'; using bundled Chromium",
                               channel)
            else:
                kwargs["channel"] = channel
    return engine, kwargs


class BrowserManager:
    """Owns the single Playwright instance and one persistent context per portal.

    Thread note: Playwright sync objects are bound to the thread that created
    them. All scans run on one scheduler worker thread (see Scheduler), so the
    single instance is created and reused consistently on that thread.
    """

    def __init__(self, cfg: BrowserConfig):
        self.cfg = cfg
        self._pw: Any = None
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}

    # ---- internal -------------------------------------------------------

    def _ensure_pw(self) -> None:
        if self._pw is not None:
            return
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright "
                "&& playwright install chromium")
        self._pw = sync_playwright().start()

    def profile_dir(self, portal: str) -> Path:
        d = Path(self.cfg.profiles_path) / portal.lower()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _launch_context(self, portal: str) -> Any:
        self._ensure_pw()
        engine_name, kwargs = build_launch_plan(self.cfg, self.profile_dir(portal))
        engine = getattr(self._pw, engine_name)
        logger.info("Launching %s (%s, headless=%s) for %s",
                    engine_name, kwargs.get("channel", "bundled"),
                    kwargs["headless"], portal)
        try:
            context = engine.launch_persistent_context(**kwargs)
        except Exception as exc:  # noqa: BLE001
            # Cross-platform fallback: configured channel (e.g. msedge on a Mac
            # without Edge) may be absent -> fall back to bundled Chromium.
            if engine_name == "chromium" and "channel" in kwargs:
                bad = kwargs.pop("channel")
                logger.warning("Browser channel '%s' unavailable (%s); falling back "
                               "to bundled Chromium. Set browser.channel: \"\" to "
                               "silence.", bad, exc)
                context = engine.launch_persistent_context(**kwargs)
            else:
                raise
        context.set_default_timeout(self.cfg.timeout_seconds * 1000)
        return context

    # ---- public API used by portals (via BrowserSession) ----------------

    @staticmethod
    def _page_alive(page: Any) -> bool:
        if page is None:
            return False
        try:
            return not page.is_closed()
        except Exception:  # noqa: BLE001
            return False

    def page(self, portal: str) -> Any:
        if portal not in self._contexts:
            ctx = self._launch_context(portal)
            self._contexts[portal] = ctx
            self._pages[portal] = ctx.pages[0] if ctx.pages else ctx.new_page()
            return self._pages[portal]
        stored = self._pages.get(portal)
        if self._page_alive(stored):
            return stored
        ctx = self._contexts[portal]
        for tab in ctx.pages:
            if self._page_alive(tab):
                self._pages[portal] = tab
                if stored is not None:
                    logger.info("Recovered %s page from open context tab", portal)
                return tab
        self._pages[portal] = ctx.new_page()
        logger.warning("All tabs closed for %s; opened a fresh page", portal)
        return self._pages[portal]

    def new_page(self, portal: str) -> Any:
        """Open a fresh tab in the portal's context (for opening a job without
        disturbing the results page). Caller must close it."""
        self.page(portal)  # ensure context exists
        return self._contexts[portal].new_page()

    def is_healthy(self, portal: str) -> bool:
        ctx = self._contexts.get(portal)
        page = self._pages.get(portal)
        if ctx is None or page is None:
            return False
        try:
            return not page.is_closed()
        except Exception:  # noqa: BLE001
            return False

    def ensure_healthy(self, portal: str) -> Any:
        """Restart a dead context for ``portal`` (auto-recovery). No-op if never
        started -- the first ``page()`` call will lazily start it."""
        if portal not in self._contexts:
            return None
        if self.is_healthy(portal):
            return self._pages[portal]
        logger.warning("Browser for %s unhealthy; restarting", portal)
        self.close_portal(portal)
        return self.page(portal)

    def screenshot(self, portal: str, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page(portal).screenshot(path=str(path))
            return str(path)
        except Exception as exc:  # noqa: BLE001 - screenshots must never crash flow
            logger.warning("Screenshot failed: %s", exc)
            return ""

    def close_portal(self, portal: str) -> None:
        ctx = self._contexts.pop(portal, None)
        self._pages.pop(portal, None)
        if ctx is not None:
            try:
                ctx.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing context for %s: %s", portal, exc)

    def close_all(self) -> None:
        """Close every context and stop Playwright -- no leaks, no orphans."""
        for portal in list(self._contexts):
            self.close_portal(portal)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error stopping Playwright: %s", exc)
            self._pw = None


class BrowserSession:
    """Per-portal facade over the shared BrowserManager.

    Preserves the API the portal classes use (``page``, ``screenshot``,
    ``ensure_healthy``, ``close``, ``profile_dir``) while ensuring there is only
    ever one Playwright instance for the process.
    """

    def __init__(self, portal: str, manager: BrowserManager):
        self.portal = portal
        self.manager = manager

    @property
    def profile_dir(self) -> Path:
        return self.manager.profile_dir(self.portal)

    @property
    def page(self) -> Any:
        return self.manager.page(self.portal)

    def new_tab(self) -> Any:
        """Open a job in a separate tab; the results page stays put."""
        return self.manager.new_page(self.portal)

    def screenshot(self, path: str | Path) -> str:
        return self.manager.screenshot(self.portal, path)

    def is_healthy(self) -> bool:
        return self.manager.is_healthy(self.portal)

    def ensure_healthy(self) -> Any:
        return self.manager.ensure_healthy(self.portal)

    def restart(self) -> Any:
        self.manager.close_portal(self.portal)
        return self.manager.page(self.portal)

    def close(self) -> None:
        self.manager.close_portal(self.portal)

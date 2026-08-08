"""Collector manager.

Job discovery is delegated to each portal's ``search()``. The manager runs
collectors independently with error isolation: if LinkedIn fails, Naukri still
runs (P002 §9). Collectors only collect and normalize -- no filtering, no AI,
no applying (P009).
"""

from __future__ import annotations

from pathlib import Path
from time import strftime

from ..ai.vision import capture_page_screenshot, check_login_vision
from ..browser.base_portal import (BasePortal, CaptchaRequired, LoginRequired,
                                    OTPRequired)
from ..core.logging_setup import get_logger
from ..core.models import Job

logger = get_logger(__name__)


class CollectorManager:
    def __init__(self, portals: list[BasePortal], keywords: list[str],
                 locations: list[str], human=None, *,
                 vision_cfg=None, settings=None, screenshot_dir: str = "screenshots"):
        self.portals = portals
        self.keywords = keywords
        self.locations = locations
        self.human = human  # optional HumanInteractionEngine
        self.vision_cfg = vision_cfg
        self.settings = settings
        self.screenshot_dir = Path(screenshot_dir)

    def _pause(self, portal: BasePortal, kind: str, reason: str) -> None:
        if not self.human:
            return
        try:
            self.human.pause(portal.session.page, kind, reason,
                             portal=portal.portal_name)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
            logger.warning("Diagnostic capture failed for %s: %s",
                           portal.portal_name, exc)

    def _vision_enabled(self) -> bool:
        cfg = self.vision_cfg
        if cfg is None:
            return False
        enabled = bool(getattr(cfg, "login_check", True))
        if self.settings is not None:
            override = self.settings.get("vision_login_enabled")
            if override is not None:
                enabled = str(override).lower() in ("1", "true", "yes", "on")
        return enabled

    def _raise_emergency(self, portal: str, reason: str) -> None:
        payload = {
            "active": True,
            "portal": portal,
            "reason": reason,
            "at": strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if self.settings is not None:
            try:
                self.settings.set_json("emergency_login", payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to persist emergency_login: %s", exc)
        logger.error("EMERGENCY LOGIN | portal=%s | %s", portal, reason)

    def _clear_emergency(self, portal: str) -> None:
        if self.settings is None:
            return
        cur = self.settings.get_json("emergency_login") or {}
        if cur.get("active") and cur.get("portal") == portal:
            cur["active"] = False
            cur["cleared_at"] = strftime("%Y-%m-%dT%H:%M:%S")
            self.settings.set_json("emergency_login", cur)

    def _vision_login_check(self, portal: BasePortal) -> None:
        """Compulsory vision confirm after DOM login check. Raises LoginRequired."""
        if not self._vision_enabled():
            return
        cfg = self.vision_cfg
        # Dashboard may override model / base_url
        base_url = getattr(cfg, "base_url", "http://127.0.0.1:11434/v1")
        model = getattr(cfg, "model", "qwen2-vl:7b")
        timeout = int(getattr(cfg, "timeout_seconds", 90) or 90)
        if self.settings is not None:
            base_url = self.settings.get("vision_base_url", base_url) or base_url
            model = self.settings.get("vision_model", model) or model
        dest = (self.screenshot_dir / "vision_login"
                / f"{portal.portal_name}_{strftime('%Y%m%d-%H%M%S')}.png")
        path = capture_page_screenshot(portal.session.page, dest)
        if not path:
            # Screenshot failure is not treated as logout — DOM already passed.
            logger.warning("%s: vision screenshot failed; trusting DOM login",
                           portal.portal_name)
            return
        result = check_login_vision(
            path, portal=portal.portal_name, base_url=base_url, model=model,
            api_key=getattr(cfg, "api_key", "") or "", timeout=timeout)
        if result.error and "vision unreachable" in (result.error or ""):
            logger.warning("%s: vision unreachable (%s); trusting DOM login",
                           portal.portal_name, result.error)
            return
        if not result.logged_in:
            reason = f"Vision login check failed: {result.reason}"
            self._raise_emergency(portal.portal_name, reason)
            self._pause(portal, "login", reason)
            raise LoginRequired(reason)
        self._clear_emergency(portal.portal_name)
        logger.info("%s: vision login OK (%s)", portal.portal_name, result.reason)

    def collect_all(self) -> list[Job]:
        """Collect from every portal; one portal's failure never stops others."""
        all_jobs: list[Job] = []
        self.collect_streaming(all_jobs.append)
        logger.info("Collection workflow complete | total_jobs=%s", len(all_jobs))
        return all_jobs

    def collect_streaming(self, on_job, should_open=None) -> None:
        """Event-driven collection: ``on_job(job)`` is invoked the instant each
        job is discovered, so the pipeline processes it immediately instead of
        waiting for the whole scan. One portal's failure never stops others.

        ``should_open(card_job) -> bool`` is an optional cheap gate: cards that
        fail it are NOT opened (the search space is narrowed before opening) but
        are still streamed so the pipeline records a terminal outcome.
        """
        logger.info("Collection workflow start (streaming) | portals=%s | "
                    "titles=%s | locations=%s",
                    [p.portal_name for p in self.portals],
                    len(self.keywords), len(self.locations))
        for portal in self.portals:
            attempts = 0
            while attempts < 2:
                attempts += 1
                try:
                    logger.info("Collector %s: ensuring browser health",
                                portal.portal_name)
                    portal.ensure_healthy()
                    logger.info("Collector %s: verifying login", portal.portal_name)
                    portal.ensure_logged_in()
                    self._vision_login_check(portal)
                    jobs = portal.search(self.keywords, self.locations, on_job=on_job,
                                         should_open=should_open)
                    logger.info("Collector %s finished | %s jobs streamed",
                                portal.portal_name, len(jobs))
                    break
                except LoginRequired as exc:
                    logger.warning("Collector %s paused: login required -- skipping",
                                   portal.portal_name)
                    self._raise_emergency(portal.portal_name, str(exc))
                    self._pause(portal, "login", str(exc))
                    break
                except OTPRequired as exc:
                    logger.warning("Collector %s paused: OTP required -- skipping",
                                   portal.portal_name)
                    self._raise_emergency(portal.portal_name, str(exc))
                    self._pause(portal, "otp", str(exc))
                    break
                except CaptchaRequired as exc:
                    logger.warning("Collector %s paused: CAPTCHA detected -- skipping",
                                   portal.portal_name)
                    self._raise_emergency(portal.portal_name, str(exc))
                    self._pause(portal, "captcha", str(exc))
                    break
                except Exception as exc:  # noqa: BLE001 - isolate per-portal failure
                    logger.warning("Collector %s failed (attempt %s): %s",
                                   portal.portal_name, attempts, exc)
                    try:
                        from ..core.win_events import EventKind, write_event
                        write_event(EventKind.BROWSER,
                                    f"{portal.portal_name} collector error: {exc}")
                        if attempts < 2:
                            write_event(EventKind.RECOVERY,
                                        f"Restarting browser for {portal.portal_name}")
                            portal.ensure_healthy()
                            import time
                            time.sleep(min(2 ** attempts, 30))
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                    logger.warning("Collector %s giving up -- continuing with others",
                                   portal.portal_name)
                    break
        logger.info("Collection workflow complete (streaming)")

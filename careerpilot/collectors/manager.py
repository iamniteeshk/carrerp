"""Collector manager.

Job discovery is delegated to each portal's ``search()``. The manager runs
collectors independently with error isolation: if LinkedIn fails, Naukri still
runs (P002 §9). Collectors only collect and normalize -- no filtering, no AI,
no applying (P009).
"""

from __future__ import annotations

from ..browser.base_portal import (BasePortal, CaptchaRequired, LoginRequired,
                                    OTPRequired)
from ..core.logging_setup import get_logger
from ..core.models import Job

logger = get_logger(__name__)


class CollectorManager:
    def __init__(self, portals: list[BasePortal], keywords: list[str],
                 locations: list[str], human=None):
        self.portals = portals
        self.keywords = keywords
        self.locations = locations
        self.human = human  # optional HumanInteractionEngine

    def _pause(self, portal: BasePortal, kind: str, reason: str) -> None:
        if not self.human:
            return
        try:
            self.human.pause(portal.session.page, kind, reason,
                             portal=portal.portal_name)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
            logger.warning("Diagnostic capture failed for %s: %s",
                           portal.portal_name, exc)

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
                    jobs = portal.search(self.keywords, self.locations, on_job=on_job,
                                         should_open=should_open)
                    logger.info("Collector %s finished | %s jobs streamed",
                                portal.portal_name, len(jobs))
                    break
                except LoginRequired as exc:
                    logger.warning("Collector %s paused: login required -- skipping",
                                   portal.portal_name)
                    self._pause(portal, "login", str(exc))
                    break
                except OTPRequired as exc:
                    logger.warning("Collector %s paused: OTP required -- skipping",
                                   portal.portal_name)
                    self._pause(portal, "otp", str(exc))
                    break
                except CaptchaRequired as exc:
                    logger.warning("Collector %s paused: CAPTCHA detected -- skipping",
                                   portal.portal_name)
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

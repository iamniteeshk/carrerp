#!/usr/bin/env python3
"""Minimal Playwright validation OUTSIDE the CareerPilot scan workflow.

Proves whether Chrome + Naukri + the saved profile are stable before blaming
application code. Run:

    python scripts/validate_chrome_browser.py
    python scripts/validate_chrome_browser.py --job-url "https://www.naukri.com/..."

Exit 0 = browser survived the full sequence. Exit 1 = crash or error.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_SEARCH = (
    "https://www.naukri.com/director-jobs-in-chennai?experience=15")
DEFAULT_JOB = ""  # optional; if empty only search page is tested


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


def _lifecycle_hooks(context, page, events: list[str]) -> None:
    def record(kind: str, detail: str = "") -> None:
        line = f"{kind} | url={_safe_url(page)} | {detail}"
        events.append(line)
        _log(line)

    try:
        context.on("close", lambda: record("CONTEXT_CLOSE",
                                            f"stack={_short_stack()}"))
    except Exception as exc:  # noqa: BLE001
        _log(f"hook context.close failed: {exc}")
    try:
        browser = getattr(context, "browser", None)
        if browser is not None:
            browser.on("disconnected", lambda: record(
                "BROWSER_DISCONNECTED", f"stack={_short_stack()}"))
    except Exception as exc:  # noqa: BLE001
        _log(f"hook browser.disconnected failed: {exc}")
    try:
        page.on("close", lambda: record("PAGE_CLOSE", f"stack={_short_stack()}"))
        page.on("crash", lambda: record("PAGE_CRASH", f"stack={_short_stack()}"))
    except Exception as exc:  # noqa: BLE001
        _log(f"hook page events failed: {exc}")


def _safe_url(page) -> str:
    try:
        return page.url or "(blank)"
    except Exception:  # noqa: BLE001
        return "(closed)"


def _short_stack(limit: int = 6) -> str:
    return "".join(traceback.format_stack(limit=limit)[:-1]).replace("\n", " | ")


def run_validation(*, profile_dir: str, search_url: str, job_url: str,
                   channel: str, headless: bool, wait_s: float) -> int:
    from careerpilot.browser.session import BrowserConfig, build_launch_plan

    events: list[str] = []
    _log(f"VALIDATE_BROWSER_START | channel={channel} | profile={profile_dir}")
    _log("This script is OUTSIDE CareerPilot -- only Playwright + Chrome + profile.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _log("FAIL | Playwright not installed (pip install playwright)")
        return 1

    cfg = BrowserConfig(channel=channel, headless=headless)
    _, kwargs = build_launch_plan(cfg, profile_dir)
    _log(f"Launch plan | engine=chromium | channel={kwargs.get('channel', 'bundled')} "
         f"| headless={kwargs['headless']}")

    pw = None
    context = None
    try:
        pw = sync_playwright().start()
        engine = pw.chromium
        context = engine.launch_persistent_context(**kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        _lifecycle_hooks(context, page, events)

        _log(f"STEP 1 | goto search | {search_url}")
        page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
        _log(f"STEP 1 OK | url={page.url}")
        time.sleep(wait_s)

        if job_url:
            _log(f"STEP 2 | goto job URL | {job_url}")
            page.goto(job_url, wait_until="domcontentloaded", timeout=60_000)
            _log(f"STEP 2 OK | url={page.url}")
            time.sleep(wait_s)
        else:
            _log("STEP 2 skipped (no --job-url); search-page stability only")

        if page.is_closed():
            _log("FAIL | page closed before normal shutdown")
            return 1
        _log("VALIDATE_BROWSER_PASS | Chrome remained stable through navigation")
        return 0
    except Exception as exc:  # noqa: BLE001
        _log(f"FAIL | {type(exc).__name__}: {exc}")
        if events:
            _log("Lifecycle events captured before failure:")
            for e in events:
                _log(f"  {e}")
        return 1
    finally:
        if context is not None:
            try:
                _log("INTENTIONAL_CLOSE | context.close() from validate script")
                context.close()
            except Exception as exc:  # noqa: BLE001
                _log(f"context.close error: {exc}")
        if pw is not None:
            try:
                _log("INTENTIONAL_STOP | playwright.stop() from validate script")
                pw.stop()
            except Exception as exc:  # noqa: BLE001
                _log(f"playwright.stop error: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Minimal Chrome + Naukri browser stability validation")
    parser.add_argument("--channel", default="chrome",
                        help="Playwright chromium channel (default: chrome)")
    parser.add_argument("--profile-dir", default="profiles_browser/naukri/chrome",
                        help="Persistent user-data-dir (channel-specific recommended)")
    parser.add_argument("--search-url", default=DEFAULT_SEARCH)
    parser.add_argument("--job-url", default=DEFAULT_JOB,
                        help="Optional job URL to open after search")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--wait", type=float, default=3.0,
                        help="Seconds to wait on each page")
    args = parser.parse_args()

    if args.channel.lower() == "msedge":
        _log("WARN | msedge requested -- use chrome for this milestone validation")

    return run_validation(
        profile_dir=args.profile_dir,
        search_url=args.search_url,
        job_url=args.job_url,
        channel=args.channel,
        headless=args.headless,
        wait_s=args.wait,
    )


if __name__ == "__main__":
    raise SystemExit(main())

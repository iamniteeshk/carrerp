"""Visual Debug Mode for the Browser Engine.

A permanent, config-driven instrument that makes the browser's behaviour fully
observable: coloured element overlays, a live on-page status panel, configurable
pauses, per-selector and per-scroll diagnostics, a saved evidence bundle, and a
JSON timeline -- so you never have to guess what the browser saw or did.

It is deterministic and AI-free. When ``visual_mode`` is off, every method is a
cheap no-op and CareerPilot behaves exactly as before.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import strftime, time
from typing import Any

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.browser.debug")

# Default overlay colours (element kind -> CSS colour).
DEFAULT_COLORS = {
    "job_card": "#e53935",     # red
    "button": "#1e88e5",       # blue
    "search_box": "#43a047",   # green
    "pagination": "#fb8c00",   # orange
    "easy_apply": "#8e24aa",   # purple
    "current_card": "#ffd600", # yellow (highlighted card)
}


@dataclass
class DebugConfig:
    visual_mode: bool = False
    pause_after_navigation_seconds: float = 0.0
    pause_before_scroll_seconds: float = 0.0
    pause_after_scroll_seconds: float = 0.0
    evidence_dir: str = "debug"
    log_first_n_jobs: int = 5
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))


@dataclass
class _Timeline:
    events: list = field(default_factory=list)

    def mark(self, name: str, detail: str = "") -> None:
        self.events.append({"event": name, "detail": detail, "t": time()})


class VisualDebugger:
    """Drives all Visual Debug Mode behaviour. No-op when disabled."""

    def __init__(self, cfg: DebugConfig | None = None):
        self.cfg = cfg or DebugConfig()
        self._page_counters: dict[str, int] = {}
        self.timeline = _Timeline()
        self.live_status = None   # optional diagnostics.LiveStatus (the Inspector)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.visual_mode)

    # ---- timeline -------------------------------------------------------

    def mark(self, name: str, detail: str = "") -> None:
        if self.enabled:
            self.timeline.mark(name, detail)

    def reset_timeline(self) -> None:
        self.timeline = _Timeline()

    # ---- pauses (debug-only; gated entirely behind visual_mode) ---------

    def pause(self, page, which: str) -> None:
        if not self.enabled:
            return
        secs = {
            "after_navigation": self.cfg.pause_after_navigation_seconds,
            "before_scroll": self.cfg.pause_before_scroll_seconds,
            "after_scroll": self.cfg.pause_after_scroll_seconds,
        }.get(which, 0.0)
        if secs and secs > 0:
            logger.info("[debug] pause %s for %ss", which, secs)
            _safe(lambda: page.wait_for_timeout(int(secs * 1000)))

    # ---- overlays -------------------------------------------------------

    def highlight(self, page, selector: str, kind: str, label: str = "") -> int:
        """Outline every element matching ``selector``. Returns matched count."""
        if not self.enabled or not selector:
            return 0
        color = self.cfg.colors.get(kind, "#e53935")
        js = """
        (args) => {
          const [sel, color, label] = args;
          const els = Array.from(document.querySelectorAll(sel));
          els.forEach((el, i) => {
            el.style.outline = '3px solid ' + color;
            el.style.outlineOffset = '-1px';
            if (label) {
              const tag = document.createElement('div');
              tag.textContent = label + ' #' + (i+1);
              tag.style.cssText = 'position:absolute;z-index:2147483646;font:11px monospace;'
                + 'background:'+color+';color:#fff;padding:1px 4px;';
              const r = el.getBoundingClientRect();
              tag.style.top = (window.scrollY + r.top) + 'px';
              tag.style.left = (window.scrollX + r.left) + 'px';
              document.body.appendChild(tag);
            }
          });
          return els.length;
        }
        """
        n = _safe(lambda: page.evaluate(js, [selector, color, label]), 0) or 0
        logger.info("[debug] highlight %s (%s) -> %s matched", kind, selector, n)
        return n

    def highlight_card(self, page, selector: str, index: int) -> None:
        """Highlight the single card currently being processed (yellow)."""
        if not self.enabled or not selector:
            return
        color = self.cfg.colors.get("current_card", "#ffd600")
        js = """
        (args) => {
          const [sel, idx, color] = args;
          const els = document.querySelectorAll(sel);
          if (els[idx]) {
            els[idx].style.outline = '4px solid ' + color;
            els[idx].scrollIntoView({block:'center'});
          }
        }
        """
        _safe(lambda: page.evaluate(js, [selector, index, color]))

    # ---- live status panel ---------------------------------------------

    def panel(self, page, info: dict) -> None:
        if not self.enabled:
            return
        # The live Browser Inspector: merge the shared status sink (pipeline +
        # browser fields) so the panel shows everything happening right now.
        if self.live_status is not None:
            merged = self.live_status.as_panel()
            merged.update(info)   # this page's fresh values win
            info = merged
        rows = "".join(
            f"<div style='display:flex;justify-content:space-between;gap:12px'>"
            f"<b>{k}</b><span>{v}</span></div>" for k, v in info.items())
        js = """
        (html) => {
          let p = document.getElementById('cp-debug-panel');
          if (!p) {
            p = document.createElement('div'); p.id = 'cp-debug-panel';
            p.style.cssText = 'position:fixed;top:10px;right:10px;z-index:2147483647;'
              + 'background:rgba(20,20,20,.92);color:#fff;font:12px monospace;'
              + 'padding:10px 12px;border-radius:8px;min-width:200px;'
              + 'box-shadow:0 2px 12px rgba(0,0,0,.5);';
            document.body.appendChild(p);
          }
          p.innerHTML = "<div style='font-weight:700;margin-bottom:6px'>CareerPilot Debug</div>" + html;
        }
        """
        _safe(lambda: page.evaluate(js, rows))

    # ---- diagnostics ----------------------------------------------------

    def selector_diagnostics(self, page, selectors: dict[str, str]) -> dict:
        """For each named selector: matched / visible / hidden counts."""
        if not self.enabled:
            return {}
        out: dict[str, dict] = {}
        js = """
        (sel) => {
          const els = Array.from(document.querySelectorAll(sel));
          let visible = 0;
          els.forEach(el => {
            const r = el.getBoundingClientRect();
            const vis = r.width>0 && r.height>0 && getComputedStyle(el).visibility!=='hidden'
              && getComputedStyle(el).display!=='none';
            if (vis) visible++;
          });
          return {matched: els.length, visible: visible};
        }
        """
        for name, sel in selectors.items():
            if not sel:
                continue
            r = _safe(lambda s=sel: page.evaluate(js, s), {"matched": 0, "visible": 0})
            r = r or {"matched": 0, "visible": 0}
            r["hidden"] = max(0, r["matched"] - r["visible"])
            out[name] = r
            logger.info("[debug] selector %s (%s) | matched=%s visible=%s hidden=%s",
                        name, sel, r["matched"], r["visible"], r["hidden"])
        return out

    def scroll_diagnostics(self, page, pass_n: int, new: int, dups: int,
                           total: int) -> dict:
        if not self.enabled:
            return {}
        js = ("() => ({y: window.scrollY, dh: document.body.scrollHeight, "
              "vh: window.innerHeight})")
        m = _safe(lambda: page.evaluate(js), {"y": 0, "dh": 0, "vh": 0}) or {}
        pct = int(100 * (m.get("y", 0) + m.get("vh", 0)) / m["dh"]) if m.get("dh") else 0
        logger.info("[debug] Pass %s | scroll=%spx/%spx (%s%%) | new=%s dups=%s total=%s",
                    pass_n, m.get("y", 0), m.get("dh", 0), pct, new, dups, total)
        return {"pass": pass_n, "scroll_y": m.get("y", 0),
                "doc_height": m.get("dh", 0), "viewport": m.get("vh", 0),
                "scroll_pct": pct, "new": new, "duplicates": dups, "total": total}

    def scroll_pct(self, page) -> int:
        if not self.enabled:
            return 0
        js = ("() => { const dh=document.body.scrollHeight; return dh ? "
              "Math.round(100*(window.scrollY+window.innerHeight)/dh) : 0; }")
        return _safe(lambda: page.evaluate(js), 0) or 0

    # ---- logging the first N jobs --------------------------------------

    def log_first_jobs(self, jobs: list) -> None:
        if not self.enabled:
            return
        for j in jobs[: self.cfg.log_first_n_jobs]:
            logger.info("[debug] job | title=%s | company=%s | location=%s | "
                        "salary=%s | easy_apply=%s | url=%s",
                        getattr(j, "job_title", "?"), getattr(j, "company", "?"),
                        getattr(j, "location", "?"), getattr(j, "salary", "n/a"),
                        getattr(j, "is_easy_apply", "?"), getattr(j, "job_url", "?"))

    # ---- anomaly: confirmed results but zero cards ---------------------

    def zero_results_anomaly(self, page, portal: str, selectors: dict[str, str],
                             browser_state: str) -> None:
        """results_confirmed=True but visible_cards=0 -- never continue silently."""
        if not self.enabled:
            return
        logger.warning("[debug] ANOMALY: results confirmed but 0 cards on %s | "
                       "url=%s -- saving diagnostics", portal, _safe(lambda: page.url, ""))
        diag = self.selector_diagnostics(page, selectors)
        self.save_evidence(page, portal, parsed_jobs=[],
                           browser_state={"state": browser_state, "anomaly": True,
                                          "selectors": diag})

    # ---- evidence bundle ------------------------------------------------

    def save_evidence(self, page, portal: str, parsed_jobs: list,
                      browser_state: dict) -> str:
        if not self.enabled:
            return ""
        n = self._page_counters.get(portal, 0) + 1
        self._page_counters[portal] = n
        folder = (Path(self.cfg.evidence_dir) / "session" / portal.lower()
                  / f"page_{n:03d}")
        folder.mkdir(parents=True, exist_ok=True)

        _safe(lambda: page.screenshot(path=str(folder / "screenshot.png"),
                                      full_page=True))
        _safe(lambda: (folder / "page.html").write_text(page.content()))
        _safe(lambda: (folder / "parsed_jobs.json").write_text(
            json.dumps([_job_dict(j) for j in parsed_jobs], indent=2)))
        state = dict(browser_state)
        state.update({"url": _safe(lambda: page.url, ""),
                      "timestamp": strftime("%Y-%m-%d %H:%M:%S"),
                      "portal": portal})
        _safe(lambda: (folder / "browser_state.json").write_text(
            json.dumps(state, indent=2)))
        _safe(lambda: (folder / "timeline.json").write_text(
            json.dumps(self.timeline.events, indent=2)))
        logger.info("[debug] evidence saved -> %s", folder)
        return str(folder)


def _job_dict(j: Any) -> dict:
    if isinstance(j, dict):
        return j
    return {k: getattr(j, k, None) for k in
            ("job_title", "company", "location", "salary", "experience",
             "is_easy_apply", "job_url", "job_description")}


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - debug must never crash the run
        logger.debug("[debug] op failed: %s", exc)
        return default

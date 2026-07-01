"""One-shot DOM export.

Dumps everything about the current page into a folder: HTML, full-page and
viewport screenshots, parsed jobs, selectors used + match counts, console log,
network log, browser state, timeline, and JSON metadata. One call / one command.
Never raises into the caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import strftime

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.diagnostics.exporter")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("export op failed: %s", exc)
        return default


def selector_report(page, selectors: dict) -> dict:
    """matched / visible / hidden / first-match-text for each named selector."""
    report: dict = {}
    js = """
    (sel) => {
      const els = Array.from(document.querySelectorAll(sel));
      let visible = 0, first = '';
      els.forEach(el => {
        const r = el.getBoundingClientRect();
        const vis = r.width>0 && r.height>0
          && getComputedStyle(el).visibility!=='hidden'
          && getComputedStyle(el).display!=='none';
        if (vis) visible++;
      });
      if (els[0]) first = (els[0].innerText||'').trim().slice(0,120);
      return {matched: els.length, visible: visible, first_match_text: first};
    }
    """
    for name, sel in (selectors or {}).items():
        if not sel:
            continue
        r = _safe(lambda s=sel: page.evaluate(js, s),
                  {"matched": 0, "visible": 0, "first_match_text": ""}) or {}
        r["hidden"] = max(0, r.get("matched", 0) - r.get("visible", 0))
        r["selector"] = sel
        report[name] = r
        if r.get("matched", 0) == 0:
            logger.warning("[selector] FAILED -- '%s' (%s) matched 0 elements",
                           name, sel)
        else:
            logger.info("[selector] %s (%s) matched=%s visible=%s hidden=%s | "
                        "first='%s'", name, sel, r["matched"], r["visible"],
                        r["hidden"], r.get("first_match_text", ""))
    return report


def export_page(page, dest: str | Path, *, meta: dict | None = None,
                selectors: dict | None = None, parsed: list | None = None,
                recorder=None, timeline: list | None = None) -> str:
    """Write the full evidence/export bundle for ``page`` into ``dest``."""
    folder = Path(dest)
    folder.mkdir(parents=True, exist_ok=True)

    _safe(lambda: (folder / "page.html").write_text(page.content()))
    _safe(lambda: page.screenshot(path=str(folder / "page.png"), full_page=True))
    _safe(lambda: page.screenshot(path=str(folder / "viewport.png"),
                                  full_page=False))
    _safe(lambda: (folder / "raw_page_text.txt").write_text(
        page.inner_text("body")))

    sel_report = selector_report(page, selectors or {})
    _safe(lambda: (folder / "selectors.json").write_text(
        json.dumps(sel_report, indent=2)))

    _safe(lambda: (folder / "parsed.json").write_text(
        json.dumps([_jobish(j) for j in (parsed or [])], indent=2)))

    scroll = _safe(lambda: page.evaluate(
        "() => ({y: window.scrollY, h: document.body.scrollHeight, "
        "vh: window.innerHeight})"), {}) or {}

    metadata = dict(meta or {})
    metadata.update({
        "url": _safe(lambda: page.url, ""),
        "timestamp": strftime("%Y-%m-%d %H:%M:%S"),
        "scroll_position": scroll,
        "selector_match_counts": {k: v.get("matched", 0)
                                  for k, v in sel_report.items()},
    })
    _safe(lambda: (folder / "browser_state.json").write_text(
        json.dumps(metadata, indent=2)))
    _safe(lambda: (folder / "metadata.json").write_text(
        json.dumps(metadata, indent=2)))

    if timeline is not None:
        _safe(lambda: (folder / "timeline.json").write_text(
            json.dumps(timeline, indent=2)))
    if recorder is not None:
        recorder.save(folder)
    else:
        # Always leave the console/network files present (empty if no recorder).
        _safe(lambda: (folder / "console.log").write_text(""))
        _safe(lambda: (folder / "network.json").write_text("[]"))

    logger.info("[export] page exported -> %s", folder)
    return str(folder)


def _jobish(j) -> dict:
    if isinstance(j, dict):
        return j
    keys = ("job_title", "company", "location", "salary", "experience",
            "is_easy_apply", "job_url", "job_description")
    return {k: getattr(j, k, None) for k in keys}

"""Apply-mode names.

Three operating modes:

* ``dry_run`` — fill the application, record every answer, stop on the
  submit page without clicking Submit.
* ``approval`` — same fill, then ask on Telegram. Proceed submits; Reject stops.
* ``auto`` — submit without asking, then notify which job was applied to.

``live`` remains for older configs: it asks when ``require_final_confirmation``
is on, and submits when that flag is off.
"""

from __future__ import annotations

VALID_APPLY_MODES = ("dry_run", "approval", "auto", "live")

_ALIASES = {
    "dry": "dry_run",
    "dryrun": "dry_run",
    "dry_run": "dry_run",
    "approval": "approval",
    "approve": "approval",
    "auto": "auto",
    "automatic": "auto",
    "live": "live",
}


def normalize_apply_mode(mode: str | None) -> str:
    raw = (mode or "dry_run").strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(raw, raw)


def is_dry_mode(mode: str | None) -> bool:
    return normalize_apply_mode(mode) == "dry_run"

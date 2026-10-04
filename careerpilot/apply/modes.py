"""Apply-mode names.

Three operating modes:

* ``dry_run`` — fill the application, record every answer, stop on the
  submit page without clicking Submit.
* ``approval`` — same fill, then ask on Telegram. Proceed submits; Reject stops.
* ``auto`` — the only mode that submits without an explicit Proceed.

Anything else fails safe. The older name ``live`` is approval (it never
submits on its own). A blank or unknown name is ``dry_run``.
"""

from __future__ import annotations

VALID_APPLY_MODES = ("dry_run", "approval", "auto")

_ALIASES = {
    "dry": "dry_run",
    "dryrun": "dry_run",
    "dry_run": "dry_run",
    "approval": "approval",
    "approve": "approval",
    "auto": "auto",
    "automatic": "auto",
    # Older configs used "live". It must not become auto-submit.
    "live": "approval",
}


def normalize_apply_mode(mode: str | None) -> str:
    raw = (mode or "dry_run").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return "dry_run"
    return _ALIASES.get(raw, raw)


def canonical_apply_mode(mode: str | None) -> str:
    """A mode that is safe to act on. Unknown values become dry_run."""
    normalized = normalize_apply_mode(mode)
    if normalized in VALID_APPLY_MODES:
        return normalized
    return "dry_run"


def is_dry_mode(mode: str | None) -> bool:
    return canonical_apply_mode(mode) == "dry_run"

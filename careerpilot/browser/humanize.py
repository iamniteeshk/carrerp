"""Human-like browsing for the Browser Engine.

Makes the browser behave like a person rather than a script: gradual scrolling
(small/medium steps, pauses, occasional upward correction, slight randomness),
content-based reading pauses (longer text -> longer pause, not a fixed sleep),
and eased mouse movement with slight overshoot.

Deterministic and testable: all randomness comes from a single seeded RNG, so a
given seed reproduces the same behaviour. When ``enabled`` is false every method
is a no-op and the engine behaves exactly as before. AI-free.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.browser.human")


@dataclass
class HumanConfig:
    enabled: bool = False
    words_per_minute: int = 220      # realistic careful-reading speed (was 350)
    min_read_ms: int = 900           # never glance for <0.9s (was 400)
    max_read_ms: int = 12000         # a long JD section can take up to 12s
    scroll_step_min_px: int = 120    # smaller, gentler notches (was 250)
    scroll_step_max_px: int = 380    # (was 650) -- no big jumps
    scroll_pause_min_ms: int = 600   # pause between notches (was 250)
    scroll_pause_max_ms: int = 1800  # (was 900) -- linger like a reader
    upward_correction_chance: float = 0.15
    mouse_moves: bool = True
    seed: int | None = None          # set for reproducible behaviour/tests


class Humanizer:
    def __init__(self, cfg: HumanConfig | None = None, recorder=None):
        self.cfg = cfg or HumanConfig()
        self.rng = random.Random(self.cfg.seed)
        self._last_x: float | None = None
        self._last_y: float | None = None
        self.recorder = recorder   # optional InteractionRecorder (diagnostics)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled)

    # ---- gradual, human-like scrolling ----------------------------------

    def scroll_one_screen(self, page) -> dict:
        """Scroll roughly one screenful in several small steps with pauses and
        an occasional small upward correction. Returns a small diagnostics dict.
        """
        if not self.enabled:
            # Fallback: single deterministic scroll (legacy behaviour).
            _safe(lambda: page.evaluate(
                "window.scrollBy(0, document.body.scrollHeight)"))
            return {"mode": "instant", "steps": 1}
        vh = _safe(lambda: page.evaluate("() => window.innerHeight"), 800) or 800
        target = vh
        moved = 0
        steps = 0
        while moved < target:
            step = self.rng.randint(self.cfg.scroll_step_min_px,
                                    self.cfg.scroll_step_max_px)
            _safe(lambda s=step: page.evaluate(f"window.scrollBy(0, {s})"))
            moved += step
            steps += 1
            self._pause(page, self.rng.randint(self.cfg.scroll_pause_min_ms,
                                               self.cfg.scroll_pause_max_ms))
            # Occasionally nudge back up a little, like a person re-reading.
            if self.rng.random() < self.cfg.upward_correction_chance:
                up = self.rng.randint(40, 140)
                _safe(lambda u=up: page.evaluate(f"window.scrollBy(0, -{u})"))
                steps += 1
                self._pause(page, self.rng.randint(120, 400))
        logger.info("[human] scrolled ~1 screen in %s steps (%spx)", steps, moved)
        if self.recorder is not None:
            self.recorder.scroll(moved)
        return {"mode": "human", "steps": steps, "pixels": moved}

    # ---- content-based reading pause ------------------------------------

    def reading_pause_ms(self, text: str) -> int:
        """Estimate reading time from content size (words / WPM), bounded."""
        words = len((text or "").split())
        ms = int(words / max(1, self.cfg.words_per_minute) * 60_000)
        return max(self.cfg.min_read_ms, min(self.cfg.max_read_ms, ms or
                                             self.cfg.min_read_ms))

    def read(self, page, text: str, label: str = "") -> int:
        if not self.enabled:
            return 0
        ms = self.reading_pause_ms(text)
        logger.info("[human] reading %s (%s words) ~%sms", label or "content",
                    len((text or "").split()), ms)
        self._pause(page, ms)
        return ms

    def incremental_read(self, page, text: str, *, recorder=None,
                         status_sink=None) -> dict:
        """Read a job page the way a person does: read the top, pause, scroll a
        slice, pause, read, scroll again -- until the end of the JD. The number
        of passes scales with content length; a short JD is read in 1-2 passes,
        a long JD in several. Deterministic under the seed. Returns a small
        reading timeline for diagnostics."""
        if not self.enabled:
            return {"passes": 0, "total_ms": 0, "timeline": []}
        words = len((text or "").split())
        passes = max(1, min(8, 1 + words // 120))   # ~120 words per screen
        timeline = []
        total = 0
        # Read the top section first (before any scrolling).
        total += self.read(page, (text or "")[:600], label="top section")
        timeline.append({"section": "top", "ms": total})
        if status_sink is not None:
            _safe(lambda: status_sink.set(reading_section="top section"))
        for i in range(passes):
            self.scroll_one_screen(page)
            seg = (text or "")[600 + i * 600: 600 + (i + 1) * 600] or "(continued)"
            ms = self.read(page, seg, label=f"section {i + 2}")
            total += ms
            timeline.append({"section": f"scroll_{i + 1}", "ms": ms})
            if recorder is not None:
                _safe(lambda s=i: recorder.record("read_section", section=s + 2))
            if status_sink is not None:
                _safe(lambda s=i: status_sink.set(
                    reading_section=f"section {s + 2}"))
        logger.info("[human] incremental read: %s passes, ~%sms total (%s words)",
                    passes + 1, total, words)
        return {"passes": passes + 1, "total_ms": total, "timeline": timeline}

    # ---- eased, curved mouse movement -----------------------------------

    def _bezier(self, x0, y0, x1, y1, steps):
        """Quadratic Bezier path with a randomized control point -> a natural
        curve rather than a straight robotic line."""
        cx = (x0 + x1) / 2 + self.rng.randint(-80, 80)
        cy = (y0 + y1) / 2 + self.rng.randint(-80, 80)
        pts = []
        for i in range(1, steps + 1):
            t = i / steps
            mt = 1 - t
            x = mt * mt * x0 + 2 * mt * t * cx + t * t * x1
            y = mt * mt * y0 + 2 * mt * t * cy + t * t * y1
            pts.append((x, y))
        return pts

    def move_mouse(self, page, x: float, y: float, steps: int = 0) -> None:
        if not self.enabled or not self.cfg.mouse_moves:
            return
        steps = steps or self.rng.randint(14, 28)
        x0 = self._last_x if self._last_x is not None else x - 200
        y0 = self._last_y if self._last_y is not None else y - 150
        # Curved path to a slight overshoot, then settle onto the target.
        ox = x + self.rng.randint(-14, 14)
        oy = y + self.rng.randint(-14, 14)
        for px, py in self._bezier(x0, y0, ox, oy, steps):
            _safe(lambda a=px, b=py: page.mouse.move(a, b))
        _safe(lambda: page.mouse.move(x, y))
        self._last_x, self._last_y = x, y
        if self.recorder is not None:
            self.recorder.mouse_move(x, y)

    def idle_move(self, page, width: int = 1200, height: int = 700) -> None:
        """Occasionally drift to a blank-ish area, like a person not clicking."""
        if not self.enabled or not self.cfg.mouse_moves:
            return
        if self.rng.random() < 0.5:
            self.move_mouse(page, self.rng.randint(50, width),
                            self.rng.randint(50, height))

    def hover_then_click(self, page, x: float, y: float) -> None:
        if not self.enabled:
            _safe(lambda: page.mouse.click(x, y))
            return
        self.move_mouse(page, x, y)
        self._pause(page, self.rng.randint(120, 450))  # pause before click
        _safe(lambda: page.mouse.click(x, y))

    @property
    def mouse_pos(self) -> tuple:
        return (self._last_x, self._last_y)

    # ---- internal -------------------------------------------------------

    def _pause(self, page, ms: int) -> None:
        if ms > 0:
            _safe(lambda: page.wait_for_timeout(ms))


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - human behaviour must never crash
        logger.debug("[human] op failed: %s", exc)
        return default

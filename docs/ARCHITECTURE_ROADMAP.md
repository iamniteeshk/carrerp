# CareerPilot Architecture Review & Roadmap

You asked for a review against a six-engine model (Browser, Vision, State, Rule,
AI, Human Interaction) where AI is a specialist reasoning engine, not a general
automation engine. This is the right philosophy. The good news is the codebase
already follows most of it. Below is the honest current state and an
evolutionary plan that does not require a rewrite.

## Current state vs. the target architecture

| Engine | Target | Where it lives today | Verdict |
|--------|--------|----------------------|---------|
| Browser | Deterministic, no AI | `browser/session.py` (BrowserManager + per-portal context), `browser/*_portal.py` | **Already there.** Zero AI imports in `browser/` (verified). Edge default, persistent profiles, recovery, screenshots, single Playwright instance. |
| Rule | Deterministic filtering | `rules/rule_engine.py`, `core/config.py` (RuleConfig) | **Already there.** No AI/browser imports. Salary/experience/location/title/blacklist/dedupe. |
| AI | The ONLY thing that talks to models | `ai/engine.py` (+ gemini/deepseek providers) | **Already isolated.** Only `main.py`, `pipeline.py`, `apply/auto_apply.py` call it; it never touches a `page`. Does fit-scoring + profile selection. |
| State | Explicit states + transitions | `core/state.py` (**new**) | **Was missing; now added.** Explicit `WorkflowState` + validated transitions, logged. Wired into the pipeline. |
| Human Interaction | Pause / save / notify / resume | exceptions (`LoginRequired`/`OTPRequired`/`CaptchaRequired`) + `core/human_interaction.py` (**new**) | **Partial → improved.** Now captures screenshot+HTML+state and notifies on pause. True "resume from exact point" still pending (Phase 3). |
| Vision | Deterministic CV fallback (OpenCV/OCR) | does not exist | **Intentionally not built yet** (see below). |

The separation you want between Browser, Rule, and AI is not something that needs
untangling — it is already enforced by the import graph. The AI engine cannot
drive the browser because it has no reference to it.

## What this change set already did (non-breaking, tested)

1. **State Engine** (`core/state.py`): the explicit state machine from your list
   (STARTING, LOGIN_REQUIRED, SEARCHING, COLLECTING, APPLYING, WAITING_FOR_*,
   COMPLETED, FAILED, ...). Every transition is validated and logged with a
   reason. Invalid transitions are logged loudly but do **not** raise in
   production, so the machine adds visibility without adding a crash path; tests
   use strict mode to assert the transition map. Wired into `pipeline.run_once`.
2. **Human Interaction Engine** (`core/human_interaction.py`): on a pause it
   saves a diagnostic bundle (screenshot + HTML + JSON state) and notifies
   Telegram, mapping each pause kind to the right WAITING_* state. Wired into the
   collector's pause branch. It never solves a challenge.
3. 14 new tests (state + navigation already in place); 63 total pass; doctor PASS.

## The Vision Engine: my honest recommendation — not yet

I did **not** build the Vision Engine, on purpose. Adding OpenCV/OCR now would be
a large subsystem with no caller, because the DOM-selector path it is meant to
back up is not finished yet. Computer vision is the correct *fallback* for when
selectors prove unreliable — but you cannot know which selectors are unreliable
until you have run the selector-based parsing against the live DOM. Building
vision first would be speculative scaffolding, which is exactly the kind of
unused complexity you have asked to avoid.

Recommended trigger: build the Vision Engine only for the specific spots where
selectors actually fail in practice (most likely CAPTCHA *presence* detection and
a couple of dynamic buttons), and keep it behind the same deterministic contract
as the rest of the browser layer. Until then it stays on this roadmap, not in
the code.

## Evolutionary roadmap (no rewrite)

**Phase 1 — done now.** State Engine + Human Interaction capture, wired in
additively. No behaviour removed.

**Phase 2 — finish the live-DOM selector layer.** Complete the
`# COMPLETE ON LIVE DOM` parsing in `linkedin_portal.py` / `naukri_portal.py`
(result cards, Easy-Apply flow). Drive each portal action through explicit state
transitions (SEARCH_PAGE → SEARCHING → PARSING). Still deterministic, still no
AI in the browser.

**Phase 3 — true pause/resume.** Persist the workflow position (a small job
queue + the current `WorkflowState`) to the database so that, after you clear a
CAPTCHA/OTP, the next tick resumes the exact remaining work instead of
re-running the scan. The State Engine and the diagnostic bundle from Phase 1 are
the foundation for this.

**Phase 4 — Vision Engine, only where selectors fail.** Introduce
`vision/` with OpenCV/OCR/template-matching helpers behind a deterministic
interface, called by the Browser Engine as a fallback locator. Scope it to the
real failure points found in Phases 2–3.

**Phase 5 — formalize the engine boundaries as packages.** Optionally move
`rules/`, `ai/`, `browser/`, and the new `core/state.py` + `core/human_interaction.py`
into clearly named `engines/` packages with thin public interfaces. This is
cosmetic/organizational and can be done last without behaviour change.

## Design guardrails to keep enforcing

- `browser/` must never import `ai/` (a one-line CI grep can enforce this).
- The AI engine returns *decisions* (score, profile name, text), never actions.
- Every workflow step goes through a `WorkflowState` transition — no hidden moves.
- Human Interaction Points pause + save + notify; they never auto-solve.

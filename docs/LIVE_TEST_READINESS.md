> **Stabilization update:** Navigation control flow (search URL building,
> page reuse, login gating, logging) is COMPLETE. The remaining live-DOM items
> are result-card PARSING and the Easy-Apply click flow only.

# Live Test Readiness — Remaining Browser Work

Everything except the items below is implemented and tested. These cannot be
finalized without a live, logged-in session, because the markup (LinkedIn
especially) is per-user and A/B-tested. **Do not let anyone fabricate these
selectors** — fill them in with your browser's inspector against your own
account, in `dry_run` mode, before enabling `live`.

Each item below corresponds to a `# COMPLETE ON LIVE DOM` marker in the code.

## LinkedIn (`careerpilot/browser/linkedin_portal.py`)

- [ ] **Logged-in detection** (line ~41): confirm the signal that the session is
      authenticated; otherwise raise `LoginRequired` / `OTPRequired`.
- [ ] **Search URL + navigation** (line ~55): build the jobs search URL from
      keywords/locations and load results.
- [ ] **Result parsing** (line ~67): select result-list items; extract title,
      company, location, URL, Easy-Apply flag into `Job` objects. Currently
      returns `[]`.
- [ ] **Easy Apply multi-step flow** (line ~86): click Easy Apply; loop the
      modal steps; upload `resume_path`; fill contact fields from the candidate;
      answer screening questions via `answer_fn`.
- [ ] **Submit + confirmation** (line ~100): click final Submit; read the
      confirmation and capture a portal reference.
- [ ] **CAPTCHA / checkpoint detection** (line ~112): detect the challenge and
      raise `CaptchaRequired` (re-import it) so a human is asked.
- [ ] **External ATS redirect**: when a job leaves LinkedIn to an external ATS,
      raise `ExternalATSRedirect` (already wired to "manual review").

## Naukri (`careerpilot/browser/naukri_portal.py`)

- [ ] **Logged-in detection** (line ~35): confirm the homepage logged-in state;
      otherwise raise `LoginRequired` (re-import `OTPRequired` if MFA appears).
- [ ] **Search URL + navigation** (line ~46): construct the Naukri search URL.
- [ ] **Result parsing** (line ~55): parse job cards into `Job` objects.
- [ ] **Apply flow** (line ~70): click Apply; handle the chatbot/questionnaire
      that Naukri often opens; answer via `answer_fn`.
- [ ] **Confirmation** (line ~83): confirm the applied state and capture a ref.

## ATS modules (not yet created)

These were planned but **do not exist** as code. They are not stubs to fill —
they are unwritten modules. Each would be a new `BasePortal` subclass:

- [ ] Workday
- [ ] Greenhouse
- [ ] Lever / others as needed

## Cross-cutting, before enabling `live`

- [ ] Run `dry_run` end-to-end and confirm the dashboard/CSV/Telegram outputs.
- [ ] Verify resume upload uses the **Document Manager** path (already wired) and
      that profile-supplied cover-letter *files* are uploaded (currently only
      AI-generated cover-letter *text* is passed; file upload is a live-DOM task).
- [ ] Confirm the first-run approval gate fires for the first N live applies.
- [ ] Keep `apply.mode: dry_run` until every box above is checked.

## Reminder on scope

The following are intentionally **out of scope** and must never be implemented:
account creation, password reset/recovery, OTP/verification-code harvesting that
bypasses human verification, and CAPTCHA solving. Security checkpoints pause for
a human.

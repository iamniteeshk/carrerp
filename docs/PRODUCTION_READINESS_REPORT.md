# CareerPilot — Production Readiness Report

> **Stabilization update (this release):** The Naukri Playwright crash is fixed at
> the root (single Playwright instance + single scan thread; verified with real
> Playwright launching two portal contexts and leaving zero orphan processes).
> Configuration is now a single `config.yaml`; `Example_Profile` is removed in
> favour of six real profiles with a `Default` fallback; all legacy/compat code
> is gone; 49 self-contained tests pass on a clean clone. The verdict below is
> unchanged: still **Alpha** — live LinkedIn/Naukri DOM automation is not built,
> so nothing is submitted to real sites yet.


**Date:** 2026-06-27
**Reviewer roles:** Architect / QA / Release / Python
**Verdict (summary):** **Alpha Ready** for dry-run and the decision pipeline.
**Not** beta or production ready. The core *application* function does not work
end-to-end against real sites yet, and the tool has never run live.

---

## The one thing to understand first

CareerPilot's *decision* pipeline is solid and tested. CareerPilot's *action*
— actually finding and submitting applications on LinkedIn/Naukri — **is not
implemented**. The portal `search()` methods return `[]` and `apply()` does not
submit; they are deliberate stubs marked `# COMPLETE ON LIVE DOM`. So if you ran
it against the real sites today, it would discover **zero** jobs and apply to
nothing. That is by design (selectors can't be written blind), but it means the
product's headline capability is not yet functional. Everything downstream of
discovery is real and tested; discovery and submission are not.

---

## 1. Architecture status

Clean and coherent for what exists. The standout property — profiles as
plug-ins — is enforced and proven by test, not just intended: the Career Profile
Engine is the only component that knows a specialization's contents; every other
module speaks `CareerProfile` objects. Adding "Cybersecurity" is a folder, with
a passing test that demonstrates it. Concurrency model is sound (single
overlap-protected scheduler thread + read-mostly dashboard + thread-local SQLite
with WAL). Separation of concerns is good; coupling is low.

## 2. Modules completed (implemented + tested)

Configuration Engine, Candidate Engine, Career Profile Engine, Document Manager,
Schema Validation, Rule Engine, AI Engine (Gemini + DeepSeek fallback, parsing,
profile selection), Apply Engine (gating/approval/mode — *minus* the live portal
call), Collector (isolation + self-heal), Browser Session lifecycle, Scheduler,
Database (migrations/backup/reconnect), Telegram, Reporting, Logging, Doctor.

## 3. Modules pending / not built

- **Human Interaction Point framework** — the uniform save→screenshot→log→
  notify→pause→**resume-from-exact-step** mechanism. Today the portals raise
  `LoginRequired`/`OTPRequired`/`CaptchaRequired`, and the apply engine queues
  the job and notifies — but there is **no resume-from-exact-step state machine**.
- **Queue Manager** — durable work queue. Not built.
- **State Recovery** — restart-surviving in-progress applications. Not built.
- **Portal Manager + ATS modules** (Workday, Greenhouse, etc.) — not built.
- **Live LinkedIn/Naukri automation** — stubs only (see §4).

## 4. Remaining live browser work

Full checklist in `docs/LIVE_TEST_READINESS.md`. Summary: LinkedIn and Naukri
each need logged-in detection, search URL + navigation, result parsing, the
apply/Easy-Apply flow, submit + confirmation capture, and CAPTCHA/checkpoint
detection — all against a live logged-in session, none to be fabricated. ATS
modules are unwritten, not stubbed.

## 5. Known limitations

- No live functionality yet (discovery returns nothing; nothing submits).
- Profile-supplied cover-letter *files* aren't uploaded yet (only AI-generated
  cover-letter *text* is passed); file upload is a live-DOM task.
- Dashboard is read-only and not covered by automated tests (smoke-import only).
- No automated retry/resume of a partially-completed application across restarts
  (depends on the unbuilt Queue Manager / State Recovery).
- Operating against these sites may violate their Terms of Service and risk your
  account. This is inherent to the use case, not a defect, and is your call.

## 6. Security review

- **Secrets:** only in `.env` (gitignored); never logged; never in source. Good.
- **Personal data:** only in `candidate.yaml` / `profiles/` (gitignored). The
  shippable repo was scanned and is clean of personal identifiers.
- **Boundaries honored:** no account creation, password reset, OTP harvesting, or
  CAPTCHA solving exists anywhere. Security checkpoints are designed to pause for
  a human (mechanism partially built — see §3).
- **Injection surface:** AI responses are parsed defensively (JSON extraction
  with fallback); the engine never executes returned content and never trusts an
  AI-returned profile name without mapping it through the engine.
- **Gaps:** no encryption at rest for the local SQLite DB (it contains job data
  and cached answers, not credentials). Acceptable for a single-user local
  deployment; note it if the machine is shared.

## 7. Performance review

Adequate for the workload (a few scans/day, tens of jobs). Deterministic rules
run before any paid AI call, minimizing cost. SQLite WAL handles the
single-writer/occasional-reader pattern comfortably. No obvious hot loops. AI
calls are the latency/cost driver and are bounded by `max_applications_per_day`
and the rule pre-filter. Not load-tested at high volume (not the use case).

## 8. Maintainability review

Good. Small, single-responsibility modules; consistent patterns; dependency
injection throughout (engines receive their collaborators). The plug-in boundary
means the highest-churn future work (new specializations, new portals) is
additive. Docs now reflect V2 (`ARCHITECTURE.md`, `TEST_PLAN.md`, refreshed
INSTALL/QUICKSTART/DEPLOYMENT/TROUBLESHOOTING).

## 9. Code quality review

- **Static analysis:** `pyflakes` clean (unused imports/dead code removed this
  pass). Type hints and docstrings present across modules.
- **Cleanups done this review:** removed dead `AIEngine.available()` and a
  speculative `DocumentManager.attachments_for()`; removed unused imports;
  replaced an unused-import availability check with `find_spec`; removed a
  hardcoded fallback profile/domain string; fixed an f-string-without-placeholder.
- **Remaining intentional API not yet consumed:** `Candidate.form_values()`,
  `CareerProfile.document()/all_documents()/cover_letter_file()`,
  `DocumentManager.cover_letter_for()/supporting_documents_for()`. These are the
  boundary contract that the live-DOM portal work will consume; documented here
  rather than hidden. Mild, deliberate forward-API.

## 10. Technical debt

- Live portal automation is the dominant debt (the product can't function without
  it).
- Human Interaction Points exist only as exception+queue+notify, not the full
  resume state machine.
- No durable queue / state recovery.
- Dashboard untested by automation.
- Cover-letter file upload not wired.

## 11. Recommended improvements (priority order)

1. Build the **Human Interaction Point** state machine (Phase 2) — it's the
   safety-critical core and everything else routes through it.
2. Complete **LinkedIn** live automation end-to-end in `dry_run`, verify, then a
   tightly-capped `live` test.
3. Build **Queue Manager + State Recovery** so a restart never loses or
   double-submits in-flight work.
4. Then **Naukri**, then **ATS** modules.
5. Add dashboard tests and wire cover-letter file upload.

## 12. Production readiness percentage

- Non-browser decision core (config, profiles, rules, AI, DB, scheduler,
  reporting): **~80%** — Beta-quality for those parts in isolation.
- End-to-end product (discover real jobs → apply → recover): **~40%**.
- **Overall toward the full V2 vision: ~45%.**

## 13. Recommendation

**Alpha Ready.**

Justification: the architecture and the non-browser core are stable, tested
(38/38), and maintainable, and dry-run is usable for inspecting decisions. But
the headline capability (applying to real jobs) is unimplemented and has never
run live, and the safety-critical Human Interaction framework plus the durability
layers (queue/state recovery) are not built. Calling this beta or production
ready would be dishonest. It is a solid alpha foundation: safe to run in
`dry_run`, not ready to submit real applications.

**Do not enable `apply.mode: live` until** the LinkedIn live-DOM checklist is
complete and verified in dry-run, the Human Interaction state machine exists, and
the first-run approval gate has been confirmed against the real flow.
EOF
echo "PRODUCTION_READINESS_REPORT.md written ($(wc -l < docs/PRODUCTION_READINESS_REPORT.md) lines)"
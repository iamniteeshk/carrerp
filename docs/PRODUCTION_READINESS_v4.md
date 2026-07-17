# CareerPilot v4.0.0 — Production Readiness

This document records the engineering audit findings, hardening changes shipped
in v4.0.0, remaining risks, and what still requires real-world validation.

## Verdict

CareerPilot is **hardened for unattended dry-run / match-quality operation** on
a dedicated Windows PC. It is **not** claimed production-ready for live
auto-submit of applications: LinkedIn and Naukri apply form-fill + final Submit
are intentionally incomplete against live DOM and will **never** report
`submitted=True` until those flows are completed and confirmed.

## Critical issues found (Phase 1) and fixes

| Issue | Severity | Fix |
|---|---|---|
| Live portal `apply()` returned `submitted=True` without submitting | Critical | Both portals now stop at confirmation boundary (`submitted=False`) |
| QUEUED / PARTIAL jobs never retried (`exists()` skipped all rows) | Critical | Retriable statuses resume on later scans |
| `_run_log` grew forever across scans | High | Reset per scan |
| Off-domain titles rescued by weak keywords (`Cloud Developer`) | High | `HARD_IC_TERMS` + `WEAK_DOMAIN_KEYWORDS`; strong-domain rescue only |
| No final confirmation before submit | High | `apply.require_final_confirmation` (default true) |
| No deterministic pre-apply safety gate | High | `ApplySafetyGate` (blacklist, domain, location, salary, seniority) |
| Unbounded cache/reports/screenshots/backups | High | `maintenance` retention + daily scheduler job + `maintenance` CLI |
| Doctor ignored provider-driven AI keys | Medium | Doctor + validation honour `ai.providers` |
| Session reports only when debug on | Medium | Always write `reports/sessions/session_*` |
| Application counts mixed dry-run/live | Medium | Count only `dry_run=0 AND APPLIED` |
| PID file written but not locked | Medium | Refuse start if live PID owns the file |
| GCC / Managed Services secondary in AI prompt | Medium | Elevated to strongly prefer |
| Blacklist exact-match only | Medium | Substring-aware company match |
| Job cache never expired | Medium | Stale reopen after `max_age_days` (default 14) |
| Keyboard Space could activate buttons | Low | Prefer PageDown/ArrowDown |
| Idle mouse used hardcoded viewport | Low | Prefer live `page.viewport_size` |

## Production profile

Use `config.production.example.yaml`:

- Chennai-first `search_locations`
- `require_final_confirmation: true`
- `require_preferred_location: true`
- Conservative daily apply cap / first-run confirmations
- Retention + daily maintenance hour
- Human browsing enabled
- `apply.mode: dry_run` until live apply is validated

Commands:

```bat
python -m careerpilot.main doctor
python -m careerpilot.main maintenance
python -m careerpilot.main run
```

Health heartbeat: `logs/health.json` (updated each scan / maintenance).

## Terminal job states

Every processed job should end in one of:

- **Applied** — live submit confirmed (not reachable until portal apply is completed)
- **Matched** — scored fit; dry-run ready or waiting for apply path
- **Rejected** — rule / AI / prefilter rejection
- **Failed** — extraction / browser failure (`PARTIAL_DATA` also counted as failed for reporting)

**Queued** remains for AI outages and human-approval / confirmation waits and is
**retriable**.

## Remaining risks (explicit)

1. **Live LinkedIn / Naukri selectors** — marked unverified; A/B markup can break
   card parsing, Easy Apply detection, and detail extraction.
2. **Live apply form-fill** — not implemented; confirmation-boundary stop is
   intentional. Do not set `require_final_confirmation: false` until forms +
   submit + confirmation toast are completed on live DOM.
3. **Telegram approval loop** — approval requests are sent, but automated
   resume-after-approval is still out-of-band.
4. **Browser shutdown thread affinity** — Playwright sync objects are created on
   the scheduler worker; main-thread shutdown may warn/fail to close cleanly.
5. **Timezone** — session windows use local PC time; ensure Windows timezone is
   set to IST for Chennai schedules.
6. **Locked Windows desktop** — headed Chrome may pause when the session is
   locked; keep an unlocked interactive session or a dedicated always-on user.
7. **Salary / unknown location** — missing salary still passes rules; location
   apply gate is enforced when `require_preferred_location: true`.

## Still requires real-world validation

- Logged-in Chrome profile persistence (LinkedIn + Naukri)
- Search URL filters and card selectors on live DOM
- JD extraction completeness on both portals
- Easy Apply / Naukri chatbot multi-step forms
- Final Submit + confirmation reference capture
- CAPTCHA / OTP / checkpoint recovery under real conditions
- Multi-day unattended run (memory, disk, recovery)

## Acceptance criteria status

| Criterion | Status |
|---|---|
| Run continuously on dedicated PC | Ready (scheduler + PID lock + maintenance) — validate on Windows |
| Browse like a human | Improved; validate visually on live portals |
| Search relevant executive IT roles | Strengthened RE + search keywords |
| Prioritize Chennai | Production profile + location apply gate |
| Open only relevant jobs | Hard IC + strong-domain prefilter |
| Extract complete JDs | Logic present; live selectors unverified |
| Score accurately | Prompt + min_match_score; needs live AI samples |
| Avoid duplicate applications | APPLIED-only duplicate check + no retry-after-submit |
| Recover from failures | Retriable statuses + browser health at scan start |
| Accurate reports | Session + portal + summary consistency fixes |
| No daily maintenance beyond reviewing reports | Retention + doctor + health heartbeat |

**Do not enable live auto-submit until the remaining live-DOM apply work is done
and validated on the dedicated PC.**

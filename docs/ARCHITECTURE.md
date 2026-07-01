# CareerPilot Architecture (V2)

## Design principles

1. **One deployment = one candidate.** No multi-tenancy, roles, or permissions.
2. **Profile-as-plug-in.** The Career Profile Engine is the only component that
   understands the *contents* of a specialization. Every other module interacts
   with a `CareerProfile` object, never with raw resumes, keywords, or files.
   Adding a specialization is creating a folder — provably no code change (see
   `tests/test_profiles.py::test_new_profile_is_a_dropin_plugin_no_code_change`).
3. **Configuration over code.** All user-specific data lives in `.env`,
   `candidate.yaml`, `config/config.yaml`, and `profiles/`. Source is generic.
4. **Deterministic before probabilistic.** A free rule engine rejects obvious
   misfits before any paid AI call.
5. **Never bypass security.** Security checkpoints pause for a human.

## Data flow

```
Collector(s)            discover raw jobs from each portal (error-isolated)
   |                    self-heals a dead browser before each scan
   v
Rule Engine             deterministic filter: salary, experience, titles,
   |                    blacklist, and the UNION of all profiles' keywords/locations
   v
AI Engine               returns match_score + career_profile name + confidence
   |                    (Gemini, DeepSeek fallback; never returns a filename)
   v
Career Profile Engine   maps name+confidence -> CareerProfile (default fallback
   |                    if confidence < threshold or name unknown)
   v
Document Manager        resolves resume / cover letter / docs for that profile
   |
   v
Apply Engine            confidence gate + first-run approval + mode (dry_run/live)
   |                    -> Portal.apply()  [live-DOM, currently stubbed]
   v
Database + Reporter + Telegram   record, summarize, notify
```

## Module map (implemented)

| Module | File | Responsibility |
|--------|------|----------------|
| Configuration Engine | `core/config.py` | Load/validate the single `config.yaml` (all sections); wire rules from profile unions. |
| Candidate Engine | `core/candidate.py` | Personal data from the `candidate:` section of `config.yaml` (legacy file still honored). |
| Career Profile Engine | `core/career_profile.py` | Discover/load/select profiles; keyword & location unions. |
| Document Manager | `core/document_manager.py` | Files for a profile; default-resume fallback. |
| Validation | `core/validation.py` | Human-readable, line-cited schema validation. |
| Rule Engine | `rules/rule_engine.py` | Deterministic job filtering. |
| AI Engine | `ai/engine.py`, `ai/gemini.py`, `ai/deepseek.py` | Fit scoring, profile choice, cover letters, answers. |
| Apply Engine | `apply/auto_apply.py`, `apply/confidence_gate.py` | Gated application with mode + approval. |
| Collector | `collectors/manager.py` | Per-portal discovery with isolation + self-heal. |
| Browser Manager | `browser/session.py` | ONE Playwright instance for the process; one persistent context per portal; config-driven (engine/channel/viewport, Edge default + Chromium fallback); health/restart; no orphan processes. |
| Portal contract | `browser/base_portal.py` | Abstract portal interface + interaction exceptions. |
| LinkedIn / Naukri | `browser/linkedin_portal.py`, `naukri_portal.py` | **Stubs** — selectors marked `# COMPLETE ON LIVE DOM`. |
| Scheduler | `core/scheduler.py` | Interval scans (overlap-protected) + daily summary/backup. |
| Database | `db/database.py`, `db/services.py` | Thread-local SQLite, WAL, migrations, backup. |
| Dashboard | `dashboard/app.py` | Read-only Flask status UI. |
| Telegram | `notify/telegram_service.py` | Notifications with retry; persisted for audit. |
| Reporting | `reports/csv_reporter.py` | CSV reports + daily summary. |
| Logging | `core/logging_setup.py` | Categorized rotating logs. |

## Not yet implemented (roadmap)

- **Human Interaction Point framework** — the uniform save→screenshot→log→notify→
  pause→resume mechanism. Today the portals raise `LoginRequired`/`OTPRequired`/
  `CaptchaRequired` and the apply engine queues the job and notifies, but there
  is no resume-from-exact-step state machine yet.
- **Queue Manager + State Recovery** — durable, restart-surviving work queue.
- **Portal Manager + ATS modules** (Workday, Greenhouse, etc.).
- **Live browser automation** for LinkedIn/Naukri (selectors + submit + parse).

## Concurrency model

A single background scheduler thread (a one-worker pool) runs every scan -- immediate and recurring -- so the single Playwright instance is created and reused on one thread (sync Playwright objects are thread-bound). The pipeline runs (`max_instances=1`,
`coalesce=True`, so a long scan never overlaps the next). The Flask dashboard
runs in its own thread and is read-mostly. SQLite uses one connection per thread
(thread-local) with WAL and a 30s busy timeout, so the two threads never share a
connection. There are no concurrent scan cycles, so cross-cycle duplicate
application is prevented by dedupe keys and `already_applied` checks rather than
locks.

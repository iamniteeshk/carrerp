# CareerPilot user files

Inventory of every user-facing and runtime file under the **data root**.  
Inferred from code (apply, profiles, doctor, backup) — not speculative.

Legend: **R** = required for production dry-run+, **O** = optional, **A** = auto-generated.

---

## Required (you supply)

| Path | Ext | Purpose | Example |
|---|---|---|---|
| `config/config.yaml` | `.yaml` | **R** — candidate, AI providers, rules, apply mode, browser, scheduler, dashboard | Copy from `config.example.yaml` |
| `.env` | — | **R** — API keys + secrets | `GEMINI_API_KEY_1=...` |
| `profiles/<Name>/profile.yaml` | `.yaml` | **R** — profile metadata + resume filename | `name: Default` |
| `profiles/<Name>/resume.pdf` | `.pdf` | **R** — uploaded on apply | `Resume_Main.pdf` via `resume:` key |

Default profile name comes from `profiles.default` in config (usually `Default`).

### `profile.yaml` keys that matter

```yaml
name: Default
resume: resume.pdf          # required on disk
cover_letter: cover.docx    # optional — preferred over AI letter
documents:                  # optional map; loaded but not auto-uploaded today
  resume: resume.pdf
```

---

## Optional (you supply)

| Path | Ext | Purpose | Used by apply? |
|---|---|---|---|
| `profiles/<Name>/keywords.yaml` | `.yaml` | Extra required keywords (unioned into rules) | Yes (filtering) |
| `profiles/<Name>/preferred_locations.yaml` | `.yaml` | Preferred locations | Yes (filtering) |
| `profiles/<Name>/screening_answers.yaml` | `.yaml` | Cached screening Q&A | Yes (forms) |
| `profiles/<Name>/<cover_letter file>` | `.docx`/`.pdf`/… | Static cover letter | Yes if declared |
| `profiles/<Name>/<doc>` | any | Declared in `documents:` | Loaded; **not attached by AutoApply yet** |
| `documents/photo.jpg` | `.jpg`/`.png` | Headshot | **No** (doctor optional check only) |
| `documents/portfolio.pdf` | `.pdf` | Portfolio | **No** |
| `certificates/**` | any | Certs / recommendation letters | **No** (backed up only) |
| `.env` → `TELEGRAM_*` | — | Notifications | Optional |
| `.env` → `DASHBOARD_PASSWORD` | — | Ops dashboard auth | Required for LAN |

Suggested optional layout (not required by code):

```
documents/
  photo.jpg
  portfolio.pdf
  linkedin_export.pdf
certificates/
  hackathon/
  recommendation_letters/
```

---

## Auto-generated (app writes)

| Path | Purpose |
|---|---|
| `database/careerpilot.db` | Applications, scans, notifications |
| `database/backups/careerpilot_*.db` | Daily SQLite copies |
| `database/good_jobs.json` | High-score learning set |
| `database/session_history.json` | Mission Control / session history |
| `cache/jobs/*.json` | JD cache |
| `logs/*.log` | Rotating domain logs |
| `logs/health.json` | Scheduler heartbeat |
| `logs/health_snapshot.json` | `health` CLI snapshot |
| `reports/**/*.csv` | Found / applied / failed CSVs |
| `reports/sessions/*` | Per-session summaries |
| `reports/run_log_*.md` | Pipeline traces |
| `reports/daily_summary_*.txt` | End-of-day text |
| `screenshots/*` | Portal / human-interaction captures |
| `debug/**` | Failure evidence, visual debug |
| `careerpilot.pid` | Single-instance lock |
| `{backups_root}/YYYY-MM-DD/` | Full backup trees |

---

## Secrets (never commit)

| File | Contents |
|---|---|
| `.env` | `GEMINI_API_KEY_*`, other provider keys, Telegram, dashboard password |
| `browser/**` | Session cookies (treat like secrets) |
| `config/config.yaml` | Personal PII (name, phone, salary) |

---

## Git ignore policy

Repository ignores personal/runtime paths (see root `.gitignore`).  
Shipped templates stay tracked: `config.example.yaml`, `.env.example`, `profiles.example/`.

---

## Doctor expectations

Doctor validates (among other things):

- config + candidate section present
- `.env` present; AI keys configured
- default profile has `resume.pdf`
- browser profile dirs exist / look used
- optional photo / certificates (SKIP if empty — not mandatory)
- writable logs, reports, database, backups
- Playwright + Chromium
- readiness score 0–100

Photo and certificates are **optional** because CareerPilot does not upload them today. Keep them under `documents/` / `certificates/` for your own records and future features.

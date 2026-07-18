# CareerPilot user files

Inventory of every user-facing and runtime file under the **data root**, plus
the **templates** shipped in Git under `app/data/`.

Legend: **T** = template in Git · **R** = required (you create) · **O** = optional · **A** = auto-generated

---

## Templates shipped with the repository (`app/data/`)

These use **placeholder** values only.

| Template | Copy / rename to (live data root) |
|---|---|
| `data/.env.example` | `.env` |
| `data/config/config.example.yaml` | `config/config.yaml` |
| `data/profiles/Murahari_M/<Spec>/` | `profiles/Murahari_M/<Spec>/` (production layout) |
| `data/profiles/Sample_Candidate/` | Optional flat sample pack |

### Production profile layout (frozen)

```
profiles/Murahari_M/
  General/profile.yaml + Murahari_M_Resume.pdf
  Leadership/...
  GCC/...
  GCC_Head_CXO/...
  Digital_Workplace/...
  Contact_Centre/...
```

Set `profiles.default` to a specialization **name** (e.g. `General`).
Optional: `enabled: false` in `profile.yaml` to exclude a specialization.

Also kept for backward compatibility: root `.env.example`, `config.example.yaml`,
`profiles.example/`.

### Migrate templates → production

```powershell
# Recommended live root
$live = "C:\CareerPilot\data"
$app  = "C:\CareerPilot\app"

New-Item -ItemType Directory -Force -Path $live\config, $live\profiles | Out-Null
Copy-Item $app\data\.env.example                    $live\.env
Copy-Item $app\data\config\config.example.yaml      $live\config\config.yaml
Copy-Item -Recurse $app\data\profiles\Sample_Candidate $live\profiles\Sample_Candidate

cd $live\profiles\Sample_Candidate
Rename-Item profile.example.yaml profile.yaml
Rename-Item keywords.example.yaml keywords.yaml
Rename-Item preferred_locations.example.yaml preferred_locations.yaml
Rename-Item screening_answers.example.yaml screening_answers.yaml
# Optional:
# Rename-Item cover_letter.example.md cover_letter.md

# Edit .env + config.yaml (replace John Doe), replace resume.pdf, then:
cd $app
py -m careerpilot.main doctor
```

`py -m careerpilot.main setup` / `doctor --fix` also materializes these
templates into the resolved data root when live files are missing.

---

## Required (you supply)

| Path | Ext | Purpose |
|---|---|---|
| `.env` | — | **R** — API keys + secrets (from `.env.example`) |
| `config/config.yaml` | `.yaml` | **R** — candidate, AI, rules, apply, browser, scheduler |
| `profiles/<Name>/profile.yaml` | `.yaml` | **R** — specialization metadata + resume filename |
| `profiles/<Name>/resume.pdf` | `.pdf` | **R** — uploaded on apply |

### `profile.yaml` keys CareerPilot loads

```yaml
name: Sample_Candidate          # required
description: "..."              # optional
resume: resume.pdf              # required on disk
cover_letter: cover_letter.md   # optional
resume_version: v1              # optional
salary_override: 2500000        # optional int or {amount: N}
documents:                      # optional map of type → filename
  resume: resume.pdf
```

Companion files (optional, same folder): `keywords.yaml`,
`preferred_locations.yaml`, `screening_answers.yaml`.

Personal identity (name, email, phone, LinkedIn, CTC, …) lives in
`config.yaml` → `candidate:`, **not** in the profile folder.

---

## Optional (you supply)

| Path | Purpose | Used by apply? |
|---|---|---|
| `profiles/<Name>/keywords.yaml` | Extra required/preferred keywords | Yes (filtering) |
| `profiles/<Name>/preferred_locations.yaml` | Preferred locations | Yes (filtering) |
| `profiles/<Name>/screening_answers.yaml` | Cached screening Q&A | Yes (forms) |
| `profiles/<Name>/cover_letter.*` | Static cover letter | Yes if declared |
| `documents/photo.jpg` | Headshot | No (doctor optional) |
| `certificates/**` | Certs / letters | No (backed up only) |
| Telegram / dashboard vars in `.env` | Notifications / Mission Control | Optional / LAN |

---

## Auto-generated (app writes)

| Path | Purpose |
|---|---|
| `database/careerpilot.db` | Applications, scans, notifications |
| `database/backups/*.db` | Daily SQLite copies |
| `database/good_jobs.json` | High-score learning set |
| `database/session_history.json` | Session / Mission Control history |
| `cache/jobs/*.json` | JD cache |
| `logs/*` | Rotating logs + health heartbeat |
| `reports/**` | CSV / session / run logs |
| `screenshots/*` | Portal captures |
| `debug/**` | Failure evidence |
| `browser/{linkedin,naukri}/` | Playwright login sessions |
| `careerpilot.pid` | Single-instance lock |
| `{backups_root}/YYYY-MM-DD/` | Full dated backups |

---

## Secrets (never commit)

| File | Contents |
|---|---|
| `.env` | API keys, Telegram, dashboard password |
| `browser/**` | Session cookies |
| `config/config.yaml` | Personal PII |
| Real `profiles/*/resume.pdf` | Your CV |

Git keeps `*.example*` and the Sample_Candidate placeholder PDF; live `.env`,
`config.yaml`, and real `profile.yaml` stay ignored (see root `.gitignore`).

---

## Doctor expectations

Doctor checks config, `.env`, AI keys, resumes, browser dirs, writable folders,
Playwright, and prints a **readiness score (0–100)**. Photo/certificates remain
optional (not uploaded by apply today).

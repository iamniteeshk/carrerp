# Install CareerPilot on Windows 11 (dedicated production PC)

This guide is written for a **fresh Windows 11** machine used only for
CareerPilot (for example a **GEEKOM A7 Max**). No prior tools are assumed.

After setup, the machine should:

1. Boot and auto-login (optional) or wait for you to sign in
2. Start CareerPilot via Task Scheduler
3. Browse LinkedIn / Naukri with a dedicated Chrome profile
4. Score jobs with Gemini, write reports, and keep running for weeks

Live auto-submit stays **off** until you explicitly enable it after validation.
Keep `apply.mode: dry_run` and `require_final_confirmation: true`.

**Python on Windows:** always prefer the **`py` launcher** (see
`docs/WINDOWS_PYTHON.md`). Do not rely on the WindowsApps `python` stub.

## Production filesystem (app vs data)

Recommended dedicated-PC layout:

```
C:\CareerPilot\          set CAREERPILOT_HOME here
  app\                   Git clone (this repository)
  data\                  all user/runtime files
  backups\               dated full backups
```

If you clone into `C:\CareerPilot\app`, `setup_windows.ps1` and Doctor resolve
the sibling `data\` automatically. Details: `docs/DATA_STRUCTURE.md`,
`docs/USER_FILES.md`, `docs/BACKUP_AND_RESTORE.md`, `docs/MIGRATION_GUIDE.md`.

---

## What CareerPilot actually needs

Inferred from this repository (not guessed):

| Dependency | Required? | Why |
|---|---|---|
| Windows 10/11 | Yes (this guide) | Dedicated production host |
| Git | Recommended | Clone + update |
| Python **3.10+** | Yes | Runtime (`docs/INSTALL.md`) |
| `py` launcher + `.venv` | Yes | Prefer `py`; never rely on WindowsApps `python` |
| Packages in `requirements.txt` | Yes | playwright, flask, APScheduler, PyYAML, requests, python-dotenv |
| Playwright **Chromium** browser | Yes | Fallback browser + Playwright driver |
| Google **Chrome** (or Edge) | Recommended | `browser.channel: chrome` (production) or `msedge` |
| Node.js / npm | **No** | Not used |
| Visual C++ Build Tools | **No** | Wheels cover all pinned deps |
| SQLite server | **No** | Embedded via Python stdlib |
| Gemini API key | Yes (for scoring) | `.env` → `GEMINI_API_KEY_1` |
| Telegram bot | Recommended | Notifications / approvals |
| Resume PDF(s) | Yes | Under `profiles/<Name>/resume.pdf` |

Disk: keep **≥ 2 GB free** (browser binaries, cache, reports, DB backups).

---

## Recommended folder layout

Keep the clone as the app root. All paths in config are **relative** and
configurable — do not hardcode `C:\Users\...`.

Example:

```text
C:\CareerPilot\                  ← git clone here (or any path you choose)
  careerpilot\                   ← Python package
  config\
    config.yaml                  ← your production config (gitignored)
  profiles\                      ← career profiles + resume.pdf
  profiles_browser\
    linkedin\                    ← dedicated Playwright Chrome profile
    naukri\
  database\
    careerpilot.db
    backups\
  logs\
  reports\
  screenshots\
  cache\jobs\
  documents\
  .venv\
  .env                           ← secrets (gitignored)
  setup_windows.ps1
  doctor.py
```

Chrome profiles used by CareerPilot are **not** your everyday Chrome profile.
Playwright creates per-portal user-data dirs under `profiles_browser\`.

---

## Phase A — Fresh Windows preparation

Do this once on the new PC:

1. Finish Windows Out-of-Box Experience; create a local or Microsoft account.
2. Install pending Windows updates; reboot.
3. Install **Google Chrome**: https://www.google.com/chrome/
4. Install **Git for Windows**: https://git-scm.com/download/win  
   (defaults are fine; enable “Git from the command line”).
5. Install **Python 3.12** (or 3.11 / 3.10): https://www.python.org/downloads/windows/  
   - Enable **Install launcher for all users** (`py.exe`)  
   - PATH for `python.exe` is optional (CareerPilot prefers `py`)  
   - Enable **Install launcher for all users** (py.exe)
6. Open **PowerShell** and confirm:

```powershell
py -3 --version          # expect 3.10+
git --version
```

### Windows power & reliability settings (24×7)

| Setting | Recommendation |
|---|---|
| Power plan | High performance (or Balanced with sleep disabled) |
| Sleep | **Never** (plugged in) |
| Hibernate | **Never** / disable `hibernate` |
| Display off | Optional (e.g. 10–30 min) — OK |
| USB selective suspend | Disabled in power options |
| Network adapters → Power Management | Uncheck “Allow computer to turn off this device” |
| Time zone | Set correctly (e.g. India Standard Time for Chennai windows) |
| Time sync | Enable “Set time automatically” |
| Windows Update restart | Prefer active hours; CareerPilot Task Scheduler uses Restart on failure |
| Automatic login | Optional (only on a physically secured dedicated PC) |
| Windows Defender exclusions | Optional — only if scans severely slow DB/browser I/O. If used, limit to `database\`, `profiles_browser\`, `cache\` under the install root. Prefer **not** excluding the whole drive. |

PowerShell snippets (run as Administrator where noted):

```powershell
# Never sleep / hibernate when plugged in (Admin)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /hibernate off
```

---

## Phase B — Clone and one-command setup

```powershell
# Choose an install root (example)
mkdir C:\CareerPilot -Force
cd C:\CareerPilot

# Clone (replace with your repo URL if different)
git clone https://github.com/iamniteeshk/carrerp.git .
# If the repo already exists as a subfolder, cd into it instead.

# Allow the setup script to run (once per user if needed)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# ONE COMMAND — creates venv, installs deps, Playwright, scaffolds, doctor --fix
.\setup_windows.ps1 -ProductionConfig
```

What `setup_windows.ps1` does (idempotent — safe to re-run):

1. Verifies Git / Python 3.10+
2. Creates `.venv`
3. Upgrades pip; installs `requirements.txt`
4. Runs Playwright Chromium install via the venv (`-m playwright`)
5. Checks for Google Chrome
6. Runs `py -m careerpilot.main doctor --fix --production`
7. Prints the remaining **manual** steps (keys, resumes, logins)

Equivalent entry points:

- `.\scripts\setup_windows.ps1`
- `.\scripts\setup_windows.bat`

---

## Phase C — Production configuration (manual secrets)

`doctor --fix` cannot invent secrets. Do this yourself:

### 1. `.env`

```env
GEMINI_API_KEY_1=your_real_key_here
# optional rotation:
# GEMINI_API_KEY_2=
# GEMINI_API_KEY_3=

TELEGRAM_BOT_TOKEN=123456:ABCDEF...
TELEGRAM_CHAT_ID=your_chat_id
```

### 2. `config\config.yaml`

Created from `config.production.example.yaml` when you used `-ProductionConfig`.

Edit at least:

- `candidate:` (name, email, phone, location)
- `rules.blacklist_companies`
- `rules.search_locations` (Chennai-first in the production template)
- `browser.channel: chrome` (or `""` for bundled Chromium only)
- Keep `apply.mode: dry_run` until live apply is validated
- Keep `apply.require_final_confirmation: true`

### 3. Resumes

Copy your real PDF:

```text
profiles\Default\resume.pdf
profiles\Infrastructure\resume.pdf
... (each profile folder you use)
```

### 4. Re-check

```powershell
.\.venv\Scripts\python.exe -m careerpilot.main doctor
# or:
py doctor.py
.\scripts\doctor.ps1
.\scripts\doctor.ps1 -Fix
```

---

## Phase D — First browser login (required once)

CareerPilot uses **dedicated** profiles under `profiles_browser\linkedin` and
`profiles_browser\naukri`.

```powershell
.\.venv\Scripts\python.exe -m careerpilot.main scan
```

A headed browser window opens. **Log into LinkedIn and Naukri once.**  
Close when done. Later runs reuse the saved session.

If login is lost after a Windows update, delete the affected folder under
`profiles_browser\` and log in again (or run `doctor --fix` to recreate empty dirs).

---

## Phase E — Start / stop / auto-start

### Foreground (good for first validation)

```powershell
.\scripts\run_careerpilot.ps1
# Ctrl+C to stop
```

### Scheduled Task (24×7)

**First few days (recommended — easier to debug):**

```powershell
.\scripts\Register-CareerPilotStartup.ps1
# same as:
.\scripts\Register-CareerPilotStartup.ps1 -Mode LogOn
```

Starts **At LogOn** for the current user. Restart on failure: every **1 minute**, up to **3** times.

**After the machine is stable (true unattended recovery after power outage):**

```powershell
# Run PowerShell as Administrator
.\scripts\Register-CareerPilotStartup.ps1 -Mode Startup
```

Starts **At Startup**, runs **whether the user is logged on or not** (SYSTEM). Same 1‑minute / 3‑retry restart policy.

```powershell
.\scripts\Register-CareerPilotStartup.ps1 -Remove
```

This registers a task that runs:

```text
.venv\Scripts\python.exe -m careerpilot.main run
```

Alternative for LogOn-only boxes: enable Windows **auto-login** for the CareerPilot user so AtLogOn still fires after a power restore.

### Dashboard LAN firewall (required for 0.0.0.0:8006)

Bind on all interfaces is fine on a dedicated LAN PC. Restrict who can connect:

```powershell
# Run PowerShell as Administrator
.\scripts\Allow-DashboardLan.ps1
```

Creates an inbound rule: **TCP 8006**, remote address **LocalSubnet** only (Private/Domain profiles). Never port-forward 8006 to the internet. Always set a strong `DASHBOARD_PASSWORD` in `.env`.

### Update / backup / health (production ops)

```powershell
.\scripts\update_careerpilot.ps1   # git pull + deps + doctor (preserves config)
.\scripts\backup.ps1               # -> backups\YYYY-MM-DD\
.\scripts\backup.ps1 -IncludeChrome
.\scripts\restore.ps1 -BackupDir backups\2026-07-18
.\scripts\health.ps1               # CPU/RAM/DB/AI/last scan JSON
```

Acceptance checklist: `docs/PRODUCTION_CHECKLIST.md`.
Ops Mission Control (LAN dashboard): `docs/OPS_DASHBOARD.md` — default
`http://0.0.0.0:8006` with `DASHBOARD_PASSWORD` in `.env`.

---

## Doctor reference

| Check | Meaning |
|---|---|
| Python / pip | Interpreter usable |
| Virtual environment | `.venv` present |
| Windows | Version probe |
| Disk space | ≥ ~2 GB free |
| Internet | Optional warning if offline |
| Schema / Configuration | YAML + candidate + profiles |
| Gemini / AI keys | Required for scoring |
| Telegram | Warning if missing |
| Folders / write perms | Runtime dirs |
| Database | SQLite schema |
| Resume files | `resume.pdf` present |
| System browser | Chrome/Edge for configured channel |
| Playwright package + Chromium | Driver + browser binary |
| Chrome profile dirs | `profiles_browser\...` |
| LinkedIn / Naukri login | Warning until session exists |
| Dashboard port | 8006 free / in use (ops Mission Control) |
| Maintenance | Retention settings loaded |

**`--fix` repairs:** missing folders, config templates, DB init, Playwright
Chromium install, empty profile dirs.  
**Never auto-fills:** API keys, Telegram secrets, website passwords.

---

## Updating CareerPilot

```powershell
cd C:\CareerPilot
.\scripts\update_careerpilot.ps1
# or manually:
git pull
py -m pip install -r requirements.txt          # or .\.venv\Scripts\python.exe -m pip …
py -m playwright install chromium
py -m careerpilot.main doctor --fix
```

Or re-run `.\setup_windows.ps1` (idempotent). See also `docs/WINDOWS_PYTHON.md`.

---

## Backup & restore

### Backup

Copy these while CareerPilot is stopped (or after a daily DB backup):

- `database\careerpilot.db` and `database\backups\`
- `config\config.yaml`
- `.env`
- `profiles\` (resumes)
- `profiles_browser\` (login sessions — treat as sensitive)

### Restore

1. Install Python/Git/Chrome as above  
2. Clone / copy the app tree  
3. Restore the files listed above  
4. `.\setup_windows.ps1`  
5. `py doctor.py`  
6. `py -m careerpilot.main run`

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `py` not found | Re-install Python with **py launcher**; open a **new** PowerShell |
| `playwright install` fails | Check internet; re-run `doctor --fix` |
| Chrome channel errors | Install Chrome, or set `browser.channel: ""` |
| Doctor FAIL: no AI key | Edit `.env` — `--fix` cannot invent keys |
| Doctor WARN: LinkedIn/Naukri login | Run a headed `scan` and log in once |
| Port 8006 in use | Stop the other CareerPilot (`careerpilot.pid`) or change `dashboard.port` |
| Sleep kills browser | Disable sleep/hibernate (Phase A) |
| After Windows Update, logins lost | Re-login; profiles usually survive but cookies can expire |
| Stack traces on startup | Run `doctor --fix` first — prefer its messages over raw traces |

---

## Production Ready checklist

Only treat the machine as **Production Ready** when **all** of these are true:

- [ ] `setup_windows.ps1` completed without install errors  
- [ ] `py doctor.py` → **RESULT: PASS** (warnings only for optional Telegram if you chose to skip it)  
- [ ] Gemini key works (`py -m careerpilot.main ai-health` or a dry scan that scores a job)  
- [ ] Telegram delivers a test notification (if enabled)  
- [ ] Headed browser launches; LinkedIn + Naukri sessions persist across restart  
- [ ] Database file exists; reports directory writable  
- [ ] `maintenance` runs cleanly  
- [ ] Scheduler starts via `run` or Task Scheduler  
- [ ] A dry-run scan completes and writes session reports under `reports\sessions\`  
- [ ] Sleep/hibernate disabled; time zone correct  

If any mandatory doctor check fails, **do not** call the box production-ready.

---

## Dependency lock

`requirements.lock` pins the exact tested package set (from `pip freeze`).
`update_careerpilot.ps1` prefers the lock file when present, then falls back to
`requirements.txt`.

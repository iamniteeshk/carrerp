# Install CareerPilot on Windows 11 (dedicated production PC)

This guide is written for a **fresh Windows 11** machine used only for
CareerPilot (for example a **GEEKOM A7 Max**). No prior tools are assumed.

The non-programmer path is `scripts\windows\Install_CareerPilot.bat`. It creates
`.venv`, installs dependencies, and copies `deployment_input\` into `config\`
and `profiles\`. You do not copy resumes or YAML by hand. Windows logon
startup is **not** registered by that installer. Add it later, separately,
if you want it.

After setup, the machine should:

1. Wait for you to sign in
2. Start CareerPilot from `CareerPilot.bat` or `Start_CareerPilot.bat`
3. Browse LinkedIn / Naukri with a dedicated browser profile
4. Score jobs with local Ollama (`qwen3:8b` and `qwen3-vl:8b`)

Leave `apply.mode: dry_run` until you have watched a real fill. `approval`
submits only after Telegram Proceed. `auto` is the only mode that submits
without asking. LinkedIn and Naukri form completion on the real sites is
**REQUIRES LIVE MANUAL TEST** (automated tests are not that test).

---

## What CareerPilot actually needs

Inferred from this repository (not guessed):

| Dependency | Required? | Why |
|---|---|---|
| Windows 10/11 | Yes (this guide) | Dedicated production host |
| Git | Recommended | Clone + update |
| Python **3.10+** | Yes | Runtime (`docs/INSTALL.md`) |
| `pip` + `.venv` | Yes | Isolated deps |
| Packages in `requirements.txt` | Yes | playwright, flask, APScheduler, PyYAML, requests, python-dotenv |
| Playwright **Chromium** browser | Yes | Fallback browser + Playwright driver |
| Google **Chrome** (or Edge) | Recommended | `browser.channel: chrome` (production) or `msedge` |
| Node.js / npm | **No** | Not used |
| Visual C++ Build Tools | **No** | Wheels cover all pinned deps |
| SQLite server | **No** | Embedded via Python stdlib |
| Ollama + the model in `config.yaml` | Yes (local scoring) | This deployment does not need a cloud AI key |
| Gemini / DeepSeek keys | Optional | Only if you switch `ai.active_provider` off Ollama |
| Telegram bot | Yes for approval and notices | `.env` → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Dashboard password | Yes | `.env` → `DASHBOARD_USER`, `DASHBOARD_PASSWORD` (change the example) |
| Resume PDF(s) | Yes | Six folders under `profiles\` (see below) |

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
   - Enable **Add python.exe to PATH**  
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
4. Runs `python -m playwright install chromium`
5. Checks for Google Chrome
6. Runs `python -m careerpilot.main doctor --fix --production`
7. Prints the remaining **manual** steps (keys, resumes, logins)

Equivalent entry points:

- `.\scripts\setup_windows.ps1`
- `.\scripts\setup_windows.bat`

---

## Phase C — Production configuration (manual secrets)

`doctor --fix` cannot invent secrets. Do this yourself:

### 1. `.env`

The clone already has a blank `.env`. Fill only:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DASHBOARD_USER=
DASHBOARD_PASSWORD=
```

Gemini keys stay empty when you use Ollama. Do not put those secrets in Git.

### 2. `config\config.yaml` and resumes

`Install_CareerPilot.bat` copies these from `deployment_input\` the first time.
It does not replace a `config\config.yaml` or a `profiles\<Name>\` folder that
already exists. It does not install an Infrastructure profile.

Leave `apply.mode: dry_run` until a real fill looks right. `approval` submits
only after a Telegram message that is exactly `Proceed`. `auto` is the only
mode that submits without that message.

### 4. Re-check

```powershell
.\.venv\Scripts\python.exe -m careerpilot.main doctor
# or:
python doctor.py
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

### Scheduled Task (optional, not part of install)

Do not run this during first setup. Use it later only if you want logon start:

```powershell
.\scripts\Register-CareerPilotStartup.ps1
# Remove later:
.\scripts\Register-CareerPilotStartup.ps1 -Remove
```

This registers a **current-user** logon task that runs:

```text
.venv\Scripts\python.exe -m careerpilot.main run
```

with restart-on-failure (3 attempts).

### Update / backup / health (production ops)

```powershell
.\scripts\update_careerpilot.ps1   # git pull + deps + doctor (preserves config)
.\scripts\backup.ps1               # -> backups\YYYY-MM-DD\
.\scripts\backup.ps1 -IncludeChrome
.\scripts\restore.ps1 -BackupDir backups\2026-07-18
.\scripts\health.ps1               # CPU/RAM/DB/AI/last scan JSON
```

Acceptance checklist: `docs/PRODUCTION_CHECKLIST.md`.

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
| Dashboard port | 5000 free / in use |
| Maintenance | Retention settings loaded |

**`--fix` repairs:** missing folders, config templates, DB init, Playwright
Chromium install, empty profile dirs.  
**Never auto-fills:** API keys, Telegram secrets, website passwords.

---

## Updating CareerPilot

```powershell
cd C:\CareerPilot
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m careerpilot.main doctor --fix
```

Or re-run `.\setup_windows.ps1` (idempotent).

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
5. `.\.venv\Scripts\python.exe -m careerpilot.main doctor`  
6. `.\scripts\run_careerpilot.ps1`

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` not found | Re-install Python with PATH + py launcher; open a **new** PowerShell |
| `playwright install` fails | Check internet; re-run `doctor --fix` |
| Chrome channel errors | Install Chrome, or set `browser.channel: ""` |
| Doctor FAIL: no AI provider | Ollama must be the active provider with `requires_auth: false`, or set a cloud key in `.env`. `--fix` cannot invent keys |
| Doctor WARN: LinkedIn/Naukri login | Run a headed `scan` and log in once |
| Port 5000 in use | Stop the other CareerPilot (`careerpilot.pid`) or change `dashboard.port` |
| Sleep kills browser | Disable sleep/hibernate (Phase A) |
| After Windows Update, logins lost | Re-login; profiles usually survive but cookies can expire |
| Stack traces on startup | Run `doctor --fix` first — prefer its messages over raw traces |

---

## Production Ready checklist

Only treat the machine as **Production Ready** when **all** of these are true:

- [ ] `setup_windows.ps1` completed without install errors  
- [ ] `.\.venv\Scripts\python.exe -m careerpilot.main doctor` → **RESULT: PASS**
- [ ] Ollama is running and the configured model answers (a cloud key is optional)
- [ ] Telegram delivers a test notification
- [ ] Dashboard login is not the example password; port 5000 is not exposed to the internet
- [ ] Headed browser launches; LinkedIn + Naukri sessions persist across restart
- [ ] Database file exists; reports directory writable
- [ ] Scheduler starts via `.\scripts\run_careerpilot.ps1` or `.\scripts\Register-CareerPilotStartup.ps1`
- [ ] A dry-run scan completes and writes session reports under `reports\sessions\`
- [ ] LinkedIn and Naukri apply on the real site are still **REQUIRES LIVE MANUAL TEST**
- [ ] Sleep/hibernate disabled; time zone correct

If any mandatory doctor check fails, **do not** call the box production-ready.

---

## Dependency lock

`requirements.lock` pins the exact tested package set (from `pip freeze`).
`update_careerpilot.ps1` prefers the lock file when present, then falls back to
`requirements.txt`.

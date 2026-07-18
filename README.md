# CareerPilot

A personal, single-candidate job-application automation framework. It discovers
leadership roles on LinkedIn and Naukri, filters them with a deterministic rule
engine, scores fit with an AI engine, selects the right **Career Profile**
(resume + cover letter + keywords + documents), and—when you enable it—applies on
your behalf, pausing for you whenever a security checkpoint needs a human.

> **Status: v4.0.0 production hardening.** The decision pipeline
> (discover → filter → score → select profile → record) is hardened for
> unattended dry-run operation. Live LinkedIn/Naukri form filling and
> submission still require live-DOM completion and will **never** claim
> `submitted=True` until that work is done. Keep `apply.mode: dry_run` and
> `require_final_confirmation: true`. See `docs/PRODUCTION_READINESS_v4.md`.

## What it is — and isn't

- **One deployment = one candidate.** No multi-user, tenant, role, or permission
  system. Anyone reuses it by cloning and editing config — never the source.
- **Profile-driven, not resume-driven.** Each career specialization is a
  self-contained folder under `profiles/`. Adding "Cybersecurity" or "Finance
  Leadership" is just creating a folder — no code changes.
- **It never bypasses security.** Login, OTP, email verification, CAPTCHA, and
  ambiguous questions are *Human Interaction Points*: the framework pauses and
  hands control to you. It does **not** create accounts, reset passwords, harvest
  OTPs, or solve CAPTCHAs. (The Human Interaction framework itself is a planned
  phase — see Roadmap.)

## Quick start (Windows dedicated PC)

```powershell
git clone <repo-url> C:\CareerPilot
cd C:\CareerPilot
.\setup_windows.ps1 -ProductionConfig
# edit .env + config\config.yaml + profiles\*\resume.pdf
python doctor.py
.\scripts\run_careerpilot.ps1
```

Full guide: [`docs/INSTALL_WINDOWS.md`](docs/INSTALL_WINDOWS.md).

## Quick start (any platform)

```bash
# 1. Install
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium   # bundled browser + cross-platform fallback

# 2. Configure (copy the examples, then edit — never edit source)
# One-time scaffold: creates config/config.yaml, profiles/, .env and runtime dirs
python3 -m careerpilot.main setup
# then edit config/config.yaml (candidate section + rules) and add keys to .env

# 3. Verify everything is wired correctly
python3 -m careerpilot.main doctor

# 4. Run (dry-run by default — nothing is submitted)
python3 -m careerpilot.main run
```

macOS/Linux helpers: `scripts/install_requirements.sh`, `scripts/doctor.sh`,
`scripts/run.sh`. Windows: the matching `.bat`/`.ps1` files.

## Commands

| Command | What it does |
|---------|--------------|
| `doctor` | Pre-flight: validates config, candidate, profiles, folders, keys, browser. |
| `check`  | Schema validation only (human-readable errors with line numbers). |
| `run`    | Runs the doctor, then starts the scheduler + dashboard. |
| `scan`   | Runs a single scan cycle and exits. |
| `dashboard` | Starts only the Flask dashboard. |

## Documentation

- `docs/QUICKSTART.md` — first run, creating Career Profiles
- `docs/INSTALL.md` — installation detail per platform
- `docs/DEPLOYMENT.md` — long-running unattended deployment
- `docs/ARCHITECTURE.md` — module map and design principles
- `docs/TEST_PLAN.md` — what is tested and how to run it
- `docs/TROUBLESHOOTING.md` — common problems
- `docs/LIVE_TEST_READINESS.md` — the remaining live-browser checklist
- `docs/PRODUCTION_READINESS_REPORT.md` — honest current-state assessment

## Important caveats

Automating job-site interactions may violate a site's Terms of Service and can
put your account at risk. That is your decision to make and is independent of how
the tool is configured. This software is provided for personal use; you are
responsible for how you operate it.

## License / privacy

Your real `.env`, `candidate.yaml`, `config/config.yaml`, and `profiles/` are
gitignored and must never be committed. The repository ships examples only.

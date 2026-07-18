# CareerPilot Production Acceptance Checklist

Use this on the dedicated Windows PC (e.g. GEEKOM A7 Max) **before** treating
the box as permanently deployed. Check each box only after you have personally
verified it.

Related guides: `docs/INSTALL_WINDOWS.md`, `docs/PRODUCTION_READINESS_v4.md`.

---

## Machine & OS

- [ ] Windows updated (latest cumulative updates installed; rebooted)
- [ ] Sleep / hibernate disabled when plugged in
- [ ] Correct time zone (e.g. India Standard Time)
- [ ] Automatic time sync enabled
- [ ] Sufficient free disk (≥ 10 GB recommended)
- [ ] Google Chrome installed (or `browser.channel: ""` for bundled Chromium)

## Install & configuration

- [ ] Repository cloned to the install root
- [ ] `.\setup_windows.ps1 -ProductionConfig` completed successfully
- [ ] `.env` has a real `GEMINI_API_KEY_1`
- [ ] Telegram configured (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) — or consciously skipped
- [ ] `config\config.yaml` candidate details filled (no placeholders)
- [ ] Resume PDF present in each used `profiles\<Name>\`
- [ ] `python doctor.py` → **RESULT: PASS** (no mandatory FAILs)
- [ ] `python doctor.py --fix` re-run after any Windows change

## Browser sessions

- [ ] Chrome / Playwright profile dirs exist under `profiles_browser\`
- [ ] Chrome profile logged into **LinkedIn** (session survives restart)
- [ ] Chrome profile logged into **Naukri** (session survives restart)
- [ ] Headed browser launches via `python -m careerpilot.main scan`

## Functional validation

- [ ] Doctor PASS
- [ ] Dry-run scan PASS (`apply.mode: dry_run`)
- [ ] Reports generated under `reports\` and `reports\sessions\`
- [ ] Scheduler starts (`python -m careerpilot.main run` or Task Scheduler)
- [ ] Startup banner shows version / git commit / AI provider
- [ ] `.\scripts\health.ps1` returns a JSON snapshot without errors
- [ ] `.\scripts\backup.ps1` creates `backups\YYYY-MM-DD\`
- [ ] Restore tested from a backup into a **scratch copy** of the install (or with `-Force` after a deliberate backup)
- [ ] Update tested: `.\scripts\update_careerpilot.ps1` preserves config/.env/DB
- [ ] Recovery observed: kill Chrome mid-scan → next cycle recovers (or browser restart logged)
- [ ] Final confirmation gate working (`require_final_confirmation: true` — applications do **not** auto-submit)

## Live apply (do **not** check until verified on this machine)

- [ ] Live validation PASS (Easy Apply / Naukri form fill against live DOM)
- [ ] Confirmation detection PASS (toast / reference captured)
- [ ] Multi-day unattended operation PASS (no manual babysitting for ≥ 3 days)

## 24×7 ops

- [ ] Ops dashboard reachable on LAN (`http://<geekom-ip>:8006`) with `DASHBOARD_PASSWORD`
- [ ] Mission Control shows live KPIs / activity after `run`
- [ ] Startup task registered (`.\scripts\Register-CareerPilotStartup.ps1`)
- [ ] PID lock prevents double start
- [ ] Graceful stop via `scripts\stop_careerpilot.bat` leaves DB intact
- [ ] Daily backup appears under `backups\` and/or `database\backups\`
- [ ] Logs rotating under `logs\`
- [ ] Windows Event Log entries visible (optional; requires Admin once to create source)

---

## Sign-off

| Item | Value |
|---|---|
| Date | |
| Machine | GEEKOM A7 Max / |
| Install path | |
| Git commit | |
| Doctor result | PASS / FAIL |
| Operator | |

**Do not claim the system is fully autonomous** until live application submission,
confirmation detection, and multi-day unattended operation have been successfully
verified on this production machine.

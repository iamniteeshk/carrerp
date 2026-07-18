# CareerPilot Production Acceptance Checklist

Use this on the dedicated Windows PC (e.g. GEEKOM A7 Max) **before** treating
the box as permanently deployed. Check each box only after you have personally
verified it.

Related guides: `docs/INSTALL_WINDOWS.md`, `docs/PRODUCTION_READINESS_v4.md`,
`docs/DATA_STRUCTURE.md`, `docs/MIGRATION_GUIDE.md`.

---

## Machine & OS

- [ ] Windows updated (latest cumulative updates installed; rebooted)
- [ ] Sleep / hibernate disabled when plugged in
- [ ] Correct time zone (e.g. India Standard Time)
- [ ] Automatic time sync enabled
- [ ] Sufficient free disk (≥ 10 GB recommended)
- [ ] Google Chrome installed (or `browser.channel: ""` for bundled Chromium)

## Install & configuration

- [ ] Cloned to `C:\CareerPilot\app` (or equivalent) with `CAREERPILOT_HOME` set
- [ ] User data lives under `data\` (not inside the Git tree)
- [ ] `.\setup_windows.ps1 -ProductionConfig` completed successfully
- [ ] `data\.env` has a real `GEMINI_API_KEY_1`
- [ ] Telegram configured (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) — or consciously skipped
- [ ] `data\config\config.yaml` candidate details filled (no placeholders)
- [ ] Resume PDF present in each used `data\profiles\<Name>\`
- [ ] `py -m careerpilot.main doctor` → **RESULT: PASS** + readiness score reviewed
- [ ] `py -m careerpilot.main doctor --fix` re-run after any Windows change

## Browser sessions

- [ ] Playwright profile dirs exist under `data\browser\` (or legacy `profiles_browser\`)
- [ ] Profile logged into **LinkedIn** (session survives restart)
- [ ] Profile logged into **Naukri** (session survives restart)
- [ ] Headed browser launches via `py -m careerpilot.main scan`

## Functional validation

- [ ] Doctor PASS
- [ ] Dry-run scan PASS (`apply.mode: dry_run`)
- [ ] Reports generated under `reports\` and `reports\sessions\`
- [ ] Scheduler starts (`py -m careerpilot.main run` or Task Scheduler)
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

- [ ] Ops dashboard reachable on LAN (`http://<geekom-ip>:8006`) with strong `DASHBOARD_PASSWORD`
- [ ] Mission Control shows live KPIs / activity after `run`
- [ ] Firewall: TCP 8006 LocalSubnet only (`.\scripts\Allow-DashboardLan.ps1`) — **not** port-forwarded
- [ ] Startup task registered (`.\scripts\Register-CareerPilotStartup.ps1` — LogOn first; `-Mode Startup` after stable)
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

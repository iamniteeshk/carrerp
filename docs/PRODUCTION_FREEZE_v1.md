# CareerPilot v1 Production Freeze

Frozen architecture for the dedicated Windows mini PC deployment.

## Deploy scope

| Mode | Status |
|---|---|
| 24×7 dry-run / scoring / reports / Mission Control | **Production-ready** |
| Unattended live auto-submit | **Deferred** — portals stop before final Submit |

Keep `apply.mode: dry_run` and `require_final_confirmation: true`.

## Production layout

```
C:\CareerPilot\
  app\                 Git repository
  data\                CAREERPILOT_DATA_ROOT
    .env
    config\config.yaml
    profiles\Murahari_M\
      General\profile.yaml + resume
      Leadership\...
      GCC\...
      GCC_Head_CXO\...
      Digital_Workplace\...
      Contact_Centre\...
    browser\{linkedin,naukri}\
    database\
    logs\
    reports\
    ...
  backups\
```

Set `CAREERPILOT_HOME=C:\CareerPilot`. Profile names are specialization names
(`General`, `Leadership`, …). Configure `profiles.default: General`.

## Mission Control (operator console)

| Page | Purpose |
|---|---|
| Config Summary | Effective runtime config (read-only, secrets redacted) |
| Config Health | Doctor-style checks + readiness score |
| Profiles | Metadata, resume/keyword/location status, usage stats |
| AI | Provider status, key status (never values), models |
| Settings | Grouped General / Advanced / Developer (read-only in v1) |

Writable settings editors are intentionally deferred.

## Intentionally deferred

- Dashboard config write/edit forms
- Live apply completion + closed-loop approval
- Temperature / max-tokens AI UI (not first-class in engine)
- Profile upload via UI

## Windows

Prefer `py` / `.venv\Scripts\python.exe`. See `docs/WINDOWS_PYTHON.md`.
Task Scheduler: `scripts/Register-CareerPilotStartup.ps1`.

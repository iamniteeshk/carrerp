# Migration guide

Goal: move CareerPilot to another Windows PC by copying **one data folder** (plus cloning the Git app).

## What to move

| Item | How |
|---|---|
| Application code | `git clone` into `C:\CareerPilot\app` |
| User data | Copy `C:\CareerPilot\data` (or use export/import scripts) |
| Dated backups (optional) | Copy `C:\CareerPilot\backups` |

You do **not** need to copy `.venv` — recreate with `setup_windows.ps1`.

## Recommended target layout

```
C:\CareerPilot\
  app\       # git clone
  data\      # imported user data
  backups\   # optional
```

Set environment (User variables):

```
CAREERPILOT_HOME=C:\CareerPilot
```

(Optional explicit overrides: `CAREERPILOT_DATA_ROOT`, `CAREERPILOT_BACKUPS_ROOT`.)

## Export (old PC)

```powershell
cd C:\CareerPilot\app
.\scripts\export_data.ps1 -OutDir D:\migrate -IncludeChrome -Compress
```

Produces:

- `D:\migrate\careerpilot_data\`
- `D:\migrate\careerpilot_data.zip` (if `-Compress`)

Omit `-IncludeChrome` if you prefer to log into LinkedIn/Naukri fresh on the new machine (smaller package).

## Import (new PC)

```powershell
# 1. Clone app
mkdir C:\CareerPilot
cd C:\CareerPilot
git clone <your-repo-url> app
cd app

# 2. Set home
[System.Environment]::SetEnvironmentVariable("CAREERPILOT_HOME", "C:\CareerPilot", "User")
$env:CAREERPILOT_HOME = "C:\CareerPilot"

# 3. Setup deps
.\setup_windows.ps1

# 4. Import data
.\scripts\import_data.ps1 -Source D:\migrate\careerpilot_data -Force -IncludeChrome

# 5. Validate
py -m careerpilot.main doctor
```

## Manual copy (no scripts)

1. Copy entire `data\` folder to `C:\CareerPilot\data`.
2. Set `CAREERPILOT_HOME`.
3. Run `setup_windows.ps1` then `doctor`.

## After migration

1. Confirm readiness score in Doctor.
2. Headed scan once; verify LinkedIn/Naukri sessions (or re-login).
3. Register startup: `.\scripts\Register-CareerPilotStartup.ps1`
4. Keep `apply.mode: dry_run` until you trust the new box.

## Updating the app without touching data

```powershell
cd C:\CareerPilot\app
.\scripts\update_careerpilot.ps1
# data\ is untouched
```

Git pull / update never overwrites `data\` when the data root is outside the repo.

## Rollback

Restore from a dated backup:

```powershell
py -m careerpilot.main restore C:\CareerPilot\backups\YYYY-MM-DD --force
```

See [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md).

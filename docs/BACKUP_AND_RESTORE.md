# Backup and restore

CareerPilot separates **daily SQLite snapshots** from **full data-root backups**.

## What gets backed up

### Full backup (`py -m careerpilot.main backup`)

Writes to `{CAREERPILOT_BACKUPS_ROOT}/YYYY-MM-DD/` (default: `C:\CareerPilot\backups\YYYY-MM-DD\`).

| Included by default | Optional flags |
|---|---|
| `config/config.yaml` | `--chrome` / `--include-chrome` → `browser/` |
| `.env` | `--zip` / `--compress` → sibling `.zip` |
| `database/` (+ online SQLite copy) | |
| `profiles/` | |
| `documents/` | |
| `certificates/` | |
| `logs/` | |
| `reports/` | |
| `good_jobs.json`, `session_history.json` | |
| `backup_manifest.json` | |

### Excluded from full backup (by design)

| Path | Why |
|---|---|
| `browser/` (unless `--chrome`) | Large; re-login often preferred |
| `cache/` | Regenerable |
| `temp/` | Scratch |
| `careerpilot.pid` | Process lock |
| `app\` / Git / `.venv` | Not user data — update via Git |

### Daily SQLite backups

Scheduler / maintenance copies the DB into `data/database/backups/` independently of the full backup command.

## Workflows

### Manual full backup

```powershell
cd C:\CareerPilot\app
py -m careerpilot.main backup
py -m careerpilot.main backup --chrome --zip   # include sessions + zip
```

Or: `.\scripts\backup.ps1`

### Verify

The `backup` command runs `verify_backup` automatically (manifest, config, `.env`, profiles).  
Python API: `careerpilot.core.backup_ops.verify_backup(path)`.

### Restore

```powershell
py -m careerpilot.main restore C:\CareerPilot\backups\2026-07-18 --force
py -m careerpilot.main restore ... --force --chrome   # also restore browser/
```

Never restore over a running instance — stop CareerPilot first (`scripts\stop_careerpilot.bat`).

### Automatic daily backups

1. Keep `py -m careerpilot.main run` as the 24×7 process (Task Scheduler).
2. Retention is configured under `maintenance:` in `config.yaml` (`backup_days`, `maintenance_hour`).
3. Optionally schedule a second Task Scheduler job:

```powershell
# Example: daily 03:30 full backup
schtasks /Create /TN CareerPilot-Backup /SC DAILY /ST 03:30 `
  /TR "py -m careerpilot.main backup" /WD C:\CareerPilot\app
```

### Incremental vs full

| Kind | Mechanism |
|---|---|
| Full | Dated folder under `backups\` (complete copy of critical trees) |
| Incremental-ish | Daily SQLite files under `database/backups/`; re-run full backup overwrites same calendar day folder |
| Compressed | `--zip` creates `YYYY-MM-DD.zip` beside the folder |

For true offsite incremental archives, copy `backups\` to NAS/OneDrive with your preferred tool; CareerPilot keeps the on-box tree simple and verifiable.

## Migration-sized copies

Use `scripts\export_data.ps1` / `import_data.ps1` when moving PCs — see [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md).

## Operator checklist

1. Stop the app (or accept that DB may be mid-write — online backup still runs).
2. `backup` (add `--chrome` before major OS changes).
3. Confirm `backup_manifest.json` and verify OK.
4. Copy `backups\` off-box weekly.
5. After restore: `doctor`, then headed `scan` to confirm portal logins.

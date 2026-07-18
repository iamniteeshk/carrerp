# CareerPilot data structure

Production layout separates **application code** (Git) from **user data** (everything personal or runtime-generated).

## Recommended Windows install tree

```
C:\CareerPilot\                         CAREERPILOT_HOME
│
├── app\                                Git repository (this repo)
│   ├── careerpilot\                    Python package
│   ├── scripts\
│   ├── docs\
│   ├── tests\
│   ├── config.example.yaml             templates only
│   ├── profiles.example\               templates only
│   ├── .env.example
│   └── .venv\                          local deps (not user data)
│
├── data\                               CAREERPILOT_DATA_ROOT
│   ├── .env                            secrets
│   ├── config\config.yaml              machine + candidate + rules
│   ├── profiles\<Name>\                resumes + profile YAML
│   ├── documents\                      optional supporting files
│   ├── certificates\                   optional (backed up; not auto-used)
│   ├── browser\{linkedin,naukri}\      Playwright Chromium user-data dirs
│   ├── database\
│   │   ├── careerpilot.db
│   │   ├── good_jobs.json
│   │   ├── session_history.json
│   │   └── backups\*.db                daily SQLite snapshots
│   ├── logs\
│   ├── reports\
│   ├── screenshots\
│   ├── cache\jobs\
│   ├── debug\
│   ├── health\                         reserved
│   ├── temp\                           scratch (excluded from export)
│   ├── exports\                        manual operator exports
│   ├── careerpilot.pid
│   └── README.md
│
└── backups\                            CAREERPILOT_BACKUPS_ROOT
    └── YYYY-MM-DD\                     full dated backups
```

## How the data root is resolved

Order (`careerpilot.core.paths`):

1. `CAREERPILOT_DATA_ROOT`
2. `CAREERPILOT_HOME\data`
3. Sibling `..\data` when the repo folder is named `app`
4. `.\data` if that directory already exists
5. Current working directory / app root (**legacy** single-folder mode)

Set once on the dedicated PC (User or System environment):

```
CAREERPILOT_HOME=C:\CareerPilot
```

Task Scheduler registration should inherit this so `run` always finds `data\`.

## What belongs in Git (`app\`)

| Include | Exclude |
|---|---|
| `careerpilot/` source | `.env`, real `config.yaml` |
| `scripts/`, `docs/`, `tests/` | `profiles/` with real resumes |
| `*.example.yaml`, `profiles.example/` | `database/`, `logs/`, `browser/` |
| `requirements.txt`, README | `backups/`, `cache/`, `reports/` |

## Folder purposes (under `data\`)

| Folder | Purpose | Writer |
|---|---|---|
| `config/` | Application + candidate + rules YAML | You (from example) |
| `profiles/` | Per-specialization resume + keywords | You |
| `documents/` | Optional extras (photo, portfolio) | You (scaffold only) |
| `certificates/` | Optional certs/letters | You (scaffold/backup only) |
| `browser/` | Persistent LinkedIn/Naukri logins | Playwright |
| `database/` | SQLite + learning JSON | App |
| `logs/` | Rotating logs + health heartbeat | App |
| `reports/` | CSV / session / run logs | App |
| `screenshots/` | Apply / human-interaction captures | App |
| `cache/jobs/` | JD extraction cache | App |
| `debug/` | Failure evidence / visual debug | App |
| `temp/` | Scratch | App / you |
| `exports/` | Operator-packaged exports | You / scripts |
| `backups\` (sibling) | Full dated backups | `backup` command |

## AI resources

Prompts live **in code** (`careerpilot/ai/engine.py`), not under `data/`. Do not invent a `prompts/` tree unless you intentionally externalize them later.

Learning signals that *are* data:

- `database/good_jobs.json`
- `database/session_history.json`
- SQLite application / scan history

## Browser data

Each portal uses Playwright `launch_persistent_context(user_data_dir=...)`:

```
data/browser/linkedin/     # cookies, Local Storage, IndexedDB, session
data/browser/naukri/
```

Safest location: **inside the data root** (above), never inside the Git `app\` tree. Multiple profiles = multiple portal folders (already supported).

Legacy name `profiles_browser` is still accepted if present in an old `config.yaml`.

## Configuration layers

| Layer | Where |
|---|---|
| Global app defaults | Shipped `config.example.yaml` in Git |
| Machine + candidate + rules + scheduling + scoring | `data/config/config.yaml` |
| Secrets (API keys, Telegram, dashboard password) | `data/.env` |
| Per-role resume selection | `data/profiles/<Name>/` |
| Browser engine/channel | `config.yaml` → `browser:` |
| Retention / maintenance | `config.yaml` → `maintenance:` |

See also: [USER_FILES.md](USER_FILES.md), [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md), [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md).

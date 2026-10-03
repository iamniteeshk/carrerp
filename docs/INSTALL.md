# Installation

CareerPilot runs anywhere Python 3.10+ and Playwright/Chromium run: Windows,
macOS, and Linux. The Python entrypoint is identical on all three.

## Prerequisites

- Python 3.10 or newer (`python3 --version`)
- pip
- ~500 MB free for the Chromium browser Playwright downloads

## Steps (all platforms)

```bash
# from the repo root
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

Pinned dependencies (see `requirements.txt`): playwright 1.49.0, flask 3.0.3,
APScheduler 3.10.4, PyYAML 6.0.2, requests 2.32.3, python-dotenv 1.0.1.

### Convenience scripts

- **Windows:** `scripts\install_requirements.bat` (or `.ps1`)
- **macOS / Linux:** `scripts/install_requirements.sh`

## Configure (no source edits — ever)

Scaffold a fresh clone with one command — it creates `config/config.yaml` (from
the example), `profiles/` (from `profiles.example/`), `.env`, and the runtime
folders. It never overwrites files you have already edited:

```bash
python3 -m careerpilot.main setup
```

Then edit `config/config.yaml`: it is a single file with all settings in clearly
labelled sections, including a `candidate:` section for your personal data (there
is no separate `candidate.yaml`; a legacy external file is still honored if
present). Put your real `resume.pdf` in each of the six profile folders
(`Default`, `Leadership`, `Digital_Workplace`, `EUC`, `GCC`, `Contact_Centre`).
`EUC` uses the same Digital Workplace PDF. Setup does not copy
`profiles.example/Infrastructure` and does not overwrite an existing `profiles/`
tree. In `.env`, set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DASHBOARD_USER`,
and `DASHBOARD_PASSWORD` (the example password is unsafe). Ollama does not need
a cloud API key. Your real `.env`, `config/config.yaml`, and `profiles/` are
gitignored and must never be committed.

Apply modes are `dry_run`, `approval`, and `auto`. Only `auto` submits without
an explicit Proceed. The dashboard on `0.0.0.0:5000` requires that login. Do
not expose it to the public internet.

### Browser on macOS vs Windows

The default browser is Microsoft Edge (`browser.channel: msedge`), which ships
with Windows. On macOS without Edge installed, CareerPilot automatically falls
back to the bundled Chromium (installed by `playwright install chromium`), so a
fresh Mac runs out of the box. To use Chrome set `channel: chrome`; for bundled
Chromium explicitly, set `channel: ""`.

## Verify

```bash
python3 -m careerpilot.main doctor
```

The doctor validates config, candidate, every Career Profile, folders, API keys,
and the browser install, with human-readable errors. Fix anything it flags before
running.

## AI keys

Local Ollama (`ai.active_provider: ollama`, `requires_auth: false`) does not
need a cloud key. A cloud provider still needs `GEMINI_API_KEY_*` and/or
`DEEPSEEK_API_KEY`. The doctor fails if no provider is configured at all.

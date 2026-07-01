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
present). Put your real `resume.pdf` in each `profiles/<Name>/` folder. Add your
API keys to `.env`. Your real `.env`, `config/config.yaml`, and `profiles/` are
gitignored and must never be committed.

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

Set at least one provider key in `.env`: one or more `GEMINI_API_KEY_*`, and/or
`DEEPSEEK_API_KEY` as a fallback. The doctor fails fast if none is present.

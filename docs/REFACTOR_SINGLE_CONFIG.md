# Refactor: Single Config + Config-Driven Browser + Cross-Platform

Refactoring and hardening only — no features removed, no behavior changed for
existing flows. All previously passing tests still pass; new tests were added.

## 1. All existing features preserved
The Profile Engine, Document Manager, AI Engine, Rule Engine, scheduler,
database, dashboard, telegram, reporting, and logging are unchanged in behavior.
47/47 tests pass (was 38; +9 for the new config/browser work).

## 2. Single configuration file
`config.yaml` is now one file with clearly separated sections: `application`,
`scheduler`, `candidate`, `ai`, `browser`, `dashboard`, `database`, `telegram`,
`profiles` (Career Profiles), `rules`, `apply`, `logging`, `documents`, and a
reserved `email` section. The separate `candidate.yaml` is merged into a
`candidate:` section. Secrets stay in `.env` only (API keys, Telegram token,
email password). **Backward compatibility:** a legacy deployment with a separate
`candidate.yaml` (via `candidate_file`) and the old top-level keys / `paths:`
block still loads — new keys win when both exist. Covered by
`tests/test_config_merge.py::test_legacy_layout_still_loads`.

> Note: the `email:` section is **reserved and not yet wired** — there is no Email
> Manager module. It is present so the config is documented; enabling it does
> nothing today.

## 3. Configuration-driven Browser Manager
`browser:` now selects `engine` (chromium/firefox/webkit), `channel`
(msedge/chrome/blank), `headless`, and `viewport`. **Microsoft Edge is the
default** (`engine: chromium`, `channel: msedge`). Switching browsers needs no
code change. The launch parameters are built by a pure `build_launch_plan()`
function and unit-tested for every engine/channel without launching a browser
(`channel` and the anti-automation arg correctly apply to chromium only).

## 4. Cross-platform paths
Audited: the codebase already uses `pathlib` throughout — no `os.path`, no manual
separators, no hardcoded slashes. The PID file and all runtime paths use `Path`.

## 5. Deployment scripts (full set, with validation)
- **Windows:** `install_requirements.bat`, `doctor.bat`, `run_careerpilot.bat`,
  `stop_careerpilot.bat`, `restart_careerpilot.bat`, `update_project.bat`.
- **macOS/Linux:** `install.sh`, `doctor.sh`, `run.sh`, `stop.sh`, `restart.sh`,
  `update.sh`.
Each checks prerequisites (python/git present, config present) and prints a
meaningful error. `run` writes `careerpilot.pid`; `stop` terminates gracefully
(force-kill fallback); `restart` chains stop+run.

## 6. Browser profiles persist
Each portal keeps its own persistent user-data dir under
`browser.profiles_path` (e.g. `profiles_browser/linkedin`,
`profiles_browser/naukri`), created with `pathlib` and surviving restarts.
Folders for portals that don't exist yet (workday/greenhouse) are created when
those portals are added — they need no special handling.

## 7. Cross-platform validation — what was actually verified
Verified here (Linux sandbox): single-file config load, legacy load, resume
loading (Document Manager), database creation, logging setup, dashboard build (9
routes), and the browser **launch-plan construction** for every engine.

**Not verifiable here, must be checked on-device:** actually launching Edge on
Windows and the system browser on macOS, and a real logged-in session. The
sandbox has no display and isn't Windows/macOS. The code is correct and
config-driven; on-device launch is a manual check on each OS.

## 8. Clone-and-run goal
A new user: clone → `cp .env.example .env` (add keys) → `cp config.example.yaml
config/config.yaml` (edit the `candidate:` section and rules) → add Career
Profile folders → `doctor` → `run`. No Python edits, ever.

## Files changed
- Rewrote `core/config.py` (sectioned single-file loader + fallback + BrowserConfig).
- Rewrote `browser/session.py` (config-driven, testable launch plan).
- `core/candidate.py` (load from dict or legacy file).
- `core/validation.py` (validate inline candidate + new sections + browser engine).
- `main.py` (BrowserConfig wiring, configured log level, PID file).
- New `config.example.yaml` (merged); removed `candidate.example.yaml`.
- Added Windows stop/restart and macOS/Linux install/stop/restart/update scripts.
- New `tests/test_config_merge.py` (9 tests). Docs updated for the single file.

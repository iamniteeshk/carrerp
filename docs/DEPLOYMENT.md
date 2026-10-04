# Deployment (long-running, unattended)

CareerPilot is designed to run continuously on one machine you control.

## Where to run it

Run it on a machine on a **residential network** (e.g. a small always-on PC or
mini-PC at home). A datacenter/VPS IP materially raises the chance LinkedIn
flags automated access. The OS does not matter; the network does.

## Choosing the browser (no code change)

The browser is selected in `config.yaml` under `browser:`. On Windows the default
is Microsoft Edge (`engine: chromium`, `channel: msedge`) since Edge ships with
Windows. To use Chrome set `channel: chrome`; for the Playwright-bundled Chromium
leave `channel: ""`; for Firefox set `engine: firefox` (channel is ignored).
`headless` and `viewport` are configurable too. Switching browsers never requires
editing Python.

## Start / stop / restart

- **Windows:** `scripts\run_careerpilot.ps1` (or `.bat`), `scripts\stop_careerpilot.bat`,
  `scripts\restart_careerpilot.bat`, `scripts\update_project.bat`,
  `scripts\doctor.bat`, `scripts\install_requirements.bat`.
  Logon start: `scripts\Register-CareerPilotStartup.ps1` (uses the project
  `.venv`, the repo folder, and writes `logs\startup.err.log`).
- **macOS / Linux:** `scripts/run.sh`, `scripts/stop.sh`, `scripts/restart.sh`,
  `scripts/update.sh`, `scripts/doctor.sh`, `scripts/install.sh`.

`run` writes a `careerpilot.pid` file; `stop` reads it to terminate gracefully
(falling back to force-kill), and `restart` chains the two. All scripts validate
prerequisites and print meaningful errors.

## Windows

- Register logon start once: `.\scripts\Register-CareerPilotStartup.ps1`.
  It launches `scripts\run_careerpilot.ps1` with the project `.venv` and the
  repository as the working directory. A second start is refused while
  `careerpilot.pid` belongs to a running process. Failures are appended to
  `logs\startup.err.log`.
- `scripts\doctor.bat` for pre-flight; `scripts\update_project.bat` to pull
  updates.
- Daily operation is the dashboard (Start, Pause, Resume, Stop, Scan now).
  Those buttons require the dashboard login.

## macOS / Linux

- Run `scripts/run.sh`, or wrap it in a `systemd` user service (Linux) or a
  `launchd` agent (macOS) with restart-on-failure.
- Example systemd unit (Linux):

  ```ini
  [Unit]
  Description=CareerPilot
  [Service]
  WorkingDirectory=/path/to/careerpilot
  ExecStart=/usr/bin/python3 -m careerpilot.main run
  Restart=on-failure
  [Install]
  WantedBy=default.target
  ```

## Operational behavior

- **Scheduler:** scans every `scan_interval_hours`. A scan that overruns the
  interval will **not** overlap the next (`max_instances=1`, `coalesce=True`).
- **Self-healing:** a dead browser context is restarted before each scan.
- **Daily summary + backup:** a Telegram summary and a SQLite backup run daily.
- **Crash isolation:** one bad scan or one failing portal never stops the rest;
  crashes are logged and notified.
- **Graceful shutdown:** SIGINT/SIGTERM close the browser sessions and database
  cleanly and send a shutdown notice.

## Backups & logs

- Database backups: `database/backups/` (configurable).
- Logs: categorized rotating files under `logs/`.
- Both directories are gitignored.

## Account-risk reminder

Automating a site may violate its Terms of Service and risk your account. That
risk exists regardless of scan volume and is your decision. Start in `dry_run`,
go slow, and keep `max_applications_per_day` conservative.

## Apply modes

| Mode | Submit |
|------|--------|
| `dry_run` | Never. |
| `approval` | Only after an explicit Proceed (Telegram or a saved Proceed decision). |
| `auto` | Without asking. This is the only mode that does that. |

If the mode is missing or not one of those three names, CareerPilot stays on
`dry_run`. An old config that says `live` is treated as `approval`.

## When something fails

CareerPilot records the job and does not mark it submitted unless the apply
flow reports a real Submit click in `auto`, or in `approval` after Proceed.

- Ollama offline, model missing, timeout, or a bad model reply: the job stays
  queued or needs review. It is not marked applied.
- Telegram unavailable during approval: the job stays `waiting`. It is not submitted.
- LinkedIn or Naukri logged out, 2FA, or CAPTCHA: the run pauses for you and
  sends a notice. It does not submit.
- Browser crash, page timeout, a changed selector, a form change, a required
  question with no answer, or a Submit button that cannot be identified: the
  attempt is recorded as not submitted.
- A short network drop: that cycle fails and is retried later. A failed cycle
  is not an application.
- Restart (including Windows logon) while an approval is open: the saved row
  stays `waiting` or `proceed`. The old page cannot be restored. After Proceed,
  the same job URL is opened again, filled again, and only then submitted.
  A restart by itself does not click Submit.

The dashboard on `0.0.0.0:5000` is for the home LAN. Log in is required for
every page. Do not forward that port to the internet.

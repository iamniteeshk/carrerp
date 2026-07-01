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

- **Windows:** `scripts\run_careerpilot.bat`, `scripts\stop_careerpilot.bat`,
  `scripts\restart_careerpilot.bat`, `scripts\update_project.bat`,
  `scripts\doctor.bat`, `scripts\install_requirements.bat`.
- **macOS / Linux:** `scripts/run.sh`, `scripts/stop.sh`, `scripts/restart.sh`,
  `scripts/update.sh`, `scripts/doctor.sh`, `scripts/install.sh`.

`run` writes a `careerpilot.pid` file; `stop` reads it to terminate gracefully
(falling back to force-kill), and `restart` chains the two. All scripts validate
prerequisites and print meaningful errors.

## Windows

- Use Task Scheduler to launch `scripts\run_careerpilot.bat` at logon, set to
  restart on failure.
- `scripts\doctor.bat` for pre-flight; `scripts\update_project.bat` to pull
  updates.

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

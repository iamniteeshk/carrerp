# CareerPilot Operations Dashboard

Professional Mission Control for the dedicated Windows production machine.
Reach it from any device on your LAN — no monitor required on the GEEKOM.

**Stack:** FastAPI · Jinja2 · HTMX · Alpine.js · Chart.js · WebSocket  
**Default bind:** `http://0.0.0.0:8006`  
**Package:** `careerpilot/ops_dashboard/`

> Does **not** redesign the CareerPilot engine. It reads the existing SQLite DB,
> logs, reports, scheduler, browser snapshots, and AI runtime state.

---

## Architecture

```
Browser (LAN laptop)
    │  HTTP / WS
    ▼
FastAPI ops_dashboard (daemon thread inside CareerPilot)
    ├── pages/     Jinja2 + HTMX fragments
    ├── api/       JSON for UI + future mobile apps
    ├── websocket/ Live phase / activity / preview ticks
    └── runtime HUB  ← bound once by CareerPilot.__init__
            │
            ├── Database (SQLite) — jobs, applications, scans, ai_history, …
            ├── LiveStatus (diagnostics) — current stage / URL / AI status
            ├── Scheduler.status() — next run, failures
            ├── BrowserManager.status_snapshot() — read-only, never launches
            ├── ActivityFeed — in-memory ring + activity_events table
            └── ControlCommand queue — drained on the scheduler worker thread
```

### Why not screenshot from the FastAPI thread?

Playwright Sync API is thread-bound to the scheduler worker. The dashboard
**never** calls Playwright. The worker writes `logs/browser_preview.png` during
pipeline stages; the UI polls `/api/browser/preview.png`.

### Startup

`py -m careerpilot.main run` and `… dashboard` both launch the ops board.
Set in `config.yaml`:

```yaml
dashboard:
  host: 0.0.0.0
  port: 8006
  refresh_seconds: 5
  password_env: DASHBOARD_PASSWORD
  session_hours: 12
```

And in `.env`:

```
DASHBOARD_PASSWORD=choose-a-strong-password
```

LAN binds without a password are refused (login always fails until set).

---

## Screens

| Route | Purpose |
|---|---|
| `/` | **Mission Control** — KPIs, live browser thumb, activity, alerts, controls |
| `/home` | Overview cards + feed |
| `/jobs` | Searchable job explorer |
| `/jobs/{id}` | JD, AI/rule notes, applications, failures, timeline |
| `/csv` | Polished CSV viewer (CSVs still generated for export) |
| `/reports` | Chart.js trends |
| `/ai` | Provider, tokens, latency, cache, failures |
| `/browser` | Live preview + portal health |
| `/scheduler` | Next run, APScheduler jobs, failure count |
| `/health` | CPU/RAM/disk/AI/Telegram/DB |
| `/notifications` | Alerts + Telegram history |
| `/settings` | Read-only config (unlock checkbox to view JSON) |
| `/login` | Session auth |

### Mission Control buttons

Pause · Resume · Restart Browser · Run Doctor · Backup Now · Scan Now  

Pause is immediate (flag). Other actions are queued and executed on the
scheduler worker thread (Playwright-safe).

---

## API (JSON)

All under `/api/` (same auth cookie as the UI). OpenAPI at `/api/docs`.

| Endpoint | Description |
|---|---|
| `GET /api/summary` | Phase, KPIs, live, scheduler, browser, health, alerts |
| `GET /api/activity` | Live activity feed |
| `GET /api/jobs` | Filtered job list |
| `GET /api/jobs/{id}` | Job detail bundle |
| `GET /api/applications` | Recent applications |
| `GET /api/ai` | AI summary + runtime counters |
| `GET /api/browser` | Browser snapshot + preview meta |
| `GET /api/browser/preview.png` | Latest worker screenshot |
| `GET /api/scheduler` | Scheduler status |
| `GET /api/health` | Full health snapshot |
| `GET /api/reports/charts` | Chart series |
| `GET /api/reports/csv` | CSV file index |
| `GET /api/reports/csv/preview` | CSV table preview |
| `GET /api/reports/csv/export` | Download CSV |
| `GET /api/notifications` | Alerts + DB notifications |
| `GET /api/settings` | Redacted config |
| `GET /api/logs/tail` | Tail a log file |
| `POST /api/control/{action}` | pause/resume/restart_browser/doctor/backup/scan_now |
| `WS /ws/live` | 2s ticks: phase, events, preview meta |

---

## Database

Migration **v4** adds:

```sql
activity_events(id, ts, level, category, message, detail, job_id, portal)
```

All other data comes from existing tables (`jobs`, `applications`,
`scan_history`, `ai_history`, `failed_jobs`, `notifications`).

AI calls are now persisted into `ai_history` from `AIEngine._log_ai`.

---

## Security

- Bind: `0.0.0.0:8006` (LAN-reachable) ✔️
- **Windows Firewall:** allow TCP 8006 from **LocalSubnet only**

  ```powershell
  # Admin PowerShell
  .\scripts\Allow-DashboardLan.ps1
  ```

- Strong `DASHBOARD_PASSWORD` in `.env` (required for non-loopback binds)
- Session cookie (`cp_ops_session`) with configurable TTL
- CSRF token on control POSTs (`csrf_token` form field or `X-CSRF-Token`)
- Settings page is read-only (no remote config writes)
- **Never port-forward 8006** on the router / never expose to the public internet

---

## Performance

- Daemon uvicorn thread, `access_log=False`
- Dashboard SQL is indexed reads only
- Browser preview is opportunistic (best-effort during stages)
- Control queue drained every 15s and around scans

---

## Manual steps on the GEEKOM

1. Set a **strong** `DASHBOARD_PASSWORD` in `.env`
2. Ensure `dashboard.host: 0.0.0.0` and `port: 8006`
3. Restrict the port to your LAN subnet:

   ```powershell
   # Admin PowerShell
   .\scripts\Allow-DashboardLan.ps1
   ```

4. Do **not** port-forward 8006 on the router
5. Open `http://<geekom-ip>:8006` from your laptop and sign in
6. Confirm Mission Control shows Idle/Searching after `run`

Do **not** treat live apply as verified until confirmation detection and
multi-day unattended operation pass on this machine.

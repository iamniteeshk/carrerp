# Troubleshooting

Run `python3 -m careerpilot.main doctor` first — most problems are reported there
in plain language with the file and line to fix.

## Config / startup

- **"candidate.X is missing" / "placeholder value (… line N)"** — edit
  `candidate.yaml`; you likely copied the example without filling a field.
- **"config.X is missing"** — a required key is absent from `config/config.yaml`;
  compare against `examples/config.example.yaml`.
- **"default_career_profile '…' not among loaded profiles"** — the name in
  `config.yaml` must match a folder name under `profiles/`.
- **"no career profiles found"** — each profile folder needs a `profile.yaml`.
- **"resume not found (profile '…')"** — put `resume.pdf` in that profile folder,
  or fix the `resume:` filename in its `profile.yaml`.
- **"no AI provider key set"** — with local Ollama this should not appear
  (`requires_auth: false`). For a cloud provider, set `GEMINI_API_KEY_*` or
  `DEEPSEEK_API_KEY` in `.env`.
- **Dashboard password FAIL** — `DASHBOARD_USER` and `DASHBOARD_PASSWORD` in
  `.env` are blank. Fill both before using the dashboard on the home LAN.
  Do not forward port 5000 to the internet.

## Browser

- **"Playwright package not installed"** — `python3 -m pip install -r
  requirements.txt`.
- **"Chromium browser … not installed"** — `python3 -m playwright install
  chromium`.
- **"no saved login yet"** (warning) — expected on first run; you log in once
  manually and the session is saved under `profiles_browser/`.

## Profile selection

- **AI keeps falling back to the default profile** — its confidence is below
  `profiles.confidence_threshold`, or it returned a name that doesn't match a
  folder. Lower the threshold, or refine each profile's `keywords.yaml` and
  `description`.

## Applications

- **Nothing is ever submitted** — that is correct in `dry_run`. `approval`
  submits only after an explicit Proceed. Only `auto` submits without asking.
  A missing or unknown mode stays `dry_run`. Real LinkedIn/Naukri completion
  is still **REQUIRES LIVE MANUAL TEST** (`LIVE_TEST_READINESS.md`).
- **Ollama is down or the model is missing** — scoring fails and the job is
  not marked applied. Start Ollama and confirm the model name in `config.yaml`.
- **Telegram is down during approval** — the job stays waiting. It is not submitted.
- **Logged out, 2FA, or CAPTCHA** — CareerPilot pauses and notifies you. Finish
  the challenge in the open browser. It does not store the portal password and
  it does not click Submit for you.
- **Restart during an approval** — the decision is saved. The browser page is
  not. After Proceed, the same job is opened and filled again, then submitted.
- **Jobs rejected as "Domain Mismatch"** — they don't match any profile's
  required keywords. Broaden a profile's `keywords.yaml`.

## Notifications

- **No Telegram messages** — set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  When unset, CareerPilot still runs and records notifications for audit.

## Database

- **"Stale DB connection … reconnecting"** (log) — handled automatically.
- To inspect data, open `database/careerpilot.db` with any SQLite browser.

# Troubleshooting

Run `python3 -m careerpilot.main doctor` first — most problems are reported there
in plain language with the file and line to fix.

## Config / startup

- **"candidate.X is missing" / "placeholder value (… line N)"** — edit
  `candidate.yaml`; you likely copied the example without filling a field.
- **"config.X is missing"** — a required key is absent from `config/config.yaml`;
  compare against `config.example.yaml`.
- **"default_career_profile '…' not among loaded profiles"** — the name in
  `config.yaml` must match a folder name under `profiles/`.
- **"no career profiles found"** — each profile folder needs a `profile.yaml`.
- **"resume not found (profile '…')"** — put `resume.pdf` in that profile folder,
  or fix the `resume:` filename in its `profile.yaml`.
- **"no AI provider key set"** — set a `GEMINI_API_KEY_*` or `DEEPSEEK_API_KEY`
  in `.env`.

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

- **Nothing is ever submitted** — that's correct in `dry_run` mode (the default),
  and submission also requires the live-DOM selectors to be completed (see
  `LIVE_TEST_READINESS.md`).
- **Jobs rejected as "Domain Mismatch"** — they don't match any profile's
  required keywords. Broaden a profile's `keywords.yaml`.

## Notifications

- **No Telegram messages** — set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  When unset, CareerPilot still runs and records notifications for audit.

## Database

- **"Stale DB connection … reconnecting"** (log) — handled automatically.
- To inspect data, open `database/careerpilot.db` with any SQLite browser.

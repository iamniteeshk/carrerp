# CareerPilot deployment checklist

This is the path for the Windows PC (GEEKOM). Setup copies
`deployment_input/config.yaml` to `config/config.yaml` and the six profile
folders to `profiles/`. You do not copy those files yourself.

The only values you type are the secrets in `.env`.

Windows logon startup is not registered by the installer. Do that later,
separately, if you want it.

## Prerequisites

- Windows 10 or 11
- Git
- Python 3.10 or newer (`py -3` or `python` on PATH)
- Google Chrome if `browser.channel` is `chrome` (Playwright Chromium is installed as the fallback)
- Ollama, installed by you from https://ollama.com/download
- Models `qwen3:8b` and `qwen3-vl:8b` (downloaded only when you confirm)
- A Telegram bot token and chat id
- A dashboard username and password, which you type into the blank `.env`

Ollama is not included in this repository. CareerPilot does not download the models during install.

## Cloning

```text
git clone -b cursor/production-ready-b4b1 https://github.com/iamniteeshk/carrerp.git C:\CareerPilot
cd C:\CareerPilot
```

Use the final deployment branch. Do not copy files out of `deployment_input` by hand.

## Setup

Double-click:

```text
scripts\windows\Install_CareerPilot.bat
```

That file checks it is inside the repository, creates `.venv`, installs
`requirements.txt`, installs Playwright Chromium, copies the six production
profiles and `config.yaml`, then runs Doctor.

The six profiles are Default, Leadership, Digital_Workplace, EUC, GCC, and
Contact_Centre. Infrastructure is not installed.

If `config\config.yaml` or `profiles\<Name>\` already exists, setup leaves it
in place. Delete that folder first only when you intend to replace it.

## .env

The clone already contains a blank `.env`. Edit that file. Do not create a second one.

You must replace:

| Name | What to put |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token from @BotFather |
| `TELEGRAM_CHAT_ID` | chat that receives approval messages |
| `DASHBOARD_USER` | a username you choose |
| `DASHBOARD_PASSWORD` | a password you choose |

Leave these empty when local Ollama is the AI provider:

- `GEMINI_API_KEY_1`
- `GEMINI_API_KEY_2`
- `GEMINI_API_KEY_3`
- `DEEPSEEK_API_KEY`
- `EMAIL_PASSWORD`

Optional session keys, only if you want the dashboard login to survive a restart:

- `FLASK_SECRET_KEY`
- `DASHBOARD_SECRET_KEY`

`.env` is gitignored. Do not commit it.

## Doctor

Double-click `scripts\windows\Doctor_CareerPilot.bat`.

It prints `PASS` or `FAIL` for config, the database, folder permissions,
Playwright, the browser, browser profile directories, all six profiles, real
resumes, the YAML files, candidate name/email/phone, Telegram, the dashboard
password, Ollama installed, Ollama running, `qwen3:8b`, and `qwen3-vl:8b`.

`run` and `scan` stop if a mandatory check fails. They do not start with a critical failure.

`doctor --fix` may create folders, initialize the database, install Playwright
Chromium, and start `ollama serve` when Ollama is already installed. It does
not pull models and it does not invent secrets.

## Ollama

Double-click `scripts\windows\Setup_Ollama.bat`.

- If Ollama is missing, it prints the install page and stops.
- If Ollama is installed but not answering, it starts `ollama serve`.
- If a model is missing, it prints `ollama pull qwen3:8b` and `ollama pull qwen3-vl:8b`.
- It downloads those models only after you type `Y`.

## Browser login

The first start creates `profiles_browser\linkedin` and `profiles_browser\naukri`.
CareerPilot opens the browser configured in `config.yaml` (`channel: chrome`
in the shipped file, headed, not headless).

Log in to LinkedIn and Naukri in that window. The sessions stay in those
folders for later runs.

CareerPilot does not store the website password, does not bypass CAPTCHA, and
does not complete 2FA. If a login, code, or CAPTCHA appears, it waits.

## Dry Run validation

Shipped `apply.mode` is `dry_run`. In this mode CareerPilot may fill a form
and record the answers. It does not click Submit.

Confirm on the machine with one job you are willing to open, and check that
no application was sent.

## Approval validation

Set `apply.mode` to `approval` only after dry run looks right.

A submission happens only when the Telegram message is exactly `Proceed`
(capitalization does not matter). These do not authorize a submit:

```text
yes
ok
go
submit
approve
Proceed now
```

`Reject` does not submit.

The dashboard Apply button only keeps the Telegram approval request. It does
not authorize the submit.

## Auto validation

`auto` is the only mode that submits without a Telegram `Proceed`. Leave it
off until you have decided you want unattended submit. A blank or unknown
mode stays `dry_run`. The old name `live` means `approval`, not `auto`.

## Dashboard

`Open_Dashboard.bat` reads `dashboard.port` from `config\config.yaml`
(5000 in the shipped file) and opens `http://127.0.0.1:<port>/` on this PC.

The shipped config listens on `0.0.0.0` port 5000, so other devices on your
home LAN can open `http://<this-pc-ip>:5000/`. Every page, including status,
asks for `DASHBOARD_USER` and `DASHBOARD_PASSWORD`. This is for the home
network only. Do not forward port 5000 to the public internet.

## Troubleshooting

| What you see | What to do |
|---|---|
| Doctor says FAIL for Telegram | Fill both Telegram lines in `.env` |
| Doctor says FAIL for the dashboard password | Fill `DASHBOARD_USER` and `DASHBOARD_PASSWORD` in `.env` |
| Doctor says Ollama is not running | Run `ollama serve`, or `Setup_Ollama.bat` |
| Doctor says a model is missing | Run the `ollama pull` command it prints |
| Doctor says a resume is a placeholder | The file in `deployment_input\profiles\<Name>\resume.pdf` is not a real PDF. Replace that file in the repository source, then delete `profiles\<Name>\` and run setup again |
| "already running" | Use Stop, or read the PID in `careerpilot.pid` |
| Browser did not open | Doctor, system browser check. `channel: chrome` needs Chrome installed |

## Backup and recovery

Copy these folders while CareerPilot is stopped:

- `database\` (includes `database\backups\`)
- `profiles\` (resumes and answers)
- `config\config.yaml`
- `.env`
- `profiles_browser\` (LinkedIn and Naukri sessions)

`scripts\backup.ps1` can copy the database tree. Restoring is copying those
folders back into a clone and running Doctor. Do not commit `.env`,
`config\config.yaml`, or `profiles\`.

## Safe shutdown

Double-click `scripts\windows\Stop_CareerPilot.bat`, or choose Stop in
`CareerPilot.bat`.

That stops only the process id stored in `careerpilot.pid`. It asks Windows
to close that process, waits, and only then force-stops that same PID.
It does not kill every Python process and it does not stop Ollama.

Closing the Start window with Ctrl+C also shuts CareerPilot down.

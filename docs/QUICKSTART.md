# Quick Start

## 1. Install and configure

See `INSTALL.md`, then run the one-time scaffold:

```bash
python3 -m careerpilot.main setup
```

This creates `config/config.yaml`, `profiles/`, `.env`, and runtime folders from
the shipped examples (it never overwrites your edits). Then edit
`config/config.yaml` (the `candidate:` section and rules) and add keys to `.env`.

## 2. Create your Career Profiles

A Career Profile is one self-contained career specialization. `setup` creates
`profiles/` from the shipped templates. It copies these six folders and does
not overwrite a `profiles/` tree you already have:

```
Default  Leadership  Digital_Workplace  EUC  GCC  Contact_Centre
```

`EUC` is meant to use the same Digital Workplace resume as `Digital_Workplace`.
Put that same PDF in both `profiles/EUC/resume.pdf` and
`profiles/Digital_Workplace/resume.pdf`. `profiles.example/Infrastructure/` is
only an extra example; setup does not copy it.

Each profile folder contains:

```
profiles/Default/
  profile.yaml             # name, description, resume filename, optional salary override, documents
  resume.pdf               # your resume for this specialization
  cover_letter.docx        # optional
  keywords.yaml            # required + preferred keywords (drives domain matching)
  preferred_locations.yaml # acceptable locations (Remote always accepted)
  screening_answers.yaml   # cached answers to common questions
  documents/               # optional supporting documents
```

Set `profiles.default` in `config/config.yaml` to the folder used when the AI
is unsure (`Default` in the shipped example).

**Adding a new specialization later is just adding a folder — no code changes.**

## 3. Verify

```bash
python3 -m careerpilot.main doctor
```

## 4. Apply modes

`apply.mode` is one of:

| Mode | What it does |
|------|----------------|
| `dry_run` | Fills the form, records every answer, stops before Submit. Never submits. |
| `approval` | Same fill, then waits for an explicit Telegram **Proceed**. Reject stops. |
| `auto` | The only mode that clicks Submit without a Proceed, then notifies you. |

A blank or unknown mode is treated as `dry_run`. The older name `live` is
treated as `approval`. Neither one becomes `auto`.

On Windows, start with `.\scripts\run_careerpilot.ps1`. On other systems:

```bash
python3 -m careerpilot.main run       # scheduler + dashboard
```

The dashboard listens on `dashboard.host` / `dashboard.port` (example
`0.0.0.0:5000`, so other devices on the home network can open it). Log in with
`DASHBOARD_USER` and `DASHBOARD_PASSWORD` from `.env`. Change the example
password before you do that. Do not forward port 5000 to the public internet.

## 5. Before `approval` or `auto`

LinkedIn and Naukri apply flows are **REQUIRES LIVE MANUAL TEST**. Automated
tests are not a test of the real websites. Stay on `dry_run` until you have
watched a real fill on your machine. See `LIVE_TEST_READINESS.md`.

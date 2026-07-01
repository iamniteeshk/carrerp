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

A Career Profile is one self-contained career specialization. `setup` already
created `profiles/` from the shipped templates with six folders:

```
Infrastructure  Digital_Workplace  Contact_Centre  GCC  Leadership  Default
```

Add a new specialization by copying any folder:

```bash
cp -r profiles/Default profiles/Cybersecurity
```

Each profile folder contains:

```
profiles/Infrastructure/
  profile.yaml             # name, description, resume filename, optional salary override, documents
  resume.pdf               # your resume for this specialization
  cover_letter.docx        # optional
  keywords.yaml            # required + preferred keywords (drives domain matching)
  preferred_locations.yaml # acceptable locations (Remote always accepted)
  screening_answers.yaml   # cached answers to common questions
  documents/               # optional supporting documents
```

Repeat for each specialization (e.g. `GCC`, `Leadership`, `Cybersecurity`).
Set `default_career_profile:` in `config/config.yaml` to the one to use when the
AI is unsure.

**Adding a new specialization later is just adding a folder — no code changes.**

## 3. Verify

```bash
python3 -m careerpilot.main doctor
```

## 4. Dry run (nothing is submitted)

`apply.mode` defaults to `dry_run`. In this mode CareerPilot discovers, filters,
scores, selects a profile, and records everything — but never submits.

```bash
python3 -m careerpilot.main scan      # one cycle
python3 -m careerpilot.main run       # scheduler + dashboard
```

Open the dashboard at the host/port in `config.yaml` (default
`http://127.0.0.1:5000`).

## 5. Before going live

Live submission needs the browser selectors completed against your logged-in
session — see `LIVE_TEST_READINESS.md`. Keep `apply.mode: dry_run` until every
item there is done and verified.

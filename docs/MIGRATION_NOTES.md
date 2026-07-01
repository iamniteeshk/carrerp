# Migration Notes — Stabilization Release

If you have an earlier deployment, read this. New clones can ignore it and follow
`docs/QUICKSTART.md`.

## 1. Naukri / Playwright crash fixed (root cause)

The error *"Playwright Sync API inside the asyncio loop"* happened because the
browser layer started a **separate Playwright instance per portal**. The second
`sync_playwright().start()` on the same thread trips Playwright's loop check.

Fix: a single `BrowserManager` owns **one** Playwright instance for the whole
process and hands out **one persistent context per portal**. In addition, every
scan (immediate and recurring) now runs on **one scheduler worker thread**,
because sync Playwright objects are thread-bound. No workaround, no async/sync
mixing — the browser layer is consistently sync everywhere.

## 2. Single configuration file (no candidate.yaml)

There is now exactly one config file: `config/config.yaml`, with a `candidate:`
section inside it. **Action:** move your details from `candidate.yaml` into the
`candidate:` section of `config.yaml`, then delete `candidate.yaml`. Legacy
formats (`candidate_file`, a `paths:` block, top-level `scan_interval_hours` /
`default_career_profile`) are **no longer supported** — the loader accepts one
modern schema only.

## 3. Example_Profile removed; six real profiles

`Example_Profile` is gone entirely. The shipped templates and the default
deployment use six career profiles:

```
Infrastructure  Digital_Workplace  Contact_Centre  GCC  Leadership  Default
```

`Default` is the fallback used when the AI's confidence is below
`profiles.confidence_threshold` (set `profiles.default: Default`).

**Place your resumes** (one per folder, named `resume.pdf`):

| Folder | Put this resume in it (as `resume.pdf`) |
|--------|------------------------------------------|
| `profiles/Infrastructure/resume.pdf` | your IT-infrastructure resume |
| `profiles/Digital_Workplace/resume.pdf` | your digital-workplace / EUC resume |
| `profiles/Contact_Centre/resume.pdf` | your contact-centre / BPM resume |
| `profiles/GCC/resume.pdf` | your GCC / global-delivery resume |
| `profiles/Leadership/resume.pdf` | your senior-leadership resume |
| `profiles/Default/resume.pdf` | your general resume (fallback) |

If you prefer to keep your original filenames, set `resume:` in each folder's
`profile.yaml` to that filename instead of renaming to `resume.pdf`. Either way
is fully configuration-driven; no Python changes.

Adding a new specialization later = copy a folder (e.g.
`cp -r profiles/Default profiles/Cybersecurity`), drop in its resume, edit its
`keywords.yaml`. Nothing else.

## 4. Browser is configuration-driven

`config.yaml -> browser:` selects `engine` (chromium/firefox/webkit), `channel`
(msedge/chrome/blank), `headless`, and `viewport`. Microsoft Edge is the default
on Windows. On macOS without Edge, it falls back to bundled Chromium
automatically. Switching browsers never needs code changes.

## 5. First run

```bash
python3 -m careerpilot.main setup    # scaffolds config/, profiles/, .env, dirs
# edit config/config.yaml (candidate + rules), drop resumes into profiles/, add keys to .env
python3 -m careerpilot.main doctor   # must say PASS
python3 -m careerpilot.main run      # dry_run by default
```

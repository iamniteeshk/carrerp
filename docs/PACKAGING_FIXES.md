# Packaging Fixes — Clone-and-Run

Reported after a clean macOS install. All six issues are fixed and verified from
a completely fresh extract.

## What was wrong (root causes)

The app worked in development only because `config/config.yaml` and `profiles/`
existed locally — both are gitignored, so a fresh clone had neither. There was
no bootstrap step, the example profile had no resume file, and the test suite
loaded the developer's private `config/config.yaml` (so tests failed on any
clean machine).

## Fixes

1. **`profiles.default` guaranteed.** The shipped `config.example.yaml` has
   `profiles.default: the example profiles`, and `setup` copies it verbatim, so the
   key always exists in a fresh `config/config.yaml`.
2. **`profiles/` is created automatically.** New `careerpilot/core/bootstrap.py`
   copies `profiles.example/` → `profiles/` when missing.
3. **First-run scaffolding.** A new `setup` command (and auto-bootstrap on every
   `doctor`/`run`/`scan`) creates `config/config.yaml`, `profiles/`, `.env`, and
   the runtime folders from the shipped examples. It never overwrites existing
   files.
4. **Default profile is initialized with a real resume.** `profiles.example/
   the example profiles/` now ships a placeholder `resume.pdf`, so the default profile
   is structurally valid immediately after `setup`.
5. **Doctor reaches every check, including database init.** A missing API key is
   no longer a fatal *load* error — `load_config` builds a structurally valid
   config and the missing key is reported by validation/doctor. So the doctor now
   runs configuration, schema, database, profiles, and browser checks even on a
   not-yet-finished setup, instead of aborting early.
6. **Placeholder candidate values are reported clearly, not silently fatal.** The
   doctor reaches all checks and points to the exact lines to fill
   (`candidate.email still has a placeholder value (config.yaml line 18)`).

## Also fixed (cross-platform)

- **macOS browser launch.** The Edge default (good for Windows) would fail on a
  Mac without Edge. The browser now falls back to bundled Chromium automatically
  with a clear warning, so a fresh Mac runs out of the box. Install scripts run
  `playwright install chromium` to guarantee the fallback exists.

## Tests now pass on a clean machine

The suite no longer depends on any user-owned file. A new
`tests/_fixture.py` builds a complete temporary deployment (config + profiles +
candidate) for each test. New `tests/test_bootstrap.py` covers scaffolding.
**50 tests pass on a freshly extracted clone with no setup performed.**

## Verified new-user flow (from a clean extract)

```bash
# 1. unzip / clone
# 2. python3 -m pip install -r requirements.txt && python3 -m playwright install chromium
# 3. python3 -m careerpilot.main setup        # creates config/, profiles/, .env, dirs
# 4. edit config/config.yaml (candidate: name/email/phone) + add keys to .env
# 5. python3 tests/*.py                        # 50 passed
# 6. python3 -m careerpilot.main doctor        # PASS
# 7. python3 -m careerpilot.main run           # starts (dry_run)
```

Steps 1–7 were executed against a fresh extract during verification.

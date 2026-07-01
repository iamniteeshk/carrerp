# AGENTS.md

## Cursor Cloud specific instructions

CareerPilot is a single-process Python app (module `careerpilot`, entrypoint
`python -m careerpilot.main`). It discovers → filters → scores → records job
applications; the Flask dashboard runs in-process. There is no separate backend
service and no external DB server (SQLite is embedded, file-based, auto-migrated
on startup).

### Environment
- Dependencies live in a virtualenv at `.venv` (created by the startup update
  script). **Always run via `.venv/bin/python`** (e.g. `.venv/bin/python -m
  careerpilot.main doctor`) — the system Python does not have the deps.
- Playwright Chromium and its system libraries are pre-installed in the VM
  snapshot. The update script only refreshes the Python deps + browser binary.

### Running / testing (see README.md and `scripts/` for the full list)
- Tests are plain scripts (no pytest): each `tests/test_*.py` prints
  `N passed, M failed` and exits non-zero on failure. Run them directly, e.g.
  `.venv/bin/python tests/test_core.py`. Run the whole suite by looping over
  `tests/test_*.py`.
- Preflight: `.venv/bin/python -m careerpilot.main doctor` (config/DB/profiles/
  keys/browser). Schema-only: `... check`.
- App: `... run` (scheduler + dashboard) or `... dashboard` (UI only) on
  `http://127.0.0.1:5000`. A single scan cycle: `... scan`.

### Non-obvious gotchas
- On a fresh clone `bootstrap.py` scaffolds `config/config.yaml`, `.env`,
  `profiles/` and runtime dirs from the shipped examples on startup. These are
  gitignored — never commit real config/secrets.
- The `doctor` env check reads `ai.gemini_key_env_vars` (top-level), while the
  runtime AI provider reads `ai.providers.gemini.api_key_envs`. If doctor reports
  "no AI provider key" despite a key in `.env`, add
  `gemini_key_env_vars: [GEMINI_API_KEY_1, ...]` to the `ai:` section.
- A **real end-to-end scan needs a logged-in Chrome profile (Naukri/LinkedIn)
  and a Gemini API key**; neither is available by default, so live scans cannot
  be validated in a fresh cloud VM. Deterministic logic (Rule Engine, pipeline
  decision layer, DB/CSV) is fully testable offline with faked AI — see
  `tests/test_read_gate.py` / `tests/test_prefilter.py` for the pipeline harness
  pattern (build `ScanPipeline` via `__new__` with fakes).
- `Portal` enum values are capitalized (`"LinkedIn"`, `"Naukri"`); the Rule
  Engine's `_portal_rule` rejects any other value.

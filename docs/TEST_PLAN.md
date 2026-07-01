# CareerPilot Test Plan (V2)

All tests run with no network, no credentials, and no real browser. AI and
portals are faked. Run each file directly; each prints `N passed, M failed` and
exits non-zero on failure.

```bash
python3 tests/test_core.py
python3 tests/test_hardening.py
python3 tests/test_profiles.py
python3 tests/test_reliability.py
```

## Current coverage (38 tests)

### `test_core.py` (13) — deterministic core + AI parsing
- Rule Engine: accepts good leadership jobs; rejects bad titles, blacklisted
  companies, night shifts, low experience, domain mismatch, location mismatch;
  allows missing salary; rejects below-threshold salary; "engineering director"
  not rejected by the "engineer" keyword.
- Salary and experience parsing.
- AI Engine: JSON extraction with fences/garbage; provider fallback on failure;
  returns `match_score` + `career_profile` + `confidence`; unknown profile name
  is preserved (not invented away).

### `test_hardening.py` (12) — config, DB, doctor, scheduler, documents
- Config loads six Career Profiles; default profile is valid; every profile has
  an existing resume; rule keywords equal the profile union; bad default profile
  is rejected; no-AI-keys fails.
- Database: idempotent init, reconnect after close, backup creates a file.
- Career Profile Engine selection + default fallback.
- Document Manager falls back to the default profile's resume when missing.
- Doctor runs and reports (Configuration, Database, Career Profiles, Schema).
- Scheduler safe-scan swallows a pipeline crash.

### `test_profiles.py` (8) — Career Profile Engine, candidate, validation
- Engine loads profiles; unions keywords/locations (de-duplicated).
- Selection: confident+known, low-confidence→default, unknown→default.
- Cached screening answers (case-insensitive).
- Empty profiles directory raises.
- Candidate loader: known fields + free-form extras preserved; summary/form values.
- Validation: missing field + placeholder value reported with line numbers; a
  good config passes.
- **Plug-in proof:** a brand-new "Cybersecurity" profile folder, dropped in at
  runtime, is discovered, passes the rule engine via the auto-expanded keyword
  union, is selectable, and its resume resolves — with zero code change.

### `test_reliability.py` (5) — unattended-operation hardening
- Collector self-heals each portal (`ensure_healthy`) before scanning.
- Collector isolates one portal's failure from the others.
- Scheduler configures overlap protection (`max_instances=1`, `coalesce=True`).
- Scheduler safe-scan swallows crashes and notifies.
- Telegram disabled path still records the notification and never crashes.

## Known test gaps (require live browser or unbuilt modules)

- **Live portal apply flows** (LinkedIn/Naukri form fill + submit + confirm):
  cannot be tested without live DOM; integration-tested only with fake portals.
- **Human Interaction Points / Queue Manager / State Recovery**: not built, so
  not tested. State-recovery tests should be added when those modules exist.
- **Dashboard rendering**: routes exist but are not exercised by automated tests
  (only smoke-importable). End-to-end dashboard tests are a future addition.
- **End-to-end against real Gemini/DeepSeek/Telegram**: faked in tests by design.

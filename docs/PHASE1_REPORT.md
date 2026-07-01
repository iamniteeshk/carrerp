# CareerPilot V2 — Phase 1 Report

**Scope:** De-personalization, configuration framework, Career Profile Engine,
and schema validation. This is the foundation every later phase builds on.

**Status:** Complete and tested. 32/32 tests pass. `doctor` reports PASS.

---

## What changed and why

### 1. One deployment = one candidate (no multi-tenant machinery)
The architecture stays deliberately simple. There are no users, roles, tenants,
or permissions. Anyone reuses the framework by cloning the repo and editing
config — never the source. Each deployment owns exactly one of everything:
candidate, config, browser-profile set, database, Career Profile library,
document library, email account, and Telegram config.

### 2. Career Profile Engine (the new foundation)
The "multiple resumes" model is gone. The framework now thinks in **Career
Profiles** — self-contained career specializations, each its own folder:

```
profiles/
  Infrastructure/
    profile.yaml            # name, description, resume filename, optional salary override, documents
    resume.pdf
    cover_letter.docx       # optional
    keywords.yaml           # required + preferred keywords for this specialization
    preferred_locations.yaml
    screening_answers.yaml  # cached Q&A for this specialization
    documents/              # supporting docs
```

Key behaviors, all implemented:

- **The AI never returns a filename.** It returns a *career profile name* and a
  *confidence*. `CareerProfileEngine.select(name, confidence)` maps the name to a
  profile, and falls back to the configured **default profile** when confidence
  is below `profiles.confidence_threshold` *or* the name is unknown. The engine
  never invents a profile.
- **Two separate AI numbers, two separate gates.** `match_score` is job-fit and
  gates whether to apply (`apply.min_apply_score`). `confidence` is the AI's
  certainty in its profile choice and gates the default-profile fallback.
- **Add a specialization = add a folder.** No Python changes, no central config
  edits. The Rule Engine's keyword and location filters are computed as the
  **union across all profiles**, so a new folder automatically extends filtering.
  A job survives the rule pass if it matches *any* specialization; the AI then
  assigns the best-fit profile.
- **Everything is profile-owned:** resume, cover letter (file preferred, AI
  fallback), keywords, preferred locations, cached screening answers, optional
  salary override, and declared documents.

### 3. Personal data fully separated from source
- `candidate.yaml` is now a first-class config file holding *all* personal data.
  Nothing personal is hardcoded anywhere in the source.
- Secrets live only in `.env`. Career data lives only in `profiles/`. Structure
  and thresholds live in `config.yaml`.
- The repository is GitHub-safe: it ships **examples only** —
  `.env.example`, `config.example.yaml`, `the candidate section`, and
  `profiles.example/the example profiles/`. Real files are gitignored.
- `.gitignore` excludes: `.env`, `candidate.yaml`, `config/config.yaml`,
  `profiles/`, `documents/`, `resumes/`, and all runtime dirs (database, logs,
  screenshots, reports, browser profiles).

### 4. Schema validation with human-readable, line-cited errors
`careerpilot/core/validation.py` validates, on startup (via `doctor`):
config.yaml, candidate.yaml, every Career Profile, required folders, required
documents (resumes mandatory; cover letters/docs warn), and environment
variables. It collects **all** problems at once and fails fast on mandatory
ones. Messages read like:

```
candidate.phone is missing (candidate.yaml)
candidate.email still has a placeholder value (candidate.yaml line 2)
profiles/Infrastructure/resume.pdf not found (profile 'Infrastructure')
no AI provider key set in environment (set a Gemini key or DeepSeek key in .env)
```

### 5. A latent crash fixed along the way
The browser session raised "Session not started" because nothing ever called
`start()`. The `page` property now starts the session lazily on first access.
This was present since V1 and masked by error isolation; it would have bitten
the first real run.

---

## New / changed modules

New: `core/career_profile.py` (engine), `core/candidate.py` (candidate loader),
`core/validation.py` (schema validation), `core/yaml_utils.py` (line-aware YAML
for error messages), `tests/test_profiles.py`.

Rewritten: `core/config.py` (V2 model — candidate from file, profiles engine,
union-derived rules; no `resumes:` dict, no inline personal data).

Updated: `core/models.py` (`AIEvaluation` → `match_score` + `career_profile` +
`confidence`; removed legacy `Resume`), `core/enums.py` (removed hardcoded
`ResumeCategory`), `ai/engine.py` (returns profile + confidence),
`apply/auto_apply.py` (resolves everything from the selected profile, cached
answers first then AI), `core/pipeline.py`, `core/doctor.py` (schema +
profile checks), `main.py` (wiring), `browser/*_portal.py` (Candidate type).

---

## Test results

```
test_core.py       13 passed   (rule engine, salary/experience parsing, AI parse+fallback)
test_hardening.py  12 passed   (config load, profile selection/default, DB, doctor, scheduler)
test_profiles.py    7 passed   (engine load/union/select/cache, candidate loader, validation)
TOTAL              32 passed, 0 failed
```

Dry-run integration (fake portal + fake AI, real pipeline) against 3 jobs:
- Accenture "GCC Centre Head" → **MATCHED**, score 94, profile `GCC_Head_CXO`
- A blacklisted company → **REJECTED** (Blacklisted Company)
- SalesCo (off-domain) → **REJECTED** (Domain Mismatch)

`doctor` → **PASS** (one expected warning: no saved browser login yet).

---

## What is intentionally NOT in this phase

No browser selectors were invented. The live LinkedIn/Naukri DOM integration
points remain marked `# COMPLETE ON LIVE DOM` and are unchanged. The refused
capabilities (account creation, password reset, OTP-bypass, CAPTCHA-solving)
were never added and never will be.

The V1 `docs/HARDENING_REPORT.md` was removed because it referenced your real
resume filenames; the V1 install/deploy docs still describe the old resume model
and will be rewritten in Phase 7 alongside the migration guide.

---

## Profiles are plug-ins (boundary hardened)

The framework is now profile-driven, not resume-driven, and the boundary is
enforced rather than merely intended:

- **`CareerProfile` is the only object that crosses the boundary.** Every module
  outside the Profile Engine interacts with a `CareerProfile` (via accessors like
  `resume_file()`, `cover_letter_file()`, `document(type)`, `cached_answer(q)`) —
  never with raw filenames, paths, or keyword lists. A grep confirms no module
  outside the engine and Document Manager touches profile internals.
- **A new `DocumentManager`** is the single place that turns a profile into files
  to attach (resume, cover letter, supporting docs) and owns the default-profile
  fallback. The Apply Engine no longer contains any file-resolution logic; it
  asks the Document Manager. The Document Manager speaks only `CareerProfile` and
  knows no profile names.
- **No hardcoded profile or domain names anywhere in source.** The AI Engine
  receives the profile list from `engine.names()`; the Rule Engine's keyword and
  location filters are the union the engine computes from whatever folders exist;
  the previous `"Director Infrastructure"` search fallback was removed.
- **Proven, not asserted.** `test_new_profile_is_a_dropin_plugin_no_code_change`
  drops in a brand-new "Cybersecurity" profile folder at runtime and verifies the
  engine discovers it, the Rule Engine accepts a CISO/Zero-Trust job through the
  auto-expanded keyword union, profile selection returns it, and the Document
  Manager resolves its resume — all with zero Python changes.

So adding "Cybersecurity", "Data Engineering", or "Finance Leadership" later is
exactly: create the folder, add the files, edit `default_career_profile` only if
you want it as the fallback. Nothing else.

## Next: Phase 2 — Human Interaction Points

The uniform mechanism for every security checkpoint (login, OTP, email
verification, CAPTCHA, account registration, password reset, security
checkpoints, ambiguous screening questions): **save state → screenshot → log →
notify via Telegram → pause safely → resume from the exact step**. Never bypass
a security mechanism. Everything in later phases routes its checkpoints through
this one well-tested path.

---

## How to adopt this on your repo

Your public repo is canonical. Suggested steps:

1. Tag your current main as `v1.0` first (so V1 stays recoverable).
2. Create a `v2` branch; unzip this tree over it and commit. Do **not** merge
   v2 into main yet — keep it on the branch until all phases land.
3. Your real `config/config.yaml`, `candidate.yaml`, and `profiles/` are
   gitignored and will not be committed — that is intended. Keep them locally.
4. Run `python -m careerpilot.main doctor` after copying your real files in.

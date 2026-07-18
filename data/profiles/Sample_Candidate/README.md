# Sample_Candidate profile pack

Fictional template only — **John Doe / ExampleCorp**. No real credentials.

## Files in this folder

| File | Required? | What to do |
|---|---|---|
| `profile.example.yaml` | Yes (as `profile.yaml`) | Rename → `profile.yaml` and edit |
| `resume.pdf` | **Yes** | Replace with your real PDF (same name, or change `resume:` in profile) |
| `cover_letter.example.md` | Optional | Rename → `cover_letter.md` and set `cover_letter:` in profile |
| `keywords.example.yaml` | Optional | Rename → `keywords.yaml` |
| `preferred_locations.example.yaml` | Optional | Rename → `preferred_locations.yaml` |
| `screening_answers.example.yaml` | Optional | Rename → `screening_answers.yaml` |
| `README.md` | — | This file |

## Where personal identity goes

Name, email, phone, LinkedIn URL, CTC, notice period, etc. belong in:

```
data/config/config.yaml   →  candidate:
```

This profile folder is a **specialization** (resume + keywords + locations), not a second identity card.

## Production copy steps

From the data root (example: `C:\CareerPilot\data`):

```powershell
# 1. Secrets
Copy-Item .env.example .env
# edit .env — add GEMINI_API_KEY_1, DASHBOARD_PASSWORD, …

# 2. App config (includes candidate: John Doe → replace with you)
Copy-Item config\config.example.yaml config\config.yaml
# edit candidate, rules, apply.mode

# 3. Profile
Copy-Item -Recurse profiles\Sample_Candidate profiles\MyRole
cd profiles\MyRole
Rename-Item profile.example.yaml profile.yaml
Rename-Item keywords.example.yaml keywords.yaml
Rename-Item preferred_locations.example.yaml preferred_locations.yaml
Rename-Item screening_answers.example.yaml screening_answers.yaml
# optional:
# Rename-Item cover_letter.example.md cover_letter.md
# then set cover_letter: cover_letter.md inside profile.yaml

# Replace resume.pdf with your file
# Set profiles.default: MyRole in config.yaml
```

Then run:

```powershell
cd C:\CareerPilot\app
py -m careerpilot.main doctor
```

## Git safety

- Committed: `*.example.yaml`, `*.example.md`, this README, placeholder `resume.pdf`
- Never commit: real `profile.yaml`, real resumes with PII, real `.env`

# CareerPilot data templates (shipped with Git)

This `data/` tree inside the **repository** shows the expected layout of a
production data root. It contains **examples only** (fake John Doe values).

## Important: templates vs live data

| Location | Purpose |
|---|---|
| `app\data\` (this folder) | Templates committed to Git |
| `C:\CareerPilot\data\` (`CAREERPILOT_DATA_ROOT`) | Your real secrets, resumes, DB, browser sessions |

On a dedicated PC, clone the repo into `C:\CareerPilot\app` and set
`CAREERPILOT_HOME=C:\CareerPilot`. Live files go in the **sibling** `data\`
folder, not here.

Quick start (copy templates into the live data root):

```powershell
$live = "C:\CareerPilot\data"
New-Item -ItemType Directory -Force -Path $live\config, $live\profiles | Out-Null
Copy-Item .\data\.env.example $live\.env
Copy-Item .\data\config\config.example.yaml $live\config\config.yaml
Copy-Item -Recurse .\data\profiles\Sample_Candidate $live\profiles\Sample_Candidate
# Then rename *.example.* → production names inside the profile folder
# (see profiles\Sample_Candidate\README.md)
```

Or run `py -m careerpilot.main setup` / `doctor --fix` after `CAREERPILOT_HOME`
is set — bootstrap copies from these templates when present.

See `docs/USER_FILES.md` and `docs/DATA_STRUCTURE.md`.

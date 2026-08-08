# Full Audit — Jarvis / Local AI Deploy Branch

Date: 2026-08-08  
Branch: `cursor/jarvis-deploy-local-ai-60c2`  
Models: **Qwen 3** text (`qwen3:8b`) + vision (`qwen3-vl:8b`) via Ollama  

This is an honest working-parts audit before PC dry-run. Verdict first, then
subsystem detail.

---

## Overall verdict

| Area | Status | Notes |
|------|--------|--------|
| Config / bootstrap / doctor | **Ready** | Paths, YAML, Windows ops solid |
| Schedule (random + 3–4h day cap) | **Ready** | Needs live day to prove budget tracking |
| Jarvis dashboard + Admin auth | **Ready** | Stats public; edits gated |
| Local AI (Ollama) + API optional | **Ready** | Config default = Qwen 3; live Ollama required |
| Vision login hold + emergency | **Ready (code)** | Needs live `qwen3-vl:8b` + real screenshots |
| Rules / AI scoring / CSV / DB | **Ready** | Offline tests green |
| Search plan (feeds → categories) | **Ready** | URLs built; parse depends on live DOM |
| Job card / JD extraction (DOM) | **At risk** | Selectors UNVERIFIED; must confirm on your account |
| Easy Apply / Naukri apply fill | **NOT ready** | Stubs: navigate + screenshot; no real form clicks |
| Dry vs live Apply click | **Contract OK** | Dry stops before submit; live also incomplete DOM |
| Humanize / visual debug | **Ready** | Use `debug.visual_mode` on first PC run |
| External ATS (Workday etc.) | **Out of scope** | Manual review only |

**Ship for PC as a dry-run discovery appliance.** Do **not** expect unattended form-fill/apply until live DOM work is done with Visual Debug evidence.

---

## Test suite snapshot

Ran all `tests/test_*.py` on this branch:

- **29/29 suites green** (offline unit + Flask console harness)
- Fixed: REJECTED recheck false-positive when DB row had no stored fields (status-only) — caused `test_streaming` skip-path crash
- Qwen3 think-tag stripping covered in `test_core` / `test_jarvis_console`
- Offline unit coverage is strong; **live LinkedIn/Naukri cannot be proven in CI**

---

## Subsystem audit

### 1. Pipeline (discover → rule → AI → apply)

**Works:** streaming per-job processing; FOUND / REJECTED / MATCHED / QUEUED / APPROVED; AI unavailable → QUEUED; min match score gate; manual approve → apply next scan; session job/time caps.

**Risks:**

- Apply path calls `portal.apply()` which does **not** fill forms yet (LinkedIn/Naukri return `dry_run` / `awaiting_final_confirmation` after open+screenshot).
- Rejected recheck only diffs stored material fields; status-only rows correctly skip.

### 2. Schedule

**Works:** batches with random durations; `run_probability`; daily budget 60–240m (hard ≤4h); history-based `used_minutes_today`; fixed + human_random modes; Jarvis Schedule tab overrides via SQLite.

**Risks:** budget uses planned minutes from history — if a run crashes early, planned minutes still count (conservative, OK). Clock must be correct local time on the PC.

### 3. AI layer

**Works:** provider factory; Ollama keyless; active provider hot-switch from dashboard; Gemini/DeepSeek optional; vision login JSON check; cover letter / evaluate prompts.

**Defaults now:**

- Text: `qwen3:8b`
- Vision: `qwen3-vl:8b`
- Base: `http://127.0.0.1:11434/v1`

**Risks:** Qwen3 hybrid thinking may emit `<think>…</think>` before JSON. Scoring + vision parsers now strip think/thinking wrappers and fences. Prefer non-thinking or `/no_think` for fast JSON scoring if latency spikes. Raise `request_timeout_seconds` if needed (already 180 in examples).

### 4. Browser / DOM

| Piece | State |
|-------|--------|
| Playwright session / profiles | Ready |
| Search URL builders (LI + Naukri) | Ready |
| Feeds-first plan | Ready |
| Card parse (`_parse_result_cards`) | Code ready; **selectors UNVERIFIED** |
| `RESULTS_SELECTOR` blanks in portal classes | Fall back to config defaults |
| Job detail extractors | Broader fallbacks; still A/B fragile on LinkedIn |
| Login detect | URL heuristics only (+ optional vision) |
| Easy Apply / Naukri apply loop | **Stub** — `# COMPLETE ON LIVE DOM` |
| CAPTCHA detect | Partial (URL checkpoint); iframe not wired |
| Apply-step screenshots | Wired when enabled |

**First PC actions:** `debug.visual_mode: true` → one scan → fix `portals.*.results_selector` + field selectors from evidence bundles.

### 5. Visual / Vision / Diagnostics

| Piece | State |
|-------|--------|
| VisualDebugger overlays / panel | Ready when enabled |
| Diagnostics toolkit / export | Ready |
| Apply-step evidence | Ready |
| Vision login (Qwen3-VL) | Ready; trusts DOM if vision unreachable |
| Emergency banner + Telegram pause | Ready |
| Vision JD fallback (screenshot → fields) | **Not built** (still DOM-first) |

### 6. Jarvis dashboard

**Works:** HUD UI; stats; rejected accordion + Admin approve; schedule JSON; AI provider/model; ops toggles; emergency clear; login from `.env`.

**Gaps (deferred):** full settings editor for every YAML key; live scan start/stop button; plaintext secret display (intentionally never).

### 7. Safety / dry-run contract

- `apply.mode: dry_run` → stop before Apply/Submit (**intended**)
- `require_final_confirmation: true` → even live waits for human
- Dry vs production difference remains **only the final Apply click** once DOM apply is implemented
- Today, even “live” LinkedIn/Naukri apply does not click Submit (incomplete DOM)

---

## PC checklist (must do)

1. `ollama pull qwen3:8b` and `ollama pull qwen3-vl:8b`
2. Set `DASHBOARD_*`, Telegram, `CAREERPILOT_HOME`
3. Log into LinkedIn + Naukri browser profiles
4. Keep `apply.mode: dry_run` and `step_screenshots: true`
5. Turn on `debug.visual_mode` for first scan
6. Confirm Jarvis shows Ollama + schedule budget lines
7. Confirm cards parse (non-zero jobs); if zero → fix selectors from `debug/`
8. Confirm vision login does not false-alarm when logged in
9. Do **not** switch to live Apply until Easy Apply steps are completed on live DOM

---

## What is intentionally not done

- Auto-solving CAPTCHA / OTP
- External ATS automation (Workday/Greenhouse)
- Vision-driven UI clicking
- Guaranteed LinkedIn/Naukri form-fill without your live selector pass

---

## Change in this audit pass

- Defaults / placeholders / VisionConfig → **Qwen 3** (`qwen3:8b`, `qwen3-vl:8b`) — not 2 / 2.5
- REJECTED recheck: no false “changed” when DB row has empty material fields
- Strip Qwen3 `<think>` / `<thinking>` wrappers in AI + vision JSON parsers
- This audit document

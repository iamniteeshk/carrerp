# CareerPilot Portal Completion Checklist

**Overall portal completion: 48%**

Legend: [ ] Not Started · [~] In Progress · [t] Tested · [x] Production Ready

_Tested = proven against a fixture/unit test. Production Ready = confirmed live + stable. Items advance automatically when run evidence (session reports, job bundles) is present._

## Quantitative metrics

**Latest run:**
- Last run: no run recorded yet
- Session reports on file: 0
- Jobs found/rejected/matched/applied: 0/0/0/0
- Success rates: match 0% · apply 0% · reject 0%
- Failure evidence bundles: 0

**Linkedin coverage:**
- Completion: 48% · started 93% · tested+ 43% · production-ready 7%
- Live-evidence coverage: 0% (0/14 items)
- Job bundles: 0 · with full JD: 0 · JD capture rate: 0%

**Naukri coverage:**
- Completion: 49% · started 92% · tested+ 46% · production-ready 8%
- Live-evidence coverage: 0% (0/13 items)
- Job bundles: 0 · with full JD: 0 · JD capture rate: 0%

### LinkedIn -- 48% complete

- [~] **Login detection**: In Progress — auth-wall detection coded; live unverified
- [~] **Session persistence**: In Progress — persistent profile dir; cross-run persistence not live-verified
- [~] **Search**: In Progress — URL search plan unit-tested; live results pending
- [~] **Recommended jobs**: In Progress — recommended feed URL wired; live unverified
- [ ] **Filters**: Not Started — UI-driven filters not implemented (URL nav only)
- [t] **Job card parsing**: Tested — config-driven parser fixture-proven (3 jobs)
- [t] **Job detail extraction**: Tested — open-in-tab + extract + cache proven on fixture
- [t] **Rule Engine integration**: Tested — parsed jobs -> decisions fixture-proven
- [t] **AI integration**: Tested — evaluate + graceful degradation unit-tested; live API pending
- [~] **Apply workflow**: In Progress — orchestration + dry-run built; live Easy-Apply modal is a stub
- [~] **Resume upload**: In Progress — resume selection done; file upload scaffolded, not live
- [~] **Stability**: In Progress — single-thread + recovery built; long run not tested
- [t] **Recovery**: Tested — cache + dedupe crash-recovery unit/fixture-proven
- [x] **Diagnostics coverage**: Production Ready — full toolkit + analyzers, 129 tests

### Naukri -- 49% complete

- [~] **Login detection**: In Progress — login-page detection coded; live unverified
- [~] **Session persistence**: In Progress — persistent profile dir; not live-verified
- [~] **Search**: In Progress — URL search plan unit-tested; live results pending
- [ ] **Filters**: Not Started — UI-driven filters not implemented (URL nav only)
- [t] **Job card parsing**: Tested — config-driven parser fixture-proven (3 jobs)
- [t] **Job detail extraction**: Tested — open-in-tab + extract + cache proven on fixture
- [t] **Rule Engine integration**: Tested — parsed jobs -> decisions fixture-proven
- [t] **AI integration**: Tested — evaluate + graceful degradation unit-tested; live API pending
- [~] **Apply workflow**: In Progress — orchestration + dry-run built; live apply is a stub
- [~] **Resume upload**: In Progress — resume selection done; file upload scaffolded, not live
- [~] **Stability**: In Progress — single-thread + recovery built; long run not tested
- [t] **Recovery**: Tested — cache + dedupe crash-recovery unit/fixture-proven
- [x] **Diagnostics coverage**: Production Ready — full toolkit + analyzers, 129 tests

## How to advance the roadmap

Run a scan with `debug.visual_mode: true`. The evidence bundles, session report and job-detail bundles it writes under `debug/` are read by this checklist (`checklist --evidence debug/`) and automatically promote items from In Progress -> Tested. Confirming an item live and over a long run moves it to Production Ready.
"""Portal Completion Checklist -- the roadmap for portal-focused development.

Each supported portal has a list of capability items, each in one of four states
(Not Started / In Progress / Tested / Production Ready), giving a measurable
completion score per portal. The baseline reflects what is actually in the code
today (honestly: fixture-tested vs live-unverified). The checklist is
EVIDENCE-DRIVEN: pointed at a ``debug/`` directory it reads session reports,
job-detail bundles and failure bundles produced by real runs and PROMOTES items
automatically -- so the roadmap advances from evidence, not guesswork.

States and weights:
  Not Started (0.0) -> In Progress (0.34) -> Tested (0.67) -> Production Ready (1.0)

"Tested"          = exercised end-to-end against a controlled fixture / unit test.
"Production Ready" = confirmed on the live portal AND stable over a long run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.diagnostics.checklist")


class State(str, Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    TESTED = "Tested"
    PRODUCTION_READY = "Production Ready"


_WEIGHT = {State.NOT_STARTED: 0.0, State.IN_PROGRESS: 0.34,
           State.TESTED: 0.67, State.PRODUCTION_READY: 1.0}
_ORDER = {s: i for i, s in enumerate(
    [State.NOT_STARTED, State.IN_PROGRESS, State.TESTED, State.PRODUCTION_READY])}


def _max_state(a: State, b: State) -> State:
    return a if _ORDER[a] >= _ORDER[b] else b


@dataclass
class Item:
    name: str
    state: State
    note: str = ""
    evidence_count: int = 0
    last_verified: str = ""

    def promote_to(self, state: State, why: str, when: str = "") -> None:
        self.evidence_count += 1
        if when:
            self.last_verified = when
        new = _max_state(self.state, state)
        if new != self.state:
            logger.info("[checklist] %s: %s -> %s (%s)", self.name,
                        self.state.value, new.value, why)
            self.state = new
            self.note = why
        elif why:
            self.note = why


@dataclass
class PortalChecklist:
    portal: str
    items: list = field(default_factory=list)

    def score(self) -> int:
        if not self.items:
            return 0
        return round(100 * sum(_WEIGHT[i.state] for i in self.items)
                     / len(self.items))

    def counts(self) -> dict:
        out = {s.value: 0 for s in State}
        for i in self.items:
            out[i.state.value] += 1
        return out

    def coverage(self) -> dict:
        """Quantitative coverage percentages across the checklist items."""
        n = len(self.items) or 1
        started = sum(1 for i in self.items if _ORDER[i.state] >= _ORDER[State.IN_PROGRESS])
        tested = sum(1 for i in self.items if _ORDER[i.state] >= _ORDER[State.TESTED])
        prod = sum(1 for i in self.items if i.state == State.PRODUCTION_READY)
        evidenced = sum(1 for i in self.items if i.evidence_count > 0)
        return {
            "items_total": len(self.items),
            "started_pct": round(100 * started / n),
            "tested_or_better_pct": round(100 * tested / n),
            "production_ready_pct": round(100 * prod / n),
            "evidence_coverage_pct": round(100 * evidenced / n),
            "items_with_live_evidence": evidenced,
        }

    def get(self, name: str) -> Item | None:
        for i in self.items:
            if i.name.lower() == name.lower():
                return i
        return None

    def as_dict(self) -> dict:
        return {"portal": self.portal, "score": self.score(),
                "counts": self.counts(), "coverage": self.coverage(),
                "items": [{"name": i.name, "state": i.state.value, "note": i.note,
                           "evidence_count": i.evidence_count,
                           "last_verified": i.last_verified}
                          for i in self.items]}

    def as_markdown(self) -> str:
        icon = {State.NOT_STARTED: "[ ]", State.IN_PROGRESS: "[~]",
                State.TESTED: "[t]", State.PRODUCTION_READY: "[x]"}
        lines = [f"### {self.portal} -- {self.score()}% complete", ""]
        for i in self.items:
            note = f" — {i.note}" if i.note else ""
            lines.append(f"- {icon[i.state]} **{i.name}**: {i.state.value}{note}")
        return "\n".join(lines)


# ---- honest baseline (what's in the code today) -------------------------

def _linkedin_items() -> list:
    P = State
    return [
        Item("Login detection", P.IN_PROGRESS, "auth-wall detection coded; live unverified"),
        Item("Session persistence", P.IN_PROGRESS, "persistent profile dir; cross-run persistence not live-verified"),
        Item("Search", P.IN_PROGRESS, "URL search plan unit-tested; live results pending"),
        Item("Recommended jobs", P.IN_PROGRESS, "recommended feed URL wired; live unverified"),
        Item("Filters", P.NOT_STARTED, "UI-driven filters not implemented (URL nav only)"),
        Item("Job card parsing", P.TESTED, "config-driven parser fixture-proven (3 jobs)"),
        Item("Job detail extraction", P.TESTED, "open-in-tab + extract + cache proven on fixture"),
        Item("Rule Engine integration", P.TESTED, "parsed jobs -> decisions fixture-proven"),
        Item("AI integration", P.TESTED, "evaluate + graceful degradation unit-tested; live API pending"),
        Item("Apply workflow", P.IN_PROGRESS, "orchestration + dry-run built; live Easy-Apply modal is a stub"),
        Item("Resume upload", P.IN_PROGRESS, "resume selection done; file upload scaffolded, not live"),
        Item("Stability", P.IN_PROGRESS, "single-thread + recovery built; long run not tested"),
        Item("Recovery", P.TESTED, "cache + dedupe crash-recovery unit/fixture-proven"),
        Item("Diagnostics coverage", P.PRODUCTION_READY, "full toolkit + analyzers, 129 tests"),
    ]


def _naukri_items() -> list:
    P = State
    return [
        Item("Login detection", P.IN_PROGRESS, "login-page detection coded; live unverified"),
        Item("Session persistence", P.IN_PROGRESS, "persistent profile dir; not live-verified"),
        Item("Search", P.IN_PROGRESS, "URL search plan unit-tested; live results pending"),
        Item("Filters", P.NOT_STARTED, "UI-driven filters not implemented (URL nav only)"),
        Item("Job card parsing", P.TESTED, "config-driven parser fixture-proven (3 jobs)"),
        Item("Job detail extraction", P.TESTED, "open-in-tab + extract + cache proven on fixture"),
        Item("Rule Engine integration", P.TESTED, "parsed jobs -> decisions fixture-proven"),
        Item("AI integration", P.TESTED, "evaluate + graceful degradation unit-tested; live API pending"),
        Item("Apply workflow", P.IN_PROGRESS, "orchestration + dry-run built; live apply is a stub"),
        Item("Resume upload", P.IN_PROGRESS, "resume selection done; file upload scaffolded, not live"),
        Item("Stability", P.IN_PROGRESS, "single-thread + recovery built; long run not tested"),
        Item("Recovery", P.TESTED, "cache + dedupe crash-recovery unit/fixture-proven"),
        Item("Diagnostics coverage", P.PRODUCTION_READY, "full toolkit + analyzers, 129 tests"),
    ]


def build_checklists() -> dict:
    return {"linkedin": PortalChecklist("LinkedIn", _linkedin_items()),
            "naukri": PortalChecklist("Naukri", _naukri_items())}


# ---- evidence-driven promotion (reads what real runs produced) ----------

def apply_evidence(checklists: dict, debug_dir: str | Path) -> dict:
    """Read a debug/ directory and promote items based on real evidence, with
    timestamps and evidence counts recorded on each item.

    - A session report with found>0  -> Search/Login/Card parsing reached Tested.
    - matched>0                       -> AI integration reached Tested.
    - applied>0 (live)                -> Apply workflow / Resume upload Tested.
    - a job-detail bundle with a non-empty JD -> Job detail extraction Tested.
    """
    from time import strftime, localtime

    debug = Path(debug_dir)
    if not debug.exists():
        logger.info("[checklist] no evidence dir at %s -- baseline only", debug)
        return checklists

    reports = sorted(debug.glob("session_report_*.json"))
    if reports:
        when = strftime("%Y-%m-%d %H:%M", localtime(reports[-1].stat().st_mtime))
        try:
            data = json.loads(reports[-1].read_text())
            counts = data.get("counts", {})
            for cl in checklists.values():
                if counts.get("found", 0) > 0:
                    for n in ("Login detection", "Search", "Job card parsing"):
                        _promote(cl, n, State.TESTED, "live run produced jobs", when)
                if counts.get("matched", 0) > 0:
                    _promote(cl, "AI integration", State.TESTED, "live AI scored jobs", when)
                if counts.get("applied", 0) > 0:
                    _promote(cl, "Apply workflow", State.TESTED, "live application made", when)
                    _promote(cl, "Resume upload", State.TESTED, "resume uploaded live", when)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[checklist] session report read failed: %s", exc)

    for key, cl in checklists.items():
        jobs_dir = debug / "session" / key / "jobs"
        if not jobs_dir.exists():
            continue
        for parsed in jobs_dir.glob("job_*/parsed.json"):
            try:
                rows = json.loads(parsed.read_text())
                if rows and (rows[0].get("job_description") or "").strip():
                    when = strftime("%Y-%m-%d %H:%M",
                                    localtime(parsed.stat().st_mtime))
                    _promote(cl, "Job detail extraction", State.TESTED,
                             "live JD captured in evidence bundle", when)
                    break
            except Exception:  # noqa: BLE001
                continue

    failures = list((debug / "failures").glob("*")) if (debug / "failures").exists() else []
    if failures:
        for cl in checklists.values():
            it = cl.get("Stability")
            if it and "failure bundles present" not in it.note:
                it.note += f" | {len(failures)} failure bundles present"
    return checklists


def quantitative_metrics(checklists: dict, debug_dir: str | Path) -> dict:
    """Run-level + per-portal quantitative metrics derived from the evidence:
    success rates, evidence counts, coverage percentages and timestamps."""
    from time import strftime, localtime

    debug = Path(debug_dir)
    run = {"found": 0, "rejected": 0, "matched": 0, "applied": 0,
           "match_rate_pct": 0, "apply_rate_pct": 0, "reject_rate_pct": 0,
           "last_run": "", "session_reports": 0, "evidence_bundles": 0}
    per_portal = {}

    if debug.exists():
        reports = sorted(debug.glob("session_report_*.json"))
        run["session_reports"] = len(reports)
        if reports:
            run["last_run"] = strftime("%Y-%m-%d %H:%M",
                                       localtime(reports[-1].stat().st_mtime))
            try:
                c = json.loads(reports[-1].read_text()).get("counts", {})
                found = c.get("found", 0) or 0
                run.update(found=found, rejected=c.get("rejected", 0),
                           matched=c.get("matched", 0), applied=c.get("applied", 0))
                if found:
                    run["match_rate_pct"] = round(100 * run["matched"] / found)
                    run["apply_rate_pct"] = round(100 * run["applied"] / found)
                    run["reject_rate_pct"] = round(100 * run["rejected"] / found)
            except Exception:  # noqa: BLE001
                pass
        fdir = debug / "failures"
        run["evidence_bundles"] = (len(list(fdir.glob("*"))) if fdir.exists() else 0)

    for key, cl in checklists.items():
        jobs_dir = debug / "session" / key / "jobs"
        bundles = list(jobs_dir.glob("job_*")) if jobs_dir.exists() else []
        jds = 0
        for b in bundles:
            pj = b / "parsed.json"
            try:
                rows = json.loads(pj.read_text()) if pj.exists() else []
                if rows and (rows[0].get("job_description") or "").strip():
                    jds += 1
            except Exception:  # noqa: BLE001
                pass
        per_portal[key] = {
            "completion_score_pct": cl.score(),
            "coverage": cl.coverage(),
            "job_bundles": len(bundles),
            "jobs_with_full_jd": jds,
            "jd_capture_rate_pct": (round(100 * jds / len(bundles))
                                    if bundles else 0),
        }
    return {"run": run, "portals": per_portal}


def _promote(cl: PortalChecklist, item_name: str, state: State, why: str,
             when: str = "") -> None:
    it = cl.get(item_name)
    if it:
        it.promote_to(state, why, when)


# ---- rendering ----------------------------------------------------------

def render_markdown(checklists: dict, metrics: dict | None = None) -> str:
    overall = round(sum(c.score() for c in checklists.values())
                    / max(1, len(checklists)))
    lines = ["# CareerPilot Portal Completion Checklist", "",
             f"**Overall portal completion: {overall}%**", "",
             "Legend: [ ] Not Started · [~] In Progress · [t] Tested · "
             "[x] Production Ready", "",
             "_Tested = proven against a fixture/unit test. Production Ready = "
             "confirmed live + stable. Items advance automatically when run "
             "evidence (session reports, job bundles) is present._", ""]

    if metrics:
        run = metrics.get("run", {})
        lines += ["## Quantitative metrics", "",
                  "**Latest run:**",
                  f"- Last run: {run.get('last_run') or 'no run recorded yet'}",
                  f"- Session reports on file: {run.get('session_reports', 0)}",
                  f"- Jobs found/rejected/matched/applied: "
                  f"{run.get('found',0)}/{run.get('rejected',0)}/"
                  f"{run.get('matched',0)}/{run.get('applied',0)}",
                  f"- Success rates: match {run.get('match_rate_pct',0)}% · "
                  f"apply {run.get('apply_rate_pct',0)}% · "
                  f"reject {run.get('reject_rate_pct',0)}%",
                  f"- Failure evidence bundles: {run.get('evidence_bundles', 0)}",
                  ""]
        for key, pm in metrics.get("portals", {}).items():
            cov = pm.get("coverage", {})
            lines += [f"**{key.title()} coverage:**",
                      f"- Completion: {pm.get('completion_score_pct',0)}% · "
                      f"started {cov.get('started_pct',0)}% · "
                      f"tested+ {cov.get('tested_or_better_pct',0)}% · "
                      f"production-ready {cov.get('production_ready_pct',0)}%",
                      f"- Live-evidence coverage: "
                      f"{cov.get('evidence_coverage_pct',0)}% "
                      f"({cov.get('items_with_live_evidence',0)}/"
                      f"{cov.get('items_total',0)} items)",
                      f"- Job bundles: {pm.get('job_bundles',0)} · "
                      f"with full JD: {pm.get('jobs_with_full_jd',0)} · "
                      f"JD capture rate: {pm.get('jd_capture_rate_pct',0)}%",
                      ""]

    for cl in checklists.values():
        lines.append(cl.as_markdown())
        lines.append("")
    lines += ["## How to advance the roadmap", "",
              "Run a scan with `debug.visual_mode: true`. The evidence bundles, "
              "session report and job-detail bundles it writes under `debug/` are "
              "read by this checklist (`checklist --evidence debug/`) and "
              "automatically promote items from In Progress -> Tested. Confirming "
              "an item live and over a long run moves it to Production Ready."]
    return "\n".join(lines)


def generate(debug_dir: str | Path = "debug", write_to: str | Path | None = None) -> dict:
    checklists = apply_evidence(build_checklists(), debug_dir)
    metrics = quantitative_metrics(checklists, debug_dir)
    result = {"overall": round(sum(c.score() for c in checklists.values())
                               / max(1, len(checklists))),
              "metrics": metrics,
              "portals": {k: c.as_dict() for k, c in checklists.items()}}
    if write_to:
        try:
            Path(write_to).write_text(render_markdown(checklists, metrics))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[checklist] write failed: %s", exc)
    return result

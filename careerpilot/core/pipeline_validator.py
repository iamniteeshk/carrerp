"""Pipeline validation mode.

Runs one real scan and reports what each stage produced -- Browser/Collector,
Rule Engine, AI Engine, Database, Reports -- so you can see exactly where the
pipeline stops instead of staring at an empty CSV. If a stage unexpectedly
produces zero, it says so loudly and points at the likely cause.
"""

from __future__ import annotations

from ..core.logging_setup import get_logger

logger = get_logger(__name__)


class StageResult:
    def __init__(self, name: str, ok: bool, detail: str):
        self.name = name
        self.ok = ok
        self.detail = detail

    def line(self) -> str:
        mark = "\u2713" if self.ok else "\u2717"
        return f"  [{mark}] {self.name}: {self.detail}"


def validate_pipeline(pilot) -> tuple[bool, list[StageResult]]:
    """Run a scan via ``pilot`` and assess each stage. Returns (ok, results)."""
    results: list[StageResult] = []

    counts = pilot.pipeline.run_once()
    found = counts.get("found", 0)
    rejected = counts.get("rejected", 0)
    matched = counts.get("matched", 0)

    # Browser/Collector
    if found > 0:
        results.append(StageResult("Browser/Collector", True,
                                   f"{found} jobs extracted"))
    else:
        results.append(StageResult(
            "Browser/Collector", False,
            "0 jobs extracted -- selectors likely don't match the live DOM. "
            "Enable debug.visual_mode and check the results_selector in "
            "config.yaml -> portals. (Also confirm you are logged in.)"))

    # Rule Engine (only meaningful if jobs were found)
    if found > 0:
        results.append(StageResult("Rule Engine", True,
                                   f"{matched} accepted, {rejected} rejected"))
    else:
        results.append(StageResult("Rule Engine", False,
                                   "skipped -- no jobs reached it"))

    # AI Engine
    if found > 0 and matched > 0:
        results.append(StageResult("AI Engine", True,
                                   f"scored {matched} matched job(s)"))
    elif found > 0:
        results.append(StageResult("AI Engine", True,
                                   "no jobs passed rules to score (not an error)"))
    else:
        results.append(StageResult("AI Engine", False, "skipped -- no jobs"))

    # Database
    try:
        by_status = pilot.job_service.count_by_status()
        total_db = sum(by_status.values())
        results.append(StageResult("Database", total_db > 0 or found == 0,
                                   f"{total_db} record(s) stored {dict(by_status)}"))
    except Exception as exc:  # noqa: BLE001
        results.append(StageResult("Database", False, f"error: {exc}"))

    # Reports
    try:
        paths = pilot.reporter.generate_all()
        results.append(StageResult("Reports", True,
                                   f"{len(paths)} CSV file(s) generated"))
    except Exception as exc:  # noqa: BLE001
        results.append(StageResult("Reports", False, f"error: {exc}"))

    ok = all(r.ok for r in results)
    return ok, results


def print_report(ok: bool, results: list[StageResult]) -> None:
    print("\n=== CareerPilot Pipeline Validation ===")
    for r in results:
        print(r.line())
    print("=" * 39)
    if ok:
        print("RESULT: pipeline healthy end-to-end.")
    else:
        first_fail = next((r for r in results if not r.ok), None)
        print(f"RESULT: pipeline STOPPED at '{first_fail.name}'.")
        print("        Fix that stage before continuing.")

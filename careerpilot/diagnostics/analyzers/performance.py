"""Performance / Browser Health analyzer (point #6).

Turns the run metrics into a health report: pages visited, jobs opened/parsed,
selectors failed, retries, timeouts, average read/scroll/processing times,
AI/Rule times, CSV/DB updates, memory/CPU (if psutil is present), bottlenecks
and recommendations.

Expected ctx key:
  metrics: a RunMetrics.as_dict() mapping (see diagnostics/metrics.py)
"""

from __future__ import annotations

from .base import Analyzer, AnalysisResult


def _resource_usage() -> dict:
    try:
        import psutil  # optional
        p = psutil.Process()
        return {"memory_mb": round(p.memory_info().rss / 1e6, 1),
                "cpu_percent": p.cpu_percent(interval=0.1)}
    except Exception:  # noqa: BLE001 - psutil optional / may fail in sandbox
        return {}


class PerformanceAnalyzer(Analyzer):
    name = "Performance & Health Analyzer"

    def analyze(self, ctx: dict) -> AnalysisResult:
        m = (ctx or {}).get("metrics", {}) or {}
        res = _resource_usage()
        findings = [
            f"pages visited: {m.get('pages_visited', 0)}",
            f"jobs opened: {m.get('jobs_opened', 0)} | parsed: {m.get('jobs_parsed', 0)}",
            f"selectors failed: {m.get('selectors_failed', 0)}",
            f"retries: {m.get('retries', 0)} | timeouts: {m.get('timeouts', 0)}",
            f"avg read: {m.get('avg_read_ms', 0)}ms | "
            f"avg scroll: {m.get('avg_scroll_ms', 0)}ms",
            f"avg job processing: {m.get('avg_job_ms', 0)}ms",
            f"avg AI: {m.get('avg_ai_ms', 0)}ms | "
            f"avg rule: {m.get('avg_rule_ms', 0)}ms",
            f"CSV updates: {m.get('csv_updates', 0)} | "
            f"DB updates: {m.get('db_updates', 0)}",
        ]
        if res:
            findings.append(f"memory: {res.get('memory_mb')}MB | "
                            f"cpu: {res.get('cpu_percent')}%")

        bottlenecks, recs = [], []
        if m.get("avg_ai_ms", 0) > 8000:
            bottlenecks.append("AI latency high (>8s/job)")
            recs.append("Consider a faster model or batching screening prompts.")
        if m.get("timeouts", 0) > 0:
            bottlenecks.append(f"{m.get('timeouts')} navigation timeout(s)")
            recs.append("Raise networkidle timeout or wait on results selector.")
        if (m.get("jobs_opened", 0) and
                m.get("jobs_parsed", 0) / max(1, m.get("jobs_opened", 1)) < 0.5):
            bottlenecks.append("Low parse yield (<50% of opened jobs parsed)")
            recs.append("Run the Selector/DOM-Diff analyzers -- detail selectors "
                        "may be stale.")
        if res.get("memory_mb", 0) > 1500:
            bottlenecks.append("High memory (>1.5GB)")
            recs.append("Ensure job tabs are closed after extraction; cap "
                        "scroll_passes.")

        sev = "warning" if bottlenecks else "info"
        return AnalysisResult(
            self.name,
            summary=("Browser health: " +
                     (", ".join(bottlenecks) if bottlenecks else "no bottlenecks "
                      "detected.")),
            severity=sev, findings=findings,
            recommendations=recs or ["Performance within expected envelope."],
            data={"metrics": m, "resources": res, "bottlenecks": bottlenecks})

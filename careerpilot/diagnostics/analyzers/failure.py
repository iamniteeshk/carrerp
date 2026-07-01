"""Failure / navigation analyzer (points #1 and #4).

Given the signals captured from a page at the moment something went wrong, this
explains the most likely cause(s) -- logged out, layout change, still loading,
CAPTCHA, redirect to login, network timeout, DOM change, overlay blocking -- each
with the evidence that supports it, ranked by confidence. It explains; it never
acts.

Expected ctx keys (all optional; missing -> not considered):
  signals: {
    has_login_form, has_captcha, has_spinner, has_overlay,
    url, redirected_to_login, networkidle_reached, results_count,
    expected_results, body_text_len, nav_timed_out
  }
"""

from __future__ import annotations

from .base import Analyzer, AnalysisResult


class FailureAnalyzer(Analyzer):
    name = "Failure & Navigation Analyzer"

    def analyze(self, ctx: dict) -> AnalysisResult:
        s = (ctx or {}).get("signals", {}) or {}
        causes: list[tuple[int, str, str]] = []  # (confidence, cause, evidence)

        def add(conf, cause, evidence):
            causes.append((conf, cause, evidence))

        if s.get("has_captcha"):
            add(95, "CAPTCHA detected", "a CAPTCHA element is present on the page")
        if s.get("redirected_to_login") or s.get("has_login_form"):
            add(90, "Redirected to login / logged out",
                f"a login form is present (url={s.get('url', '?')})")
        if s.get("has_overlay"):
            add(70, "Overlay/popup blocking interaction",
                "a modal/overlay element is covering the page")
        if s.get("has_spinner"):
            add(65, "Page still loading",
                "a loading spinner was still visible when read")
        if s.get("nav_timed_out") and not s.get("networkidle_reached", True):
            add(60, "Network idle never reached",
                "navigation timed out before the network went quiet")
        if (s.get("results_count") == 0 and s.get("expected_results")
                and not s.get("has_login_form")):
            add(55, "Search returned zero jobs OR website changed its DOM",
                "the results selector matched 0 elements on a loaded, "
                "logged-in page -- likely a DOM/class-name change or a genuinely "
                "empty search")
        if (s.get("body_text_len", 1) == 0):
            add(50, "Blank/empty page", "the page body had no text")

        causes.sort(reverse=True)
        if not causes:
            return AnalysisResult(
                self.name, summary="No failure signals detected.",
                severity="info")

        top = causes[0]
        findings = [f"{c[1]} (confidence {c[0]}%) -- {c[2]}" for c in causes]
        recs = []
        labels = " ".join(c[1].lower() for c in causes)
        if "login" in labels or "logged out" in labels:
            recs.append("Re-authenticate: confirm the persistent profile is still "
                        "logged in; pause for human login if needed.")
        if "captcha" in labels:
            recs.append("Route to the Human Interaction Engine (pause + notify), "
                        "never auto-solve.")
        if "dom" in labels or "zero jobs" in labels:
            recs.append("Run the Selector Analyzer + DOM Diff to check for a "
                        "layout change before assuming the search was empty.")
        if "spinner" in labels or "idle" in labels:
            recs.append("Increase networkidle/settle timeout for this portal, or "
                        "wait on the results selector explicitly.")
        return AnalysisResult(
            self.name,
            summary=f"Most likely cause: {top[1]} (confidence {top[0]}%).",
            severity="error" if top[0] >= 80 else "warning",
            findings=findings, recommendations=recs,
            data={"ranked_causes": [{"confidence": c[0], "cause": c[1],
                                     "evidence": c[2]} for c in causes]})

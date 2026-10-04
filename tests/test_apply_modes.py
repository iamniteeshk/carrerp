"""Dry, approval, and auto apply modes, plus neutral review holds."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.apply.confidence_gate import ConfidenceGate
from careerpilot.apply.modes import canonical_apply_mode, is_dry_mode, normalize_apply_mode
from careerpilot.browser.form_walker import finish_application
from careerpilot.core.candidate import Candidate
from careerpilot.core.config import ApplyConfig, RuleConfig, _location_list, _salary_floor
from careerpilot.core.decision_memory import DecisionMemory
from careerpilot.core.enums import JobStatus
from careerpilot.core.models import AIEvaluation, Job
from careerpilot.db.database import Database
from careerpilot.db.services import JobService
from careerpilot.apply.pending_flow import next_pending_action
from careerpilot.notify.telegram_service import TelegramService, telegram_text_decision
from careerpilot.rules.rule_engine import RuleEngine


passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def _rules(**kw):
    base = dict(
        minimum_salary=7000000, salary_currency="INR", minimum_experience=15,
        accepted_employment_types=["Full Time"], rejected_shifts=[],
        preferred_locations=["Chennai"],
        accepted_titles=["Director"], rejected_titles=[],
        blacklist_companies=[], required_keywords=["Infrastructure"],
        nice_to_have_keywords=[],
    )
    base.update(kw)
    return RuleConfig(**base)


def _job(**kw):
    defaults = dict(
        portal="LinkedIn", company="GoodCo", job_title="IT Infrastructure Director",
        location="Chennai", salary="", experience="20 years",
        employment_type="Full Time", job_url="https://example.com/j",
        job_description="Lead infrastructure.", is_easy_apply=True,
        status=JobStatus.FOUND,
    )
    defaults.update(kw)
    return Job(**defaults)


def _eval():
    return AIEvaluation(match_score=95, career_profile="Default", confidence=90,
                        reason="fit", apply=True)


def _apply_cfg(mode, **kw):
    base = dict(
        mode=mode, first_run_confirmations=0, max_applications_per_day=10,
        delay_between_applications_seconds=0, retry_limit=1, easy_apply_only=True,
        require_final_confirmation=True,
    )
    base.update(kw)
    return ApplyConfig(**base)


class ScriptedPage:
    """Tiny stand-in for the apply dialog."""

    def __init__(self, required_blank=False):
        self.phase = "closed"
        self.values = {}
        self.clicked_submit = False
        self.required_blank = required_blank

    def evaluate(self, script, arg=None):
        if "CP_SNAPSHOT" in script:
            if self.phase == "closed":
                return {"fields": [], "buttons": [{"idx": 0, "text": "Easy Apply"}]}
            fields = [
                {"idx": 0, "label": "Email", "type": "email",
                 "value": self.values.get(0, ""), "required": True, "options": []},
                {"idx": 1, "label": "Phone", "type": "tel",
                 "value": self.values.get(1, ""), "required": True, "options": []},
            ]
            if self.required_blank:
                fields.append({
                    "idx": 2, "label": "Security clearance id", "type": "text",
                    "value": "", "required": True, "options": [],
                })
            return {"fields": fields, "buttons": [{"idx": 1, "text": "Submit application"}]}
        if "CP_FILL" in script:
            self.values[arg["idx"]] = arg["value"]
            return True
        if "CP_CLICK" in script:
            if self.phase == "closed":
                self.phase = "form"
                return True
            self.clicked_submit = True
            return True
        return None

    def wait_for_timeout(self, ms):
        return None


class Portal:
    def __init__(self, page):
        self.page = page
        self.candidate = Candidate(
            full_name="Test Candidate", email="test.candidate@example.com",
            phone="9999999999",
            current_location="Chennai")
        self.session = None
        self.apply_evidence = None


def test_mode_names_and_gates():
    check("dry alias", normalize_apply_mode("dry") == "dry_run")
    check("auto alias", normalize_apply_mode("automatic") == "auto")
    check("live is approval", normalize_apply_mode("live") == "approval")
    check("blank is dry", canonical_apply_mode("") == "dry_run")
    check("unknown is dry", canonical_apply_mode("maybe") == "dry_run")
    check("is dry", is_dry_mode("dry_run") and not is_dry_mode("approval"))
    dry = ConfidenceGate(_apply_cfg("dry_run"), 90, 100).decide(_job(), _eval(), 0)
    check("dry does not ask", dry.proceed and not dry.needs_approval, dry.reason)
    approval = ConfidenceGate(_apply_cfg("approval"), 90, 100).decide(_job(), _eval(), 0)
    check("approval asks", approval.proceed and approval.needs_approval, approval.reason)
    auto = ConfidenceGate(_apply_cfg("auto"), 90, 100).decide(_job(), _eval(), 0)
    check("auto does not ask", auto.proceed and not auto.needs_approval, auto.reason)
    legacy = ConfidenceGate(
        _apply_cfg("live", require_final_confirmation=False), 90, 100).decide(
            _job(), _eval(), 0)
    check("legacy live still asks", legacy.proceed and legacy.needs_approval, legacy.reason)
    unknown = ConfidenceGate(_apply_cfg("mystery"), 90, 100).decide(_job(), _eval(), 0)
    check("unknown mode is dry", unknown.proceed and not unknown.needs_approval,
          unknown.reason)


def test_form_stops_before_submit_until_allowed():
    page = ScriptedPage()
    out = finish_application(Portal(page), page, _job(), "", lambda q: "", dry_run=True)
    check("dry not submitted", not out.submitted and out.note == "dry_run", out.note)
    check("dry recorded email", any(a.question == "Email" for a in out.answers))
    check("dry did not click submit", not page.clicked_submit)

    page2 = ScriptedPage()
    out2 = finish_application(
        Portal(page2), page2, _job(), "", lambda q: "", dry_run=False,
        confirm_fn=lambda job, filled: "reject")
    check("reject does not submit", (not out2.submitted) and out2.note == "approval:reject"
          and not page2.clicked_submit, out2.note)

    page3 = ScriptedPage()
    out3 = finish_application(
        Portal(page3), page3, _job(), "", lambda q: "", dry_run=False,
        confirm_fn=lambda job, filled: "proceed")
    check("proceed clicks submit", out3.submitted and page3.clicked_submit, out3.note)

    page4 = ScriptedPage()
    out4 = finish_application(Portal(page4), page4, _job(), "", lambda q: "", dry_run=False)
    check("auto clicks submit", out4.submitted and page4.clicked_submit, out4.note)

    page5 = ScriptedPage(required_blank=True)
    out5 = finish_application(
        Portal(page5), page5, _job(), "", lambda q: "", dry_run=False)
    check("unknown required field is review",
          (not out5.submitted) and out5.note.startswith("needs_review")
          and not page5.clicked_submit, out5.note)


def test_salary_hidden_and_grouped_locations():
    eng = RuleEngine(_rules(reject_undisclosed_salary=False))
    result = eng.evaluate(_job(salary=""))
    check("hidden salary not rejected", result.accepted, getattr(result.reason, "value", result.reason))
    low = eng.evaluate(_job(salary="10 LPA"))
    check("low disclosed salary rejected", not low.accepted)
    amount, currency, reject_hidden = _salary_floor({
        "minimum_salary": {"fixed_amount": 7000000, "currency": "INR",
                           "salary_undisclosed": {"reject": False}}
    })
    check("fixed_amount parsed", amount == 7000000 and currency == "INR" and not reject_hidden)
    locs = _location_list({"primary": ["Chennai"], "secondary": ["Bengaluru"], "remote": ["Remote"]})
    check("grouped locations", locs == ["Chennai", "Bengaluru", "Remote"], str(locs))
    flexible = RuleEngine(_rules(reject_outside_preferred=False))
    away = flexible.evaluate(_job(location="Mumbai"))
    check("outside city kept when flexible", away.accepted, getattr(away.reason, "value", ""))


def test_telegram_proceed_and_manual_memory():
    class Store:
        def record(self, *a, **k):
            return 1

    for word in ("yes", "ok", "go", "submit", "approve", "Proceed now", "yes proceed"):
        check(f"not an approval word: {word}", telegram_text_decision(word) is None, word)
    check("exact Proceed", telegram_text_decision("Proceed") == "proceed")
    check("exact proceed", telegram_text_decision("  proceed  ") == "proceed")
    check("exact Reject", telegram_text_decision("Reject") == "reject")
    check("dashboard note cannot submit",
          next_pending_action("proceed", None, "dashboard apply") == "wait")
    check("waiting yes does not submit", next_pending_action("waiting", "yes") == "wait")
    check("waiting Proceed submits", next_pending_action("waiting", "Proceed") == "submit")
    check("waiting Reject does not submit",
          next_pending_action("waiting", "Reject") == "reject")
    svc = TelegramService("token", "42", Store(), timeout=1)
    replies = iter(["yes", "ok", "approve", "Proceed"])

    def _next():
        return next(replies)

    svc._next_reply = _next
    check("telegram proceed", svc.wait_for_reply(timeout_seconds=2, poll_seconds=0) == "proceed")
    svc2 = TelegramService("", "", Store())
    check("telegram off", svc2.wait_for_reply(timeout_seconds=1, poll_seconds=0) == "unavailable")

    with tempfile.TemporaryDirectory() as tmp:
        mem = DecisionMemory(Path(tmp) / "decision_memory.json")
        mem.record(action="apply", job_title="Director EUC", company="HCL")
        mem.record(action="reject", job_title="Sales Director", company="Nope")
        text = mem.summary()
        check("memory mentions both", "Director EUC" in text and "Sales Director" in text, text)

        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        jobs = JobService(db)
        jid = jobs.insert(_job())
        jobs.update_status(jid, JobStatus.CONFUSED, rejection_reason="Needs review")
        row = jobs.approve(jid)
        check("confused can be approved", row and row["status"] == "APPROVED")
        jid2 = jobs.insert(_job(job_url="https://example.com/j2", job_title="Other"))
        jobs.update_status(jid2, JobStatus.CONFUSED)
        row2 = jobs.reject_manual(jid2, "manual reject")
        check("confused can be rejected", row2 and row2["status"] == "REJECTED")
        db.close()


def test_uncertain_evaluation_flag():
    from careerpilot.ai.engine import AIEngine
    from careerpilot.core.config import AIConfig

    class Resp:
        text = ('{"match_score": 72, "career_profile": "Default", "confidence": 40, '
                '"reason": "role is close but seniority is unclear", "apply": false, '
                '"uncertain": true, "decision": "review"}')
        model = "qwen3:8b"
        tokens_used = 12
        cost_usd = 0

    class Prov:
        name = "ollama"

        def is_available(self):
            return True

        def generate(self, prompt, timeout=30):
            return Resp()

    cfg = AIConfig(gemini_keys=[], gemini_model="", deepseek_key="", deepseek_model="",
                   request_timeout=5, max_retries=0, min_apply_score=90)
    engine = AIEngine(cfg, "candidate", ["Default"], "Default")
    engine.providers = [Prov()]
    ev = engine.evaluate_job(_job())
    check("uncertain review", ev.uncertain and not ev.apply, f"uncertain={ev.uncertain} apply={ev.apply}")


def test_dashboard_apply_stays_waiting():
    from careerpilot.dashboard.app import create_dashboard
    from careerpilot.db.services import PendingApplicationService
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        jobs = JobService(db)
        jid = jobs.insert(_job())
        jobs.update_status(jid, JobStatus.CONFUSED, rejection_reason="Needs review")
        settings_mod = __import__(
            "careerpilot.db.services", fromlist=["SettingsService"])
        settings = settings_mod.SettingsService(db)
        settings.set("apply_mode", "approval")

        class _Apply:
            mode = "approval"

        class _Cfg:
            apply = _Apply()
            telegram_token = ""
            telegram_chat_id = ""
            database_path = str(Path(tmp) / "t.db")

        app = create_dashboard(db, 5, config=_Cfg(), settings=settings)
        app.config["TESTING"] = True
        client = app.test_client()
        os.environ["DASHBOARD_USER"] = "Admin"
        os.environ["DASHBOARD_PASSWORD"] = "Adming"
        client.post("/login", data={"username": "Admin", "password": "Adming"})
        resp = client.post(f"/api/jobs/{jid}/approve")
        check("dashboard apply accepted", resp.status_code == 200, str(resp.status_code))
        saved = PendingApplicationService(db).get(jid)
        check("dashboard apply is waiting",
              saved and saved["state"] == "waiting", str(saved))
        check("dashboard apply is not proceed",
              saved and saved["state"] != "proceed" and "dashboard apply" not in (saved["note"] or ""))
        db.close()


def test_no_candidate_pii_in_tracked_tests():
    root = Path(__file__).resolve().parents[1]
    banned = ("Mura" + "hari", "94455" + "05850", "Stats stay " + "public")
    hits = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".venv", "profiles", "deployment_input", "__pycache__"}
               for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".html", ".md", ".yaml", ".yml", ".example", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for word in banned:
            if word in text:
                hits.append(f"{path.relative_to(root)}:{word}")
    check("no banned personal or public-stats text", not hits, "; ".join(hits))


def test_pending_survives_and_salary_label():
    from careerpilot.apply.pending_flow import next_pending_action
    from careerpilot.ai.local_health import classify_provider_failure, prefer_small_local_model
    check("wait until reply", next_pending_action("waiting", None) == "wait")
    check("proceed submits", next_pending_action("waiting", "proceed") == "submit")
    check("reject stops", next_pending_action("waiting", "reject") == "reject")
    check("saved proceed submits", next_pending_action("proceed", None) == "submit")
    check("timeout is ollama class",
          classify_provider_failure(TimeoutError("read timed out")) == "timeout")
    check("refused is unavailable",
          classify_provider_failure(ConnectionError("connection refused")) == "ollama_unavailable")
    check("small model preferred",
          prefer_small_local_model(["qwen3:70b", "qwen3:8b", "qwen3:32b"]) == "qwen3:8b")
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        jobs = JobService(db)
        from careerpilot.db.services import PendingApplicationService
        jid = jobs.insert(_job(salary=""))
        jobs.set_salary_status(jid, "salary_unknown")
        row = jobs.get(jid)
        check("salary_unknown stored", row["salary_status"] == "salary_unknown")
        pending = PendingApplicationService(db)
        job = _job(salary="")
        job.job_id = jid
        pending.upsert(job, state="waiting", filled=[{"label": "Email", "value": "a@b.c"}])
        saved = pending.get(jid)
        check("pending waiting stored", saved and saved["state"] == "waiting")
        pending.set_state(jid, "proceed", "telegram proceed")
        check("pending proceed stored", pending.get(jid)["state"] == "proceed")
        db.close()


def test_dashboard_controls_and_lan_defaults():
    from careerpilot.dashboard.app import create_dashboard
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.initialize()
        app = create_dashboard(db, 5)
        app.config["TESTING"] = True
        client = app.test_client()
        anonymous = client.post("/api/control", json={"action": "stop"})
        check("anonymous control blocked", anonymous.status_code == 401)
        check("anonymous stats blocked", client.get("/api/stats").status_code == 401)
        with client.session_transaction() as sess:
            sess["admin"] = True
        stopped = client.post("/api/control", json={"action": "stop"})
        body = stopped.get_json()
        check("stop control", stopped.status_code == 200 and body["bot_command"] == "stopped",
              str(body))
        stats = client.get("/api/stats").get_json()
        check("stats expose telegram state", stats["telegram"] == "not configured")
        check("stats bot command", stats["bot_command"] == "stopped")
        db.close()


if __name__ == "__main__":
    print("=== apply modes ===")
    test_mode_names_and_gates()
    test_form_stops_before_submit_until_allowed()
    test_salary_hidden_and_grouped_locations()
    test_telegram_proceed_and_manual_memory()
    test_uncertain_evaluation_flag()
    test_dashboard_apply_stays_waiting()
    test_no_candidate_pii_in_tracked_tests()
    test_pending_survives_and_salary_label()
    test_dashboard_controls_and_lan_defaults()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

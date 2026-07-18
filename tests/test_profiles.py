"""Tests for the V2 Career Profile Engine, candidate loader, and schema
validation. All run without network, credentials, or a browser.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.career_profile import CareerProfileEngine, CareerProfileError
from careerpilot.core.candidate import candidate_from_dict
from careerpilot.core.validation import validate_all


def _make_profile(root: Path, name: str, *, with_resume: bool = True,
                  required=("Infrastructure",), locations=("Chennai",)) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(
        f"name: {name}\ndescription: test\nresume: resume.pdf\n"
        f"resume_version: v2\ndocuments:\n  resume: resume.pdf\n")
    if with_resume:
        (d / "resume.pdf").write_text("%PDF-1.4 fake")
    req = "\n".join(f"  - {k}" for k in required)
    (d / "keywords.yaml").write_text(f"required:\n{req}\npreferred:\n  - Azure\n")
    locs = "\n".join(f"- {x}" for x in locations)
    (d / "preferred_locations.yaml").write_text(locs + "\n")
    (d / "screening_answers.yaml").write_text(
        'answers:\n  "How many years of experience": "25 years"\n')


# ---- Career Profile Engine ----------------------------------------------

def test_engine_loads_nested_owner_layout():
    """Production layout: profiles/Murahari_M/<Specialization>/profile.yaml"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        owner = root / "Murahari_M"
        for name in ("General", "Leadership", "GCC"):
            _make_profile(owner, name, required=(name,), locations=("Chennai",))
        eng = CareerProfileEngine(root, "General", 70)
        eng.load()
        assert set(eng.names()) == {"General", "Leadership", "GCC"}
        assert eng.get("General").owner == "Murahari_M"
        assert eng.get("General").relative_key() == "Murahari_M/General"
        assert eng.select("Leadership", 90).name == "Leadership"
        assert eng.select("Ghost", 99).name == "General"


def test_engine_respects_enabled_flag():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        _make_profile(root, "General")
        _make_profile(root, "GCC", required=("GCC",))
        # Disable GCC
        p = root / "GCC" / "profile.yaml"
        text = p.read_text()
        p.write_text(text + "enabled: false\n")
        eng = CareerProfileEngine(root, "General", 70)
        eng.load()
        assert eng.get("GCC").enabled is False
        assert "GCC" not in eng.all_required_keywords()
        assert eng.select("GCC", 99).name == "General"  # disabled → default
        rows = eng.summary_rows()
        assert any(r["name"] == "GCC" and not r["enabled"] for r in rows)


def test_engine_loads_and_unions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        _make_profile(root, "Infrastructure", required=("Infrastructure", "Cloud"),
                      locations=("Chennai", "Remote"))
        _make_profile(root, "GCC", required=("GCC", "Global Delivery"),
                      locations=("Bangalore", "Remote"))
        eng = CareerProfileEngine(root, "Infrastructure", 70)
        eng.load()
        assert set(eng.names()) == {"Infrastructure", "GCC"}
        # Union keywords/locations, de-duplicated.
        assert set(eng.all_required_keywords()) == {
            "Infrastructure", "Cloud", "GCC", "Global Delivery"}
        assert eng.all_preferred_locations().count("Remote") == 1


def test_engine_selection_and_default():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        _make_profile(root, "Infrastructure")
        _make_profile(root, "GCC", required=("GCC",))
        eng = CareerProfileEngine(root, "Infrastructure", 70)
        eng.load()
        assert eng.select("GCC", 90).name == "GCC"           # confident + known
        assert eng.select("GCC", 50).name == "Infrastructure"  # low confidence
        assert eng.select("Ghost", 99).name == "Infrastructure"  # unknown


def test_engine_cached_screening_answer():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        _make_profile(root, "Infrastructure")
        eng = CareerProfileEngine(root, "Infrastructure", 70)
        eng.load()
        p = eng.get("Infrastructure")
        # Case-insensitive / whitespace-normalized match.
        assert p.cached_answer("how many years of experience") == "25 years"
        assert p.cached_answer("unknown question") is None


def test_engine_empty_dir_raises():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        root.mkdir()
        eng = CareerProfileEngine(root, "X", 70)
        try:
            eng.load()
            assert False, "should have raised"
        except CareerProfileError:
            pass


# ---- candidate loader ----------------------------------------------------

def test_candidate_loads_known_and_extra_fields():
    import yaml
    data = yaml.safe_load(
        "full_name: Jane Doe\nemail: jane@x.com\nphone: '+1-555'\n"
        "total_experience: 20 years\n"
        "skills:\n  - Leadership\n  - Cloud\n")
    c = candidate_from_dict(data)
    assert c.full_name == "Jane Doe"
    assert c.email == "jane@x.com"
    assert "Jane Doe" in c.summary()
    assert c.extra["skills"] == ["Leadership", "Cloud"]  # preserved
    assert c.form_values()["phone"] == "+1-555"


# ---- validation ----------------------------------------------------------

def test_validation_reports_missing_and_placeholder_with_lines():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Minimal config pointing at our temp candidate + profiles.
        prof = tmp / "profiles"
        _make_profile(prof, "Infrastructure")
        env = tmp / ".env"
        env.write_text("GEMINI_API_KEY_1=k\n")
        cfg = tmp / "config.yaml"
        # Modern single-file schema: inline candidate with a placeholder email
        # and a missing phone.
        cfg.write_text(
            "scheduler: {scan_interval_hours: 4}\n"
            "candidate:\n  full_name: Tester\n  email: your_email\n"
            "database:\n  path: db\n"
            f"profiles: {{dir: {prof}, default: Infrastructure}}\n"
            f"logging: {{dir: {tmp}/logs}}\n"
            "dashboard: {host: x, port: 1}\nbrowser: {}\n"
            "ai:\n  gemini_model: m\n  gemini_key_env_vars: [GEMINI_API_KEY_1]\n"
            "rules: {}\napply:\n  min_apply_score: 90\n  mode: dry_run\n")
        report = validate_all(cfg, env)
        msgs = [i.message for i in report.errors]
        assert any("candidate.phone is missing" in m for m in msgs), msgs
        assert any("placeholder" in m and "line" in m for m in msgs), msgs
        assert not report.ok


def test_validation_passes_on_good_config():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        prof = tmp / "profiles"
        _make_profile(prof, "Infrastructure")
        env = tmp / ".env"
        env.write_text("GEMINI_API_KEY_1=k\n")
        cfg = tmp / "config.yaml"
        cfg.write_text(
            "scheduler: {scan_interval_hours: 4}\n"
            "candidate:\n  full_name: Tester\n  email: t@x.com\n  phone: '+1-5'\n"
            "database:\n  path: db\n"
            f"profiles: {{dir: {prof}, default: Infrastructure}}\n"
            f"logging: {{dir: {tmp}/logs}}\n"
            "dashboard: {host: x, port: 1}\nbrowser: {}\n"
            "ai:\n  gemini_model: m\n  gemini_key_env_vars: [GEMINI_API_KEY_1]\n"
            "rules: {}\napply:\n  min_apply_score: 90\n  mode: dry_run\n")
        report = validate_all(cfg, env)
        assert report.ok, [i.message for i in report.errors]


def test_new_profile_is_a_dropin_plugin_no_code_change():
    """The core guarantee: dropping in a brand-new profile folder makes the
    Rule Engine, profile selection, and Document Manager all use it -- with no
    Python change and no profile name mentioned anywhere in code."""
    from careerpilot.core.career_profile import CareerProfileEngine
    from careerpilot.core.document_manager import DocumentManager
    from careerpilot.core.config import RuleConfig
    from careerpilot.core.models import Job
    from careerpilot.rules.rule_engine import RuleEngine

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "profiles"
        _make_profile(root, "Infrastructure", required=("Infrastructure",),
                      locations=("Chennai",))
        # A specialization the framework has never heard of, with a unique
        # keyword that no other profile contributes.
        _make_profile(root, "Cybersecurity",
                      required=("Cybersecurity", "CISO", "Zero Trust"),
                      locations=("Remote",))

        eng = CareerProfileEngine(root, "Infrastructure", 70)
        eng.load()
        # 1. Discovered dynamically.
        assert "Cybersecurity" in eng.names()

        # 2. Rule Engine filters expand automatically (built the same way
        #    config.py builds them: from the engine's union).
        rules = RuleConfig(
            minimum_salary=0, salary_currency="INR", minimum_experience=10,
            accepted_employment_types=["Full Time"], rejected_shifts=[],
            preferred_locations=eng.all_preferred_locations(),
            accepted_titles=["Head", "CISO", "Director"], rejected_titles=[],
            blacklist_companies=[],
            required_keywords=eng.all_required_keywords(),  # includes new domain
            nice_to_have_keywords=[])
        engine = RuleEngine(rules)
        cyber_job = Job(portal="LinkedIn", company="SecureCo",
                        job_title="CISO", location="Remote", experience="18 years",
                        employment_type="Full Time", shift="Day Shift",
                        job_description="Lead Zero Trust and Cybersecurity strategy")
        assert engine.evaluate(cyber_job).accepted, "new domain must pass rules"

        # 3. AI picks the new profile -> engine.select returns it.
        chosen = eng.select("Cybersecurity", 92)
        assert chosen.name == "Cybersecurity"

        # 4. Document Manager resolves the new profile's resume with no special
        #    casing.
        docs = DocumentManager(eng)
        assert docs.resume_for(chosen) == chosen.resume_file()
        assert chosen.resume_file().endswith("Cybersecurity/resume.pdf")


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                passed += 1
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

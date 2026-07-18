"""Tests for the production-hardening work.

Covers configuration loading/validation, Career Profile selection, database
reconnect/backup/idempotency, the doctor routine, and scheduler safety. All run
without network, credentials, or a browser.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import yaml

from careerpilot.core.config import ConfigError, load_config
from careerpilot.db.database import Database
from _fixture import make_deployment, make_profile


def _write_env(tmp: str, gemini: str = "k1") -> str:
    path = os.path.join(tmp, ".env")
    with open(path, "w") as fh:
        fh.write(f"GEMINI_API_KEY_1={gemini}\n")
    return path


# ---- configuration -------------------------------------------------------

def test_config_loads_six_career_profiles():
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        cfg = load_config(config_path, env)
        assert len(cfg.profiles) == 6, list(cfg.profiles)
        assert cfg.default_career_profile in cfg.profiles


def test_profile_resumes_exist():
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        cfg = load_config(config_path, env)
        for name, profile in cfg.profiles.items():
            assert profile.resume_path is not None and profile.resume_path.exists(), \
                f"missing resume for profile: {name}"


def test_rule_keywords_are_union_of_profiles():
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        cfg = load_config(config_path, env)
        union = cfg.profile_engine.all_required_keywords()
        for profile in cfg.profiles.values():
            for kw in profile.required_keywords:
                assert kw in cfg.rules.required_keywords
        assert set(union).issubset(set(cfg.rules.required_keywords))


def test_config_rejects_bad_default_profile():
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        raw = yaml.safe_load(open(config_path))
        raw["profiles"]["default"] = "Nonexistent"
        yaml.safe_dump(raw, open(config_path, "w"))
        try:
            load_config(config_path, env)
            assert False, "should have raised"
        except ConfigError:
            pass


def test_no_keys_is_a_validation_error_not_a_load_crash():
    """Config still LOADS without AI keys (so doctor reaches every check), but
    validation flags the missing key as a mandatory error."""
    from careerpilot.core.validation import validate_all
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        open(env, "w").write("")  # wipe the keys the fixture wrote
        for k in ("GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3",
                  "DEEPSEEK_API_KEY"):
            os.environ.pop(k, None)
        # Loads without crashing...
        cfg = load_config(config_path, env)
        assert cfg.ai.gemini_keys == [] and cfg.ai.deepseek_key == ""
        # ...but validation reports it as a mandatory error.
        report = validate_all(config_path, env)
        assert any("AI provider key" in i.message for i in report.errors), \
            [i.message for i in report.errors]


# ---- database ------------------------------------------------------------

def test_database_init_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        db.initialize()
        db.initialize()  # second call must not error or re-run migrations
        conn = db.connect()
        v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        assert v >= 3
        db.close()


def test_database_reconnect_after_close():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        db.initialize()
        db.close()
        # connect() should transparently create a fresh connection
        conn = db.connect()
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        db.close()


def test_database_backup_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(os.path.join(tmp, "test.db"))
        db.initialize()
        backup_dir = os.path.join(tmp, "backups")
        path = db.backup(backup_dir)
        assert os.path.exists(path)
        db.close()


# ---- career profile selection / default fallback ------------------------

def test_engine_select_falls_back_on_low_confidence_or_unknown():
    from careerpilot.core.career_profile import CareerProfileEngine
    tmp = tempfile.mkdtemp()
    make_profile(Path(tmp) / "profiles", "Infrastructure")
    make_profile(Path(tmp) / "profiles", "GCC_Head_CXO", required=["GCC Head"])
    eng = CareerProfileEngine(Path(tmp) / "profiles", "Infrastructure", 70)
    eng.load()
    assert eng.select("GCC_Head_CXO", 95).name == "GCC_Head_CXO"
    assert eng.select("GCC_Head_CXO", 40).name == "Infrastructure"
    assert eng.select("Nonexistent", 99).name == "Infrastructure"


def test_document_manager_falls_back_when_resume_missing():
    from careerpilot.core.document_manager import DocumentManager
    from careerpilot.core.career_profile import CareerProfile, CareerProfileEngine

    tmp = tempfile.mkdtemp()
    make_profile(Path(tmp) / "profiles", "Infrastructure")
    eng = CareerProfileEngine(Path(tmp) / "profiles", "Infrastructure", 70)
    eng.load()
    docs = DocumentManager(eng)
    default_path = eng.default_profile.resume_file()

    # A profile whose resume file does not exist resolves to the default's.
    broken = CareerProfile(name="Broken", folder=Path("profiles/Broken"),
                           resume_path=Path("/does/not/exist.pdf"))
    assert docs.resume_for(broken) == default_path
    # A profile with a real resume uses its own.
    infra = eng.get("Infrastructure")
    assert docs.resume_for(infra) == infra.resume_file()
    # supporting documents come straight from the profile.
    assert isinstance(docs.supporting_documents_for(infra), dict)


# ---- doctor --------------------------------------------------------------

def test_doctor_runs_and_reports():
    from careerpilot.core.doctor import Doctor, FAIL
    with tempfile.TemporaryDirectory() as tmp:
        config_path, env = make_deployment(tmp)
        doc = Doctor(config_path, env)
        # Should complete and produce results without raising.
        doc.run()
        names = {r.name for r in doc.results}
        assert "Configuration" in names
        assert "Database" in names
        assert "Career Profiles" in names
        assert "Schema" in names
        # Config must have loaded fine
        config_result = next(r for r in doc.results if r.name == "Configuration")
        assert config_result.status != FAIL


# ---- scheduler safety ----------------------------------------------------

def test_scheduler_safe_scan_swallows_pipeline_crash():
    from careerpilot.core.scheduler import Scheduler

    class BoomPipeline:
        def run_once(self): raise RuntimeError("boom")

    class FakeTelegram:
        def __init__(self): self.sent = []
        def send(self, ntype, msg): self.sent.append((ntype, msg))

    tg = FakeTelegram()
    sched = Scheduler.__new__(Scheduler)
    sched.pipeline = BoomPipeline()
    sched.telegram = tg
    # Must not raise; must notify a critical error.
    sched._safe_scan()
    assert len(tg.sent) == 1


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

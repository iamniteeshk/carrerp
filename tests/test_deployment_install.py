"""Deployment install: real deployment_input, no Infrastructure, PID lock, bats."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core.bootstrap import (
    PRODUCTION_PROFILES, ensure_scaffold, validate_deployment_input,
)
from careerpilot.core.candidate import candidate_from_dict

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_input_validates():
    problems = validate_deployment_input(ROOT / "deployment_input")
    assert problems == [], problems


def test_setup_copies_six_profiles_and_config_without_infrastructure():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(ROOT / "deployment_input", root / "deployment_input")
        infra = root / "deployment_input" / "profiles" / "Infrastructure"
        infra.mkdir()
        (infra / "profile.yaml").write_text("name: Infrastructure\n", encoding="utf-8")
        example = root / "profiles.example" / "Sample_Profile"
        example.mkdir(parents=True)
        (example / "profile.yaml").write_text("name: Sample_Profile\n", encoding="utf-8")
        (example / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
        (root / "config.example.yaml").write_text("application: {name: Example}\n", encoding="utf-8")
        (root / ".env.example").write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
        old = os.getcwd()
        os.chdir(root)
        try:
            actions = ensure_scaffold()
        finally:
            os.chdir(old)
        cfg = (root / "config" / "config.yaml").read_bytes()
        assert cfg == (ROOT / "deployment_input" / "config.yaml").read_bytes()
        for name in PRODUCTION_PROFILES:
            src = ROOT / "deployment_input" / "profiles" / name / "resume.pdf"
            dst = root / "profiles" / name / "resume.pdf"
            assert dst.read_bytes() == src.read_bytes(), name
        assert not (root / "profiles" / "Infrastructure").exists()
        assert not (root / "profiles" / "Sample_Profile").exists()
        real = root / "profiles" / "Default" / "resume.pdf"
        original = real.read_bytes()
        real.write_bytes(original + b"\n%kept")
        os.chdir(root)
        try:
            ensure_scaffold()
        finally:
            os.chdir(old)
        assert real.read_bytes() == original + b"\n%kept"
        assert any("did not install profiles/Infrastructure" in a for a in actions)


def test_env_example_lists_required_names_and_env_is_ignored():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in (
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_USER",
        "DASHBOARD_PASSWORD", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
        "GEMINI_API_KEY_3", "DEEPSEEK_API_KEY", "EMAIL_PASSWORD",
        "FLASK_SECRET_KEY", "DASHBOARD_SECRET_KEY",
    ):
        assert name in text, name
    assert "MUST REPLACE" in text
    proc = subprocess.run(
        ["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert proc.returncode == 0


def test_candidate_structured_compensation_becomes_form_text():
    cand = candidate_from_dict({
        "full_name": "Test Candidate",
        "email": "test@example.com",
        "phone": "9999999999",
        "current_ctc": {"formatted": "₹77 Lakhs", "fixed": 5000000},
        "notice_period": {"days": 90, "negotiable": True},
        "work_authorization": {"india": True, "usa": "Review required"},
    })
    assert cand.current_ctc == "₹77 Lakhs"
    assert cand.notice_period == "90 days, negotiable"
    assert cand.work_authorization == "India"
    assert cand.extra["current_ctc_detail"]["fixed"] == 5000000


def test_duplicate_pid_is_refused():
    import logging
    from careerpilot.main import CareerPilot
    with tempfile.TemporaryDirectory() as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        try:
            app = CareerPilot.__new__(CareerPilot)
            app.logger = logging.getLogger("pid-test")
            Path("careerpilot.pid").write_text(str(os.getpid()), encoding="utf-8")
            assert app._acquire_pid_lock() is False
            Path("careerpilot.pid").write_text("999999", encoding="utf-8")
            assert app._acquire_pid_lock() is True
            assert Path("careerpilot.pid").read_text(encoding="utf-8") == str(os.getpid())
        finally:
            os.chdir(old)


def test_windows_bats_are_safe():
    win = ROOT / "scripts" / "windows"
    names = [
        "Install_CareerPilot.bat", "Start_CareerPilot.bat", "Stop_CareerPilot.bat",
        "Restart_CareerPilot.bat", "Doctor_CareerPilot.bat", "Open_Dashboard.bat",
        "Setup_Ollama.bat",
    ]
    for name in names:
        text = (win / name).read_text(encoding="ascii")
        assert "Register-CareerPilotStartup" not in text
        assert "taskkill /IM" not in text.lower()
        assert "taskkill /F /IM" not in text
    stop = (win / "Stop_CareerPilot.bat").read_text(encoding="ascii")
    assert "careerpilot.pid" in stop
    assert "/PID" in stop
    ollama = (win / "Setup_Ollama.bat").read_text(encoding="ascii")
    assert "ollama pull qwen3:8b" in ollama
    assert "ollama pull qwen3-vl:8b" in ollama
    assert "Type Y" in ollama
    menu = (ROOT / "CareerPilot.bat").read_text(encoding="ascii")
    assert "CAREERPILOT CONTROL" in menu
    assert "Register-CareerPilotStartup" not in menu
    install = (win / "Install_CareerPilot.bat").read_text(encoding="ascii")
    assert "deployment_input\\config.yaml" in install
    assert "careerpilot\\main.py" in install


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

"""Windows deployment / doctor --fix tests (no real Chrome required)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core import windows_env as wenv
from careerpilot.core.doctor import Doctor, run_doctor
from careerpilot.core.bootstrap import ensure_scaffold, RUNTIME_DIRS
from tests._fixture import make_deployment

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def test_python_version_helper():
    ok, msg = wenv.python_version_ok()
    check("python_version_ok reports", ok and "need" in msg)


def test_disk_and_port_helpers():
    ok, msg = wenv.disk_free_gb(".")
    check("disk_free_gb", ok or "free" in msg, msg)
    ok2, msg2 = wenv.port_available("127.0.0.1", 59999)
    check("port_available high port", ok2, msg2)


def test_find_browser_bundled_channel():
    ok, msg = wenv.find_browser("")
    check("empty channel uses bundled chromium message", ok and "bundled" in msg.lower())


def test_runtime_dirs_include_cache_and_profiles():
    joined = " ".join(RUNTIME_DIRS)
    check("runtime has cache", "cache" in joined)
    check("runtime has browser or profiles_browser",
          "browser/linkedin" in joined or "profiles_browser/linkedin" in joined)


def _isolate_data_root(tmp: Path):
    """Point path resolution at tmp and stop detect_app_root walking to the repo."""
    (tmp / "careerpilot").mkdir(exist_ok=True)
    (tmp / "careerpilot" / "__init__.py").write_text("# test\n")
    keys = ("CAREERPILOT_DATA_ROOT", "CAREERPILOT_HOME", "CAREERPILOT_BACKUPS_ROOT")
    old = {k: os.environ.get(k) for k in keys}
    os.environ["CAREERPILOT_DATA_ROOT"] = str(tmp)
    for k in ("CAREERPILOT_HOME", "CAREERPILOT_BACKUPS_ROOT"):
        os.environ.pop(k, None)
    return old


def _restore_env(old: dict):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_doctor_fix_creates_folders_and_db():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg, env = make_deployment(tmp)
        old = os.getcwd()
        old_env = _isolate_data_root(tmp)
        try:
            os.chdir(tmp)
            for name in ("logs", "screenshots", "reports", "cache"):
                p = tmp / name
                if p.exists():
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
            doc = Doctor(cfg, env, fix=True)
            ok = doc.run()
            check("doctor --fix returns bool", isinstance(ok, bool))
            check("fix created logs", (tmp / "logs").is_dir())
            check("fix created cache/jobs or cache",
                  (tmp / "cache").is_dir() or (tmp / "cache" / "jobs").is_dir())
            check("fix created profiles_browser/linkedin or browser/linkedin",
                  (tmp / "profiles_browser" / "linkedin").is_dir()
                  or (tmp / "browser" / "linkedin").is_dir())
            check("database file exists after fix",
                  Path(doc.config.database_path).exists() if doc.config else False)
            check("doctor completed report", len(doc.results) >= 5)
            check("doctor has readiness score",
                  getattr(doc, "readiness_score", 0) > 0)
        finally:
            os.chdir(old)
            _restore_env(old_env)


def test_doctor_reports_missing_ai_key_clearly():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cfg, env = make_deployment(tmp)
        Path(env).write_text("# empty\n")
        old_key = os.environ.pop("GEMINI_API_KEY_1", None)
        old_cwd = os.getcwd()
        old_env = _isolate_data_root(tmp)
        try:
            os.chdir(tmp)
            doc = Doctor(cfg, env, fix=False)
            ok = doc.run()
            check("doctor fails without AI key", ok is False)
            msgs = " ".join(r.message for r in doc.results if r.status == "FAIL")
            check("failure mentions key / .env",
                  "key" in msgs.lower() or "GEMINI" in msgs or ".env" in msgs,
                  msgs)
        finally:
            os.chdir(old_cwd)
            _restore_env(old_env)
            if old_key is not None:
                os.environ["GEMINI_API_KEY_1"] = old_key


def test_ensure_scaffold_prefer_production():
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old = os.getcwd()
        try:
            os.chdir(repo)
            target = tmp / "config" / "config.yaml"
            actions = ensure_scaffold(target, prefer_production=True)
            check("scaffold created config", target.exists())
            body = target.read_text(encoding="utf-8")
            check("production template preferred when available",
                  "require_final_confirmation" in body or "Chennai" in body)
            check("scaffold returns actions list", isinstance(actions, list))
        finally:
            os.chdir(old)


def test_root_doctor_py_exists():
    root = Path(__file__).resolve().parents[1]
    check("doctor.py at repo root", (root / "doctor.py").exists())
    check("setup_windows.ps1 at repo root", (root / "setup_windows.ps1").exists())
    check("INSTALL_WINDOWS.md", (root / "docs" / "INSTALL_WINDOWS.md").exists())


if __name__ == "__main__":
    print("=== Windows deployment / doctor --fix ===")
    test_python_version_helper()
    test_disk_and_port_helpers()
    test_find_browser_bundled_channel()
    test_runtime_dirs_include_cache_and_profiles()
    test_doctor_fix_creates_folders_and_db()
    test_doctor_reports_missing_ai_key_clearly()
    test_ensure_scaffold_prefer_production()
    test_root_doctor_py_exists()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

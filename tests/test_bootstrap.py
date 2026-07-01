"""Tests for first-run bootstrap (ensure_scaffold): a fresh clone with only
example files becomes runnable, idempotently, without overwriting real files.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core import bootstrap


def _fake_clone(root: Path) -> None:
    """Lay down only the example files a fresh clone ships with."""
    (root / "config.example.yaml").write_text("application: {name: CP}\n")
    (root / ".env.example").write_text("GEMINI_API_KEY_1=\n")
    ex = root / "profiles.example" / "Sample_Profile"
    ex.mkdir(parents=True)
    (ex / "profile.yaml").write_text("name: Sample_Profile\nresume: resume.pdf\n")
    (ex / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF")


def _run_in(root: Path):
    cwd = os.getcwd()
    os.chdir(root)
    try:
        return bootstrap.ensure_scaffold()
    finally:
        os.chdir(cwd)


def test_bootstrap_creates_config_profiles_env_and_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_clone(root)
        actions = _run_in(root)
        assert (root / "config" / "config.yaml").exists()
        assert (root / "profiles" / "Sample_Profile" / "profile.yaml").exists()
        assert (root / "profiles" / "Sample_Profile" / "resume.pdf").exists()
        assert (root / ".env").exists()
        for d in ("logs", "database", "screenshots", "reports", "profiles_browser"):
            assert (root / d).is_dir(), d
        assert actions, "should report what it created"


def test_bootstrap_is_idempotent_and_never_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fake_clone(root)
        _run_in(root)
        # Put real user content in place; a second run must NOT clobber it.
        (root / "config" / "config.yaml").write_text("REAL USER CONFIG\n")
        (root / ".env").write_text("GEMINI_API_KEY_1=realkey\n")
        actions = _run_in(root)
        assert actions == [], "second run should do nothing"
        assert (root / "config" / "config.yaml").read_text() == "REAL USER CONFIG\n"
        assert "realkey" in (root / ".env").read_text()


def test_bootstrap_without_examples_does_not_crash():
    with tempfile.TemporaryDirectory() as tmp:
        # No example files at all -> should still create runtime dirs, no crash.
        actions = _run_in(Path(tmp))
        assert (Path(tmp) / "logs").is_dir()
        # config/profiles not created (nothing to copy from), but no exception.


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

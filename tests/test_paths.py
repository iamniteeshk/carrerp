"""Tests for production data-root path resolution and layout."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from careerpilot.core import paths, bootstrap, backup_ops


def _isolate(env: dict):
    """Context: set env keys, clear layout-related vars not listed."""
    keys = ("CAREERPILOT_DATA_ROOT", "CAREERPILOT_HOME", "CAREERPILOT_BACKUPS_ROOT")
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        if k in env:
            os.environ[k] = env[k]
        elif k in os.environ:
            del os.environ[k]
    return old


def _restore(old: dict):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_app(root: Path) -> Path:
    """Minimal app tree so detect_app_root stops here."""
    pkg = root / "careerpilot"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("# test\n")
    (root / "config.example.yaml").write_text(
        "application: {name: CP}\n"
        "candidate: {full_name: T, email: t@e.com}\n"
        "profiles: {default: Default}\n"
        "apply: {min_apply_score: 70}\n"
        "browser:\n  profiles_path: browser\n"
    )
    (root / ".env.example").write_text("GEMINI_API_KEY_1=\n")
    ex = root / "profiles.example" / "Default"
    ex.mkdir(parents=True)
    (ex / "profile.yaml").write_text("name: Default\nresume: resume.pdf\n")
    (ex / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    return root


def test_resolve_data_root_env():
    with tempfile.TemporaryDirectory() as tmp:
        app = _make_app(Path(tmp) / "app")
        data = Path(tmp) / "mydata"
        data.mkdir()
        old = _isolate({"CAREERPILOT_DATA_ROOT": str(data)})
        try:
            assert paths.resolve_data_root(app) == data.resolve()
        finally:
            _restore(old)


def test_resolve_sibling_when_repo_named_app():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "CareerPilot"
        app = _make_app(home / "app")
        old = _isolate({})
        try:
            got = paths.resolve_data_root(app)
            assert got == (home / "data").resolve()
            backups = paths.resolve_backups_root(got, app)
            assert backups == (home / "backups").resolve()
        finally:
            _restore(old)


def test_resolve_home_env():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "CP"
        home.mkdir()
        app = _make_app(Path(tmp) / "elsewhere")
        old = _isolate({"CAREERPILOT_HOME": str(home)})
        try:
            assert paths.resolve_data_root(app) == (home / "data").resolve()
        finally:
            _restore(old)


def test_layout_ensure_dirs_and_scaffold():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "CareerPilot"
        app = _make_app(home / "app")
        data = home / "data"
        old = _isolate({"CAREERPILOT_HOME": str(home)})
        cwd = os.getcwd()
        try:
            os.chdir(app)
            layout = paths.get_layout(app_root=app)
            assert layout.data_root == data.resolve()
            created = layout.ensure_dirs()
            assert (data / "browser" / "linkedin").is_dir()
            assert (data / "database" / "backups").is_dir()
            assert (home / "backups").is_dir()
            assert created  # first run creates dirs

            actions = bootstrap.ensure_scaffold()
            assert (data / "config" / "config.yaml").exists()
            assert (data / ".env").exists()
            assert (data / "profiles" / "Default" / "profile.yaml").exists()
            assert (data / "README.md").exists()
            # Second scaffold is idempotent
            assert bootstrap.ensure_scaffold() == []
            # Config should prefer browser path
            text = (data / "config" / "config.yaml").read_text()
            assert "profiles_path: browser" in text or "profiles_path:browser" in text.replace(" ", "")
        finally:
            os.chdir(cwd)
            _restore(old)


def test_backup_roundtrip_under_data_root():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "CareerPilot"
        app = _make_app(home / "app")
        old = _isolate({"CAREERPILOT_HOME": str(home)})
        cwd = os.getcwd()
        try:
            os.chdir(app)
            bootstrap.ensure_scaffold()
            layout = paths.get_layout(app_root=app)
            # Seed a tiny DB file
            layout.database_path.parent.mkdir(parents=True, exist_ok=True)
            layout.database_path.write_bytes(b"sqlite-placeholder")
            (layout.database_dir / "good_jobs.json").write_text("[]")

            result = backup_ops.create_backup(
                include_chrome_profiles=False,
                include_logs=False,
                include_reports=False,
                stamp="2099-01-01",
            )
            assert Path(result.path).exists()
            v = backup_ops.verify_backup(result.path)
            assert v["ok"], v
            assert "config/config.yaml" in v["present"]

            # Restore into a fresh data dir
            dest = Path(tmp) / "restored_data"
            dest.mkdir()
            r2 = backup_ops.restore_backup(result.path, root=dest, force=True)
            assert "config" in r2.copied or "profiles" in r2.copied
            assert (dest / "config" / "config.yaml").exists() or (
                dest / "profiles").exists()
        finally:
            os.chdir(cwd)
            _restore(old)


def test_layout_resolve_relative():
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        layout = paths.DataLayout(
            data_root=data.resolve(),
            app_root=Path(tmp).resolve(),
            backups_root=(Path(tmp) / "backups").resolve(),
        )
        assert layout.resolve("logs") == (data / "logs").resolve()
        abs_p = Path("/tmp/abs").resolve()
        assert layout.resolve(abs_p) == abs_p


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
    print(f"{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)

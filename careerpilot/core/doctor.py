"""Startup validation -- the "doctor" routine.

Runs pre-flight checks and prints a clear PASS / WARNING / FAIL report.
Mandatory failures cause a non-zero exit (fail fast).

Run via:
    python -m careerpilot.main doctor
    python -m careerpilot.main doctor --fix
    python doctor.py [--fix]

``--fix`` safely repairs what can be automated (folders, DB schema, Playwright
browser binary, config templates, Chrome profile dirs). It never invents API
keys, Telegram credentials, or website logins — those always need a human.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .bootstrap import ensure_scaffold
from .config import AppConfig, ConfigError, load_config
from .logging_setup import get_logger
from . import windows_env as wenv

logger = get_logger(__name__)

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_SYMBOL = {PASS: "[ OK ]", FAIL: "[FAIL]", WARN: "[WARN]", SKIP: "[SKIP]"}

RUNTIME_DIRS = (
    "logs", "database", "database/backups", "screenshots", "reports",
    "profiles_browser", "cache", "cache/jobs", "documents", "debug",
)


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    mandatory: bool = True
    fixed: bool = False


@dataclass
class FixAction:
    description: str
    ok: bool = True
    detail: str = ""


class Doctor:
    """Collects and reports pre-flight checks. Optionally auto-repairs safe issues."""

    def __init__(self, config_path: str = "config/config.yaml",
                 env_path: str = ".env", *, fix: bool = False,
                 production: bool = False):
        self.config_path = config_path
        self.env_path = env_path
        self.fix = fix
        self.production = production
        self.results: list[CheckResult] = []
        self.fixes: list[FixAction] = []
        self.config: AppConfig | None = None

    def run(self) -> bool:
        """Run all checks. Returns True if no mandatory check failed."""
        if self.fix:
            self._apply_safe_fixes()

        self._check_host_python()
        self._check_py_launcher()
        self._check_git()
        self._check_pip()
        self._check_venv()
        self._check_windows()
        self._check_disk()
        self._check_internet()

        self._check_schema()
        self._check_config()
        if self.config is not None:
            self._check_env_file()
            self._check_gemini_keys()
            self._check_deepseek()
            self._check_telegram()
            self._check_folders()
            self._check_write_permissions()
            self._check_database()
            self._check_profiles()
            self._check_browser_profiles()
            self._check_system_browser()
            self._check_port()
            self._check_maintenance_config()
        else:
            self._check_env_file_raw()

        self._check_playwright()
        self._check_browser_binary()
        self._print_report()
        return not any(r.status == FAIL and r.mandatory for r in self.results)

    # ---- fix mode --------------------------------------------------------

    def _apply_safe_fixes(self) -> None:
        """Repair only safe, non-secret issues. Idempotent."""
        print("Doctor --fix: applying safe repairs...\n")

        # 1. Scaffold config / profiles / .env templates / base dirs.
        try:
            actions = ensure_scaffold(self.config_path)
            for a in actions:
                self.fixes.append(FixAction(a, True))
        except Exception as exc:  # noqa: BLE001
            self.fixes.append(FixAction("ensure_scaffold", False, str(exc)))

        # 2. Prefer production template when requested and config is still stock.
        if self.production:
            self._maybe_copy_production_config()

        # 3. Extra runtime directories (incl. cache / backups).
        for name in RUNTIME_DIRS:
            d = Path(name)
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    self.fixes.append(FixAction(f"created {name}/", True))
                except OSError as exc:
                    self.fixes.append(FixAction(f"create {name}/", False, str(exc)))

        # 4. Per-portal Chrome profile dirs (Playwright user-data-dir).
        for portal in ("linkedin", "naukri"):
            d = Path("profiles_browser") / portal
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    self.fixes.append(FixAction(
                        f"created Chrome profile dir {d}/", True))
                except OSError as exc:
                    self.fixes.append(FixAction(f"create {d}/", False, str(exc)))

        # 5. Initialize database schema.
        try:
            cfg_path = Path(self.config_path)
            if cfg_path.exists():
                cfg = load_config(self.config_path, self.env_path)
                from ..db.database import Database
                db = Database(cfg.database_path)
                db.initialize()
                db.close()
                self.fixes.append(FixAction(
                    f"database initialized at {cfg.database_path}", True))
        except Exception as exc:  # noqa: BLE001
            self.fixes.append(FixAction("database initialize", False, str(exc)))

        # 6. Install Playwright Chromium if missing.
        ok, msg = wenv.playwright_browser_installed()
        if not ok:
            self.fixes.append(FixAction(
                "installing Playwright Chromium browser...", True, msg))
            try:
                from .python_launcher import resolve_python_argv
                r = subprocess.run(
                    [*resolve_python_argv(), "-m", "playwright", "install", "chromium"],
                    capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    self.fixes.append(FixAction(
                        "Playwright Chromium installed", True))
                else:
                    self.fixes.append(FixAction(
                        "Playwright Chromium install", False,
                        (r.stderr or r.stdout or "failed")[:400]))
            except Exception as exc:  # noqa: BLE001
                self.fixes.append(FixAction(
                    "Playwright Chromium install", False, str(exc)))

        if self.fixes:
            print("Repairs:")
            for f in self.fixes:
                mark = "OK" if f.ok else "FAIL"
                extra = f" — {f.detail}" if f.detail else ""
                print(f"  [{mark}] {f.description}{extra}")
            print()

    def _maybe_copy_production_config(self) -> None:
        """Copy config.production.example.yaml when no real config exists yet."""
        target = Path(self.config_path)
        prod = Path("config.production.example.yaml")
        if target.exists() or not prod.exists():
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(prod, target)
            self.fixes.append(FixAction(
                f"created {target} from config.production.example.yaml", True))
        except OSError as exc:
            self.fixes.append(FixAction("copy production config", False, str(exc)))

    # ---- checks ----------------------------------------------------------

    def _add(self, name: str, status: str, message: str = "",
             mandatory: bool = True, fixed: bool = False) -> None:
        self.results.append(CheckResult(name, status, message, mandatory, fixed))

    def _check_host_python(self) -> None:
        ok, msg = wenv.python_version_ok()
        self._add("Python", PASS if ok else FAIL, msg)

    def _check_py_launcher(self) -> None:
        """On Windows, prefer ``py``. Missing bare ``python`` is OK."""
        if not wenv.is_windows():
            self._add("py launcher", SKIP, "non-Windows host", mandatory=False)
            return
        ok, msg = wenv.py_launcher_available()
        # WARN not FAIL — .venv\Scripts\python.exe is enough after setup.
        self._add("py launcher", PASS if ok else WARN, msg, mandatory=False)
        # Explicitly do NOT fail if `python` is missing from PATH.
        bare = __import__("shutil").which("python")
        if bare and "WindowsApps" in bare:
            self._add("python on PATH", WARN,
                      f"WindowsApps stub at {bare} — use py or .venv instead",
                      mandatory=False)
        elif not bare:
            self._add("python on PATH", PASS,
                      "not required — CareerPilot uses py / .venv",
                      mandatory=False)

    def _check_pip(self) -> None:
        ok, msg = wenv.pip_working()
        self._add("pip", PASS if ok else FAIL, msg)

    def _check_git(self) -> None:
        ok, msg = wenv.git_installed()
        self._add("Git", PASS if ok else WARN, msg, mandatory=False)

    def _check_venv(self) -> None:
        ok, msg = wenv.venv_active_or_present(Path.cwd())
        self._add("Virtual environment", PASS if ok else WARN, msg,
                  mandatory=False)

    def _check_windows(self) -> None:
        if not wenv.is_windows():
            self._add("Windows", SKIP,
                      f"{sys.platform} host (Windows checks skipped)",
                      mandatory=False)
            return
        ok, msg = wenv.windows_version()
        self._add("Windows", PASS if ok else WARN, msg, mandatory=False)

    def _check_disk(self) -> None:
        ok, msg = wenv.disk_free_gb(".")
        self._add("Disk space", PASS if ok else FAIL, msg)

    def _check_internet(self) -> None:
        ok, msg = wenv.internet_ok()
        self._add("Internet", PASS if ok else WARN, msg, mandatory=False)

    def _check_schema(self) -> None:
        from .validation import validate_all
        if not Path(self.config_path).exists():
            self._add("Schema", FAIL,
                      f"{self.config_path} missing — run setup or doctor --fix")
            return
        report = validate_all(self.config_path, self.env_path)
        for issue in report.errors:
            self._add("Schema", FAIL, issue.message)
        for issue in report.warnings:
            self._add("Schema", WARN, issue.message, mandatory=False)
        if not report.errors and not report.warnings:
            self._add("Schema", PASS, "config, candidate, and profiles valid")

    def _check_config(self) -> None:
        try:
            self.config = load_config(self.config_path, self.env_path)
            self._add("Configuration", PASS, f"loaded {self.config_path}")
        except ConfigError as exc:
            self._add("Configuration", FAIL, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._add("Configuration", FAIL, f"unexpected: {exc}")

    def _check_env_file(self) -> None:
        if Path(self.env_path).exists():
            self._add(".env file", PASS, self.env_path)
        else:
            self._add(".env file", FAIL,
                      f"{self.env_path} not found (copy .env.example to .env "
                      f"or run: py -m careerpilot.main doctor --fix)")

    def _check_env_file_raw(self) -> None:
        if Path(self.env_path).exists():
            self._add(".env file", PASS, self.env_path)
        else:
            self._add(".env file", FAIL, f"{self.env_path} not found")

    def _check_gemini_keys(self) -> None:
        assert self.config
        n = len(self.config.ai.gemini_keys)
        provider_keys = 0
        for spec in getattr(self.config.ai, "providers", []) or []:
            if not getattr(spec, "enabled", True):
                continue
            keys = getattr(spec, "api_keys", None) or []
            if keys:
                provider_keys += len(keys)
            elif not getattr(spec, "requires_auth", True):
                provider_keys += 1
        if n > 0:
            self._add("Gemini API keys", PASS, f"{n} key(s) configured")
        elif provider_keys > 0:
            self._add("AI provider keys", PASS,
                      f"{provider_keys} provider key(s)/endpoint(s) configured")
        elif self.config.ai.deepseek_key:
            self._add("Gemini API keys", WARN,
                      "no Gemini keys; relying on DeepSeek fallback",
                      mandatory=False)
        else:
            self._add("AI provider keys", FAIL,
                      "no AI key in .env — set GEMINI_API_KEY_1=... "
                      "(doctor --fix cannot invent secrets)")

    def _check_deepseek(self) -> None:
        assert self.config
        if self.config.ai.deepseek_key:
            self._add("DeepSeek key (optional)", PASS, "configured",
                      mandatory=False)
        else:
            self._add("DeepSeek key (optional)", SKIP, "not set",
                      mandatory=False)

    def _check_telegram(self) -> None:
        assert self.config
        token = self.config.telegram_token
        chat = self.config.telegram_chat_id
        if token and chat:
            self._add("Telegram", PASS, "token + chat id set", mandatory=False)
        elif token or chat:
            self._add("Telegram", WARN,
                      "only one of TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID set",
                      mandatory=False)
        else:
            self._add("Telegram", WARN,
                      "not configured — set TELEGRAM_BOT_TOKEN and "
                      "TELEGRAM_CHAT_ID in .env for notifications",
                      mandatory=False)

    def _check_folders(self) -> None:
        assert self.config
        c = self.config
        folders = {
            "logs": c.log_path, "screenshots": c.screenshot_path,
            "reports": c.report_path, "backups": c.backup_path,
            "profiles_browser": c.browser_profiles_path,
            "cache": "cache",
        }
        problems = []
        for name, path in folders.items():
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                problems.append(f"{name}: {exc}")
        if problems:
            self._add("Required folders", FAIL, "; ".join(problems))
        else:
            self._add("Required folders", PASS, f"{len(folders)} folders ready")

    def _check_write_permissions(self) -> None:
        assert self.config
        targets = [self.config.log_path, self.config.report_path,
                   self.config.database_path and str(Path(self.config.database_path).parent)]
        bad = []
        for t in targets:
            if not t:
                continue
            ok, msg = wenv.path_writable(t)
            if not ok:
                bad.append(msg)
        if bad:
            self._add("Write permissions", FAIL, "; ".join(bad))
        else:
            self._add("Write permissions", PASS, "logs/reports/database writable")

    def _check_database(self) -> None:
        assert self.config
        try:
            from ..db.database import Database
            db = Database(self.config.database_path)
            db.initialize()
            db.close()
            self._add("Database", PASS,
                      f"schema ready at {self.config.database_path}")
        except Exception as exc:  # noqa: BLE001
            self._add("Database", FAIL, str(exc))

    def _check_profiles(self) -> None:
        assert self.config
        engine = self.config.profile_engine
        names = engine.names()
        missing = []
        for name, profile in engine.profiles.items():
            if profile.resume_path is None or not profile.resume_path.exists():
                missing.append(name)
        if not missing:
            self._add("Resume files", PASS,
                      f"{len(names)} profile(s) have resume.pdf")
            self._add("Career Profiles", PASS,
                      f"{len(names)} profile(s): {', '.join(names)}")
        else:
            default = self.config.default_career_profile
            default_ok = default not in missing
            self._add("Resume files", WARN if default_ok else FAIL,
                      f"resume.pdf missing for: {', '.join(missing)} — "
                      f"copy your PDF into profiles/<Name>/resume.pdf",
                      mandatory=not default_ok)
            self._add("Career Profiles", WARN if default_ok else FAIL,
                      f"{len(names)} loaded; default '{default}' "
                      + ("OK" if default_ok else "MISSING RESUME"),
                      mandatory=not default_ok)

    def _check_browser_profiles(self) -> None:
        assert self.config
        path = Path(self.config.browser_profiles_path)
        linkedin = path / "linkedin"
        naukri = path / "naukri"
        has_any = path.exists() and any(path.iterdir()) if path.exists() else False
        # Heuristic: a used Playwright profile usually has Default/ or Local State.
        def _looks_used(d: Path) -> bool:
            if not d.exists():
                return False
            if (d / "Default").exists() or (d / "Local State").exists():
                return True
            try:
                return any(d.iterdir())
            except OSError:
                return False

        if not has_any:
            self._add("Chrome profile dirs", WARN,
                      f"empty {path} — first headed run creates profiles; "
                      f"log into LinkedIn/Naukri once",
                      mandatory=False)
            return
        self._add("Chrome profile dirs", PASS, f"present under {path}",
                  mandatory=False)
        if _looks_used(linkedin):
            self._add("LinkedIn login", PASS,
                      "profile data present (verify manually on first run)",
                      mandatory=False)
        else:
            self._add("LinkedIn login", WARN,
                      "no saved session yet — open LinkedIn once in CareerPilot "
                      "and log in",
                      mandatory=False)
        if _looks_used(naukri):
            self._add("Naukri login", PASS,
                      "profile data present (verify manually on first run)",
                      mandatory=False)
        else:
            self._add("Naukri login", WARN,
                      "no saved session yet — open Naukri once in CareerPilot "
                      "and log in",
                      mandatory=False)

    def _check_system_browser(self) -> None:
        assert self.config
        channel = (self.config.browser.channel or "").strip().lower()
        if not channel:
            self._add("System browser", PASS,
                      "using Playwright bundled Chromium (browser.channel empty)",
                      mandatory=False)
            return
        ok, msg = wenv.find_browser(channel)
        if ok:
            self._add("System browser", PASS, msg, mandatory=False)
            return
        # Playwright falls back to bundled Chromium when the channel is missing
        # (see browser/session.py). On Windows production this is a WARN so the
        # operator installs Chrome; it is not a hard FAIL that blocks setup.
        self._add("System browser", WARN,
                  msg + " — CareerPilot will fall back to bundled Chromium",
                  mandatory=False)

    def _check_port(self) -> None:
        assert self.config
        host = self.config.dashboard_host or "127.0.0.1"
        port = int(self.config.dashboard_port or 8006)
        ok, msg = wenv.port_available(host, port)
        self._add("Dashboard port", PASS if ok else WARN, msg, mandatory=False)

    def _check_maintenance_config(self) -> None:
        assert self.config
        ret = getattr(self.config, "retention", None)
        if ret is None:
            self._add("Maintenance / retention", WARN,
                      "no maintenance: section — using defaults",
                      mandatory=False)
        else:
            self._add("Maintenance / retention", PASS,
                      f"cache={ret.cache_days}d reports={ret.report_days}d "
                      f"screenshots={ret.screenshot_days}d "
                      f"daily@{ret.maintenance_hour:02d}:15",
                      mandatory=False)

    def _check_playwright(self) -> None:
        import importlib.util
        if importlib.util.find_spec("playwright") is not None:
            self._add("Playwright package", PASS, "importable")
        else:
            self._add("Playwright package", FAIL,
                      "not installed — run setup_windows.ps1 or: "
                      "py -m pip install -r requirements.txt")

    def _check_browser_binary(self) -> None:
        ok, msg = wenv.playwright_browser_installed()
        if ok:
            self._add("Playwright Chromium", PASS, "installed")
        else:
            hint = msg
            if self.fix:
                hint += " (doctor --fix already attempted install)"
            else:
                hint += " — run: py -m careerpilot.main doctor --fix"
            self._add("Playwright Chromium", FAIL, hint)

    # ---- report ----------------------------------------------------------

    def _print_report(self) -> None:
        lines = ["", "=" * 64, "  CareerPilot Doctor — production pre-flight",
                 "=" * 64]
        for r in self.results:
            tag = "" if r.mandatory else "  (optional)"
            lines.append(f" {_SYMBOL[r.status]}  {r.name}{tag}")
            if r.message:
                lines.append(f"          {r.message}")
        failed = [r for r in self.results if r.status == FAIL and r.mandatory]
        warns = [r for r in self.results if r.status == WARN]
        lines.append("=" * 64)
        if failed:
            lines.append(f"  RESULT: FAIL — {len(failed)} mandatory check(s) failed.")
            lines.append("  Fix the items above before starting CareerPilot.")
            from .python_launcher import cli_hint
            lines.append(f"  Tip: {cli_hint('careerpilot.main doctor --fix')}")
            lines.append("       repairs folders/DB/Playwright browsers automatically.")
            lines.append("  Secrets (API keys) and portal logins always need you.")
        else:
            suffix = f" ({len(warns)} warning(s))" if warns else ""
            if warns:
                lines.append(f"  RESULT: PASS{suffix} — safe to run in dry_run.")
                lines.append("  Resolve WARNINGs (Telegram, portal logins, resumes)")
                lines.append("  before calling this a fully attended production box.")
            else:
                lines.append("  RESULT: PASS — production pre-flight clear.")
        lines.append("=" * 64 + "\n")
        print("\n".join(lines))


def run_doctor(config_path: str = "config/config.yaml",
               env_path: str = ".env", *, fix: bool = False,
               production: bool = False) -> bool:
    return Doctor(config_path, env_path, fix=fix,
                  production=production).run()

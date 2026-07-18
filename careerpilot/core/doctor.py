"""Startup validation -- the "doctor" routine.

Runs pre-flight checks and prints a clear PASS / WARNING / FAIL report plus a
**readiness score** (0–100). Mandatory failures cause a non-zero exit.

All checks are data-root aware (``CAREERPILOT_DATA_ROOT`` / sibling ``data/``).

Run via:
    py -m careerpilot.main doctor
    py -m careerpilot.main doctor --fix
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .bootstrap import ensure_scaffold
from .config import AppConfig, ConfigError, load_config
from .logging_setup import get_logger
from .paths import get_layout
from . import windows_env as wenv

logger = get_logger(__name__)

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_SYMBOL = {PASS: "[ OK ]", FAIL: "[FAIL]", WARN: "[WARN]", SKIP: "[SKIP]"}

# Weighted readiness: mandatory FAIL zeros that weight; WARN halves it.
_SCORE_WEIGHTS: dict[str, int] = {
    "Python": 5,
    "Virtual environment": 4,
    "Git": 2,
    "py launcher": 3,
    "Disk space": 5,
    "Data root": 6,
    "Configuration": 8,
    ".env file": 6,
    "AI provider keys": 8,
    "Gemini API keys": 8,
    "Required folders": 6,
    "Write permissions": 6,
    "Database": 7,
    "Resume files": 7,
    "Career Profiles": 5,
    "Candidate profile": 4,
    "Chrome profile dirs": 4,
    "LinkedIn login": 3,
    "Naukri login": 3,
    "Playwright package": 5,
    "Playwright Chromium": 5,
    "Dashboard port": 2,
    "Backups root": 3,
    "Logs dir": 2,
    "Reports dir": 2,
    "Cache dir": 2,
    "Certificates (optional)": 1,
    "Photo (optional)": 1,
    "Scheduler config": 2,
    "Startup task": 3,
}


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

    def __init__(self, config_path: str | None = None,
                 env_path: str | None = None, *, fix: bool = False,
                 production: bool = False):
        self.layout = get_layout()
        # Resolve defaults against the data root (not cwd).
        if config_path is None:
            if self.layout.config_yaml.exists():
                self.config_path = str(self.layout.config_yaml)
            elif (self.layout.app_root / "config" / "config.yaml").exists():
                self.config_path = str(
                    self.layout.app_root / "config" / "config.yaml")
            else:
                self.config_path = str(self.layout.config_yaml)
        else:
            self.config_path = config_path
        if env_path is None:
            if self.layout.env_file.exists():
                self.env_path = str(self.layout.env_file)
            elif (self.layout.app_root / ".env").exists():
                self.env_path = str(self.layout.app_root / ".env")
            else:
                self.env_path = str(self.layout.env_file)
        else:
            self.env_path = env_path
        self.fix = fix
        self.production = production
        self.results: list[CheckResult] = []
        self.fixes: list[FixAction] = []
        self.config: AppConfig | None = None
        self.readiness_score: int = 0

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
        self._check_data_root()

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
            self._check_candidate()
            self._check_optional_assets()
            self._check_browser_profiles()
            self._check_system_browser()
            self._check_port()
            self._check_maintenance_config()
            self._check_scheduler()
            self._check_backups_logs_cache()
        else:
            self._check_env_file_raw()

        self._check_playwright()
        self._check_browser_binary()
        self._check_startup_task()
        self.readiness_score = self._compute_readiness()
        self._print_report()
        return not any(r.status == FAIL and r.mandatory for r in self.results)

    # ---- fix mode --------------------------------------------------------

    def _apply_safe_fixes(self) -> None:
        """Repair only safe, non-secret issues. Idempotent."""
        print("Doctor --fix: applying safe repairs...\n")
        print(f"  data root = {self.layout.data_root}")
        print(f"  app root  = {self.layout.app_root}")
        print(f"  backups   = {self.layout.backups_root}\n")

        try:
            actions = ensure_scaffold(self.config_path, prefer_production=self.production,
                                      env_path=self.env_path)
            for a in actions:
                self.fixes.append(FixAction(a, True))
        except Exception as exc:  # noqa: BLE001
            self.fixes.append(FixAction("ensure_scaffold", False, str(exc)))

        if self.production:
            self._maybe_copy_production_config()

        # Extra legacy Chrome profile dirs when still using profiles_browser.
        for portal in ("linkedin", "naukri"):
            for base in (self.layout.browser_dir,
                         self.layout.data_root / "profiles_browser"):
                d = base / portal
                if not d.exists():
                    try:
                        d.mkdir(parents=True, exist_ok=True)
                        self.fixes.append(FixAction(
                            f"created Chrome profile dir {d}/", True))
                    except OSError as exc:
                        self.fixes.append(FixAction(
                            f"create {d}/", False, str(exc)))

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
        target = Path(self.config_path)
        prod = self.layout.app_root / "config.production.example.yaml"
        if target.exists() or not prod.exists():
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(prod, target)
            text = target.read_text(encoding="utf-8")
            text2 = text.replace("profiles_path: profiles_browser",
                                 "profiles_path: browser")
            if text2 != text:
                target.write_text(text2, encoding="utf-8")
            self.fixes.append(FixAction(
                f"created {target} from config.production.example.yaml", True))
        except OSError as exc:
            self.fixes.append(FixAction("copy production config", False, str(exc)))

    # ---- checks ----------------------------------------------------------

    def _add(self, name: str, status: str, message: str = "",
             mandatory: bool = True, fixed: bool = False) -> None:
        self.results.append(CheckResult(name, status, message, mandatory, fixed))

    def _check_data_root(self) -> None:
        layout = self.layout
        mode = ("production sibling" if layout.data_root != layout.app_root
                else "legacy (data inside app/repo)")
        env_hint = ""
        if os.getenv("CAREERPILOT_DATA_ROOT"):
            env_hint = " via CAREERPILOT_DATA_ROOT"
        elif os.getenv("CAREERPILOT_HOME"):
            env_hint = " via CAREERPILOT_HOME"
        self._add("Data root", PASS,
                  f"{layout.data_root} ({mode}{env_hint})", mandatory=False)
        # Writable data root is mandatory for production.
        ok, msg = wenv.path_writable(str(layout.data_root))
        if not ok:
            self._add("Data root writable", FAIL, msg)
        else:
            self._add("Data root writable", PASS, "writable")

    def _check_host_python(self) -> None:
        ok, msg = wenv.python_version_ok()
        self._add("Python", PASS if ok else FAIL, msg)

    def _check_py_launcher(self) -> None:
        if not wenv.is_windows():
            self._add("py launcher", SKIP, "non-Windows host", mandatory=False)
            return
        ok, msg = wenv.py_launcher_available()
        self._add("py launcher", PASS if ok else WARN, msg, mandatory=False)
        bare = shutil.which("python")
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
        ok, msg = wenv.venv_active_or_present(self.layout.app_root)
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
        target = self.layout.data_root
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            target = self.layout.data_root.parent if self.layout.data_root.parent.exists() else Path(".")
        ok, msg = wenv.disk_free_gb(str(target))
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
                      f"{self.env_path} not found (copy .env.example to data/.env "
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
            "logs": c.log_path,
            "screenshots": c.screenshot_path,
            "reports": c.report_path,
            "db_backups": c.backup_path,
            "browser": c.browser_profiles_path,
            "cache": str(self.layout.cache_dir),
            "documents": c.documents_dir,
            "debug": getattr(c.debug, "evidence_dir", str(self.layout.debug_dir)),
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
        targets = [
            self.config.log_path,
            self.config.report_path,
            str(Path(self.config.database_path).parent),
            str(self.layout.backups_root),
            str(self.layout.temp_dir),
        ]
        bad = []
        for t in targets:
            if not t:
                continue
            try:
                Path(t).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            ok, msg = wenv.path_writable(t)
            if not ok:
                bad.append(msg)
        if bad:
            self._add("Write permissions", FAIL, "; ".join(bad))
        else:
            self._add("Write permissions", PASS,
                      "logs/reports/database/backups/temp writable")

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

    def _check_candidate(self) -> None:
        assert self.config
        c = self.config.candidate
        name = (getattr(c, "full_name", None) or "").strip()
        email = (getattr(c, "email", None) or "").strip()
        if not name or name.lower() in ("your name", "changeme"):
            self._add("Candidate profile", WARN,
                      "candidate.full_name still looks like a placeholder — "
                      "edit config/config.yaml",
                      mandatory=False)
        elif not email or "your_email" in email.lower():
            self._add("Candidate profile", WARN,
                      "candidate.email still looks like a placeholder",
                      mandatory=False)
        else:
            self._add("Candidate profile", PASS,
                      f"{name} <{email}>", mandatory=False)

    def _check_optional_assets(self) -> None:
        """Photo / certificates are user assets — optional, not consumed by apply."""
        certs = self.layout.certificates_dir
        if certs.exists() and any(certs.iterdir()):
            self._add("Certificates (optional)", PASS,
                      f"files under {certs}", mandatory=False)
        else:
            self._add("Certificates (optional)", SKIP,
                      f"empty {certs} (optional — not used by apply today)",
                      mandatory=False)

        # Look for a headshot next to documents or under profiles.
        photo_names = ("photo.jpg", "photo.jpeg", "photo.png",
                       "headshot.jpg", "headshot.png")
        found = None
        for base in (self.layout.documents_dir, self.layout.profiles_dir):
            for n in photo_names:
                p = base / n
                if p.exists():
                    found = p
                    break
            if found:
                break
            # Also scan profile folders one level deep
            if base == self.layout.profiles_dir and base.exists():
                for child in base.iterdir():
                    if not child.is_dir():
                        continue
                    for n in photo_names:
                        p = child / n
                        if p.exists():
                            found = p
                            break
                    if found:
                        break
        if found:
            self._add("Photo (optional)", PASS, str(found), mandatory=False)
        else:
            self._add("Photo (optional)", SKIP,
                      "no photo.jpg/headshot under documents/ or profiles/ "
                      "(optional — not used by apply today)",
                      mandatory=False)

    def _check_browser_profiles(self) -> None:
        assert self.config
        path = Path(self.config.browser_profiles_path)
        linkedin = path / "linkedin"
        naukri = path / "naukri"

        def _looks_used(d: Path) -> bool:
            if not d.exists():
                return False
            if (d / "Default").exists() or (d / "Local State").exists():
                return True
            try:
                return any(d.iterdir())
            except OSError:
                return False

        has_any = path.exists() and any(path.iterdir()) if path.exists() else False
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

    def _check_scheduler(self) -> None:
        assert self.config
        hrs = int(self.config.scan_interval_hours or 0)
        if hrs <= 0:
            self._add("Scheduler config", WARN,
                      "scan_interval_hours <= 0", mandatory=False)
        else:
            self._add("Scheduler config", PASS,
                      f"scan every {hrs}h, daily summary @{self.config.daily_summary_hour}:00",
                      mandatory=False)

    def _check_backups_logs_cache(self) -> None:
        layout = self.layout
        try:
            layout.backups_root.mkdir(parents=True, exist_ok=True)
            self._add("Backups root", PASS, str(layout.backups_root),
                      mandatory=False)
        except OSError as exc:
            self._add("Backups root", FAIL, str(exc))

        for label, path in (("Logs dir", layout.logs_dir),
                            ("Reports dir", layout.reports_dir),
                            ("Cache dir", layout.cache_dir)):
            try:
                path.mkdir(parents=True, exist_ok=True)
                self._add(label, PASS, str(path), mandatory=False)
            except OSError as exc:
                self._add(label, FAIL, str(exc))

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

    def _check_startup_task(self) -> None:
        if not wenv.is_windows():
            self._add("Startup task", SKIP, "non-Windows", mandatory=False)
            return
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "CareerPilot"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                self._add("Startup task", PASS,
                          "Task Scheduler 'CareerPilot' registered",
                          mandatory=False)
            else:
                self._add("Startup task", WARN,
                          "not registered — run scripts\\Register-CareerPilotStartup.ps1",
                          mandatory=False)
        except Exception as exc:  # noqa: BLE001
            self._add("Startup task", SKIP, str(exc), mandatory=False)

    def _compute_readiness(self) -> int:
        """0–100 score from weighted check results."""
        by_name: dict[str, CheckResult] = {}
        for r in self.results:
            # Keep worst status per name
            prev = by_name.get(r.name)
            if prev is None:
                by_name[r.name] = r
                continue
            order = {FAIL: 0, WARN: 1, SKIP: 2, PASS: 3}
            if order.get(r.status, 9) < order.get(prev.status, 9):
                by_name[r.name] = r

        total = earned = 0
        for name, weight in _SCORE_WEIGHTS.items():
            total += weight
            r = by_name.get(name)
            if r is None:
                earned += weight * 0.5  # unknown → half credit
                continue
            if r.status == PASS:
                earned += weight
            elif r.status == WARN:
                earned += weight * 0.5
            elif r.status == SKIP:
                earned += weight * 0.75
            # FAIL → 0
        if total <= 0:
            return 0
        return int(round(100 * earned / total))

    # ---- report ----------------------------------------------------------

    def _print_report(self) -> None:
        layout = self.layout
        lines = [
            "",
            "=" * 64,
            "  CareerPilot Doctor — production pre-flight",
            "=" * 64,
            f"  data root : {layout.data_root}",
            f"  app root  : {layout.app_root}",
            f"  backups   : {layout.backups_root}",
            "-" * 64,
        ]
        for r in self.results:
            tag = "" if r.mandatory else "  (optional)"
            lines.append(f" {_SYMBOL[r.status]}  {r.name}{tag}")
            if r.message:
                lines.append(f"          {r.message}")
        failed = [r for r in self.results if r.status == FAIL and r.mandatory]
        warns = [r for r in self.results if r.status == WARN]
        score = self.readiness_score
        lines.append("=" * 64)
        lines.append(f"  READINESS SCORE: {score}/100")
        if score >= 90:
            lines.append("  Band: PRODUCTION-READY (resolve remaining WARNs for 24x7)")
        elif score >= 70:
            lines.append("  Band: DRY-RUN READY (fill keys/resumes/logins before live)")
        elif score >= 40:
            lines.append("  Band: SETUP INCOMPLETE")
        else:
            lines.append("  Band: NOT READY")
        lines.append("-" * 64)
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


def run_doctor(config_path: str | None = None,
               env_path: str | None = None, *, fix: bool = False,
               production: bool = False) -> bool:
    return Doctor(config_path, env_path, fix=fix,
                  production=production).run()

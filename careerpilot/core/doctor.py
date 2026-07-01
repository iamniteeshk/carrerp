"""Startup validation -- the "doctor" routine.

Runs a series of pre-flight checks and prints a clear pass/fail report. Mandatory
failures cause a non-zero exit (fail fast); optional components only warn. This
is what stands between a misconfigured machine and a confusing mid-run crash.

Run via:  python -m careerpilot.main doctor
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig, ConfigError, load_config
from .logging_setup import get_logger

logger = get_logger(__name__)

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_SYMBOL = {PASS: "[ OK ]", FAIL: "[FAIL]", WARN: "[WARN]", SKIP: "[SKIP]"}


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    mandatory: bool = True


class Doctor:
    """Collects and reports pre-flight checks."""

    def __init__(self, config_path: str = "config/config.yaml",
                 env_path: str = ".env"):
        self.config_path = config_path
        self.env_path = env_path
        self.results: list[CheckResult] = []
        self.config: AppConfig | None = None

    def run(self) -> bool:
        """Run all checks. Returns True if no mandatory check failed."""
        self._check_schema()
        self._check_config()
        # Subsequent checks need a valid config; if it failed, stop early.
        if self.config is not None:
            self._check_env_file()
            self._check_gemini_keys()
            self._check_deepseek()
            self._check_telegram()
            self._check_folders()
            self._check_database()
            self._check_profiles()
            self._check_browser_profiles()
        self._check_playwright()
        self._check_browser_binary()
        self._print_report()
        return not any(r.status == FAIL and r.mandatory for r in self.results)

    # ---- checks ----------------------------------------------------------

    def _add(self, name: str, status: str, message: str = "",
             mandatory: bool = True) -> None:
        self.results.append(CheckResult(name, status, message, mandatory))

    def _check_schema(self) -> None:
        """Rich human-readable schema validation (config/candidate/profiles)."""
        from .validation import validate_all
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
                      f"{self.env_path} not found (copy .env.example to .env)")

    def _check_gemini_keys(self) -> None:
        assert self.config
        n = len(self.config.ai.gemini_keys)
        if n > 0:
            self._add("Gemini API keys", PASS, f"{n} key(s) configured")
        elif self.config.ai.deepseek_key:
            self._add("Gemini API keys", WARN,
                      "no Gemini keys; relying on DeepSeek fallback", mandatory=False)
        else:
            self._add("Gemini API keys", FAIL, "no Gemini keys and no DeepSeek key")

    def _check_deepseek(self) -> None:
        assert self.config
        if self.config.ai.deepseek_key:
            self._add("DeepSeek key (optional)", PASS, "configured", mandatory=False)
        else:
            self._add("DeepSeek key (optional)", SKIP, "not set", mandatory=False)

    def _check_telegram(self) -> None:
        assert self.config
        token = self.config.telegram_token
        chat = self.config.telegram_chat_id
        if token and chat:
            self._add("Telegram (optional)", PASS, "token + chat id set",
                      mandatory=False)
        elif token or chat:
            self._add("Telegram (optional)", WARN,
                      "only one of token/chat_id set; notifications disabled",
                      mandatory=False)
        else:
            self._add("Telegram (optional)", SKIP, "not configured",
                      mandatory=False)

    def _check_folders(self) -> None:
        assert self.config
        c = self.config
        folders = {
            "logs": c.log_path, "screenshots": c.screenshot_path,
            "reports": c.report_path, "backups": c.backup_path,
            "profiles": c.browser_profiles_path,
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

    def _check_database(self) -> None:
        assert self.config
        try:
            from ..db.database import Database
            db = Database(self.config.database_path)
            db.initialize()
            db.close()
            self._add("Database", PASS, f"schema ready at {self.config.database_path}")
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
            self._add("Career Profiles", PASS,
                      f"{len(names)} profile(s): {', '.join(names)}")
        else:
            default = self.config.default_career_profile
            default_ok = default not in missing
            self._add("Career Profiles", WARN if default_ok else FAIL,
                      f"resume missing for: {', '.join(missing)}"
                      + ("" if default_ok else "  (DEFAULT profile resume missing!)"),
                      mandatory=not default_ok)

    def _check_browser_profiles(self) -> None:
        assert self.config
        path = Path(self.config.browser_profiles_path)
        if path.exists() and any(path.iterdir()):
            self._add("Browser profiles", PASS, "saved session(s) found",
                      mandatory=False)
        else:
            self._add("Browser profiles", WARN,
                      "no saved login yet; first run will need manual login",
                      mandatory=False)

    def _check_playwright(self) -> None:
        import importlib.util
        if importlib.util.find_spec("playwright") is not None:
            self._add("Playwright package", PASS, "importable")
        else:
            self._add("Playwright package", FAIL,
                      "not installed (pip install playwright)")

    def _check_browser_binary(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:  # noqa: BLE001
            self._add("Chromium browser", SKIP, "Playwright not installed",
                      mandatory=False)
            return
        try:
            with sync_playwright() as p:
                exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                self._add("Chromium browser", PASS, "installed")
            else:
                self._add("Chromium browser", FAIL,
                          "not found (run: playwright install chromium)")
        except Exception as exc:  # noqa: BLE001
            self._add("Chromium browser", FAIL,
                      f"unavailable: {exc} (run: playwright install chromium)")

    # ---- report ----------------------------------------------------------

    def _print_report(self) -> None:
        lines = ["", "=" * 60, "  CareerPilot Doctor -- pre-flight checks", "=" * 60]
        for r in self.results:
            tag = "" if r.mandatory else "  (optional)"
            lines.append(f" {_SYMBOL[r.status]}  {r.name}{tag}")
            if r.message:
                lines.append(f"          {r.message}")
        failed = [r for r in self.results if r.status == FAIL and r.mandatory]
        lines.append("=" * 60)
        if failed:
            lines.append(f"  RESULT: FAIL -- {len(failed)} mandatory check(s) failed.")
            lines.append("  Fix the items above before starting CareerPilot.")
        else:
            warns = [r for r in self.results if r.status == WARN]
            suffix = f" ({len(warns)} warning(s))" if warns else ""
            lines.append(f"  RESULT: PASS{suffix} -- ready to run.")
        lines.append("=" * 60 + "\n")
        print("\n".join(lines))


def run_doctor(config_path: str = "config/config.yaml",
               env_path: str = ".env") -> bool:
    return Doctor(config_path, env_path).run()

"""Configuration schema validation.

Validates config.yaml, candidate.yaml, and every Career Profile before the app
starts, collecting *all* problems and reporting them in human-readable form
(with source line numbers where the offending key exists). Mandatory problems
cause a fail-fast; missing optional pieces are warnings.

Example messages:
    candidate.phone is missing (candidate.yaml)
    profiles/Infrastructure/resume.pdf not found
    config.apply.min_apply_score must be 0-100 (config.yaml line 42)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .yaml_utils import line_of, load_yaml_with_lines


@dataclass
class Issue:
    message: str
    mandatory: bool = True


class ValidationReport:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, message: str) -> None:
        self.issues.append(Issue(message, mandatory=True))

    def warn(self, message: str) -> None:
        self.issues.append(Issue(message, mandatory=False))

    @property
    def ok(self) -> bool:
        return not any(i.mandatory for i in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.mandatory]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if not i.mandatory]


# Required candidate fields (the rest are optional / free-form extras).
_REQUIRED_CANDIDATE = ["full_name", "email", "phone"]

# Placeholder tokens that indicate the example was copied but not filled in.
_PLACEHOLDERS = {"", "your_email", "your_profile", "+91-xxxxxxxxxx",
                 "changeme", "todo", "tbd"}


def validate_all(config_path: str | Path = "config/config.yaml",
                 env_path: str | Path = ".env") -> ValidationReport:
    """Run every validation. Returns a report; caller decides to fail fast."""
    report = ValidationReport()

    cfg = _validate_config(config_path, report)
    if cfg is None:
        return report  # cannot proceed without a parseable config

    fname = Path(config_path).name
    if isinstance(cfg.get("candidate"), dict):
        _validate_candidate_section(cfg["candidate"], fname, report)
    else:
        report.error(f"config.candidate section is missing ({fname})")

    profiles_cfg = cfg.get("profiles", {}) or {}
    profiles_dir = profiles_cfg.get("dir", "profiles")
    default_profile = profiles_cfg.get("default", "")
    _validate_profiles(profiles_dir, default_profile, report)

    _validate_folders(cfg, report)
    _validate_env(cfg, env_path, report)
    return report


def _validate_config(path: str | Path, report: ValidationReport) -> dict | None:
    path = Path(path)
    if not path.exists():
        report.error(f"config file not found: {path}")
        return None
    try:
        cfg = load_yaml_with_lines(path)
    except Exception as exc:  # noqa: BLE001
        report.error(f"config.yaml could not be parsed: {exc}")
        return None

    fname = path.name
    # Required sections (accept either the new layout or the legacy one).
    if "database" not in cfg:
        report.error(f"config.database is missing ({fname})")
    if "dashboard" not in cfg:
        report.error(f"config.dashboard is missing ({fname})")
    if "ai" not in cfg:
        report.error(f"config.ai is missing ({fname})")
    if "apply" not in cfg:
        report.error(f"config.apply is missing ({fname})")
    # Career profiles: new 'profiles.default' or legacy 'default_career_profile'.
    profiles_cfg = cfg.get("profiles", {}) or {}
    if not profiles_cfg.get("default"):
        report.error(f"config.profiles.default is missing ({fname})")

    apply_cfg = cfg.get("apply", {}) or {}
    score = apply_cfg.get("min_apply_score")
    if score is not None and not (0 <= float(score) <= 100):
        report.error(_loc("config.apply.min_apply_score must be 0-100",
                          fname, apply_cfg, "min_apply_score"))
    mode = apply_cfg.get("mode", "dry_run")
    if mode not in ("dry_run", "live"):
        report.error(_loc("config.apply.mode must be 'dry_run' or 'live'",
                          fname, apply_cfg, "mode"))

    ct = profiles_cfg.get("confidence_threshold")
    if ct is not None and not (0 <= float(ct) <= 100):
        report.error(_loc("config.profiles.confidence_threshold must be 0-100",
                          fname, profiles_cfg, "confidence_threshold"))

    # Browser engine sanity (config-driven browser).
    browser = cfg.get("browser", {}) or {}
    engine = str(browser.get("engine", "chromium")).lower()
    if engine not in ("chromium", "firefox", "webkit"):
        report.error(_loc("config.browser.engine must be chromium/firefox/webkit",
                          fname, browser, "engine"))
    return cfg


def _validate_candidate_section(data: dict, fname: str,
                                report: ValidationReport) -> None:
    """Validate the inline candidate: section (line numbers from config.yaml)."""
    for key in _REQUIRED_CANDIDATE:
        value = data.get(key)
        if value is None:
            report.error(f"candidate.{key} is missing ({fname})")
        elif str(value).strip().lower() in _PLACEHOLDERS:
            report.error(_loc(f"candidate.{key} still has a placeholder value",
                              fname, data, key))




def _validate_profiles(profiles_dir: str | Path, default_profile: str,
                       report: ValidationReport) -> None:
    from .career_profile import (CareerProfileEngine, CareerProfileError,
                                  PROFILE_FILE)
    profiles_dir = Path(profiles_dir)
    if not profiles_dir.exists():
        report.error(f"profiles directory not found: {profiles_dir}")
        return

    folders = [d for d in profiles_dir.iterdir()
               if d.is_dir() and not d.name.startswith(".")
               and (d / PROFILE_FILE).exists()]
    if not folders:
        report.error(f"no career profiles found under {profiles_dir} "
                     f"(each needs a {PROFILE_FILE})")
        return

    try:
        engine = CareerProfileEngine(profiles_dir, default_profile, 0)
        engine.load()
    except CareerProfileError as exc:
        report.error(str(exc))
        return

    # Every profile must have an existing resume file.
    for name, profile in engine.profiles.items():
        if profile.resume_path is None or not profile.resume_path.exists():
            report.error(f"{profile.resume_path or '(no resume configured)'} "
                         f"not found (profile '{name}')")
        if profile.cover_letter_path is not None \
                and not profile.cover_letter_path.exists():
            report.warn(f"cover letter missing for profile '{name}': "
                        f"{profile.cover_letter_path}")
        for doc_type, doc_path in profile.documents.items():
            if doc_path is not None and not doc_path.exists():
                report.warn(f"document '{doc_type}' missing for profile "
                            f"'{name}': {doc_path}")

    if default_profile and default_profile not in engine.profiles:
        report.error(f"default_career_profile '{default_profile}' is not among "
                     f"the loaded profiles: {sorted(engine.profiles)}")


def _validate_folders(cfg: dict, report: ValidationReport) -> None:
    logging_cfg = cfg.get("logging", {}) or {}
    browser = cfg.get("browser", {}) or {}
    application = cfg.get("application", {}) or {}
    db = cfg.get("database", {}) or {}
    folders = {
        "logs": logging_cfg.get("dir"),
        "screenshots": browser.get("screenshots_path"),
        "reports": application.get("reports_dir"),
        "backups": db.get("backups_path"),
    }
    for name, path in folders.items():
        if not path:
            continue
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report.error(f"cannot create '{name}' folder ({path}): {exc}")


def _validate_env(cfg: dict, env_path: str | Path, report: ValidationReport) -> None:
    if not Path(env_path).exists():
        report.warn(f".env not found at {env_path} (copy .env.example to .env)")
    ai = cfg.get("ai", {}) or {}
    gemini_vars = ai.get("gemini_key_env_vars", []) or []
    deepseek_var = ai.get("deepseek_key_env_var", "DEEPSEEK_API_KEY")
    # Load .env into the environment for the check, without overwriting set vars.
    if Path(env_path).exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    has_gemini = any(os.getenv(v, "").strip() for v in gemini_vars)
    has_deepseek = bool(os.getenv(deepseek_var, "").strip())
    if not has_gemini and not has_deepseek:
        report.error("no AI provider key set in environment "
                     "(set a Gemini key or DeepSeek key in .env)")


def _loc(message: str, fname: str, mapping: dict, key: str) -> str:
    line = line_of(mapping, key)
    return f"{message} ({fname} line {line})" if line else f"{message} ({fname})"

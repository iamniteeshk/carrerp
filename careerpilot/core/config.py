"""Configuration loading for CareerPilot V2.

Single-file design: everything user-specific lives in one ``config.yaml`` with
clearly separated sections (application, scheduler, candidate, ai, browser,
dashboard, database, telegram, profiles, rules, apply, logging, documents,
email). Secrets live only in ``.env``.

``load_config`` raises ``ConfigError`` for programmatic safety; richer
human-readable validation lives in ``validation.py`` (run by the doctor).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..browser.session import BrowserConfig
from ..browser.visual_debug import DebugConfig, DEFAULT_COLORS
from ..browser.humanize import HumanConfig
from .candidate import Candidate, candidate_from_dict
from .career_profile import CareerProfileEngine
from .yaml_utils import load_yaml, strip_line_meta


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass
class AIConfig:
    gemini_keys: list[str]
    gemini_model: str
    deepseek_key: str
    deepseek_model: str
    request_timeout: int
    max_retries: int
    min_apply_score: float
    active_provider: str = ""
    providers: list = field(default_factory=list)  # list[ai.factory.ProviderSpec]


@dataclass
class RuleConfig:
    minimum_salary: int
    salary_currency: str
    minimum_experience: int
    accepted_employment_types: list[str]
    rejected_shifts: list[str]
    preferred_locations: list[str]
    accepted_titles: list[str]
    rejected_titles: list[str]
    blacklist_companies: list[str]
    required_keywords: list[str]
    nice_to_have_keywords: list[str]
    # Minimum AI match score (0-100) for a job to be MATCHED. A scored job below
    # this becomes REJECTED instead of appearing in MatchedJobs -- so the Rule
    # Engine and the AI agree on the final decision. 0 disables the gate.
    minimum_match_score: float = 0.0
    # Extra hard off-domain title terms (merged with the built-in denylist). A
    # title containing one of these is rejected before the AI is called, UNLESS
    # the title also carries one of the candidate's own domain keywords (then it
    # is borderline and the AI decides).
    excluded_title_terms: list[str] = field(default_factory=list)
    # Focused list of phrases to SEARCH on each portal (point 6 priority titles).
    # Distinct from accepted_titles, which is the broader "is this a relevant
    # role" allowlist used for matching. If empty, search falls back to
    # accepted_titles (backward compatible).
    search_keywords: list[str] = field(default_factory=list)
    # Quality-first search: when false, skip the nationwide keyword sweep.
    search_nationwide: bool = False
    # When false, skip the logged-in recommended-jobs feed (fewer duplicates).
    search_include_recommended: bool = False
    # When true, visit Easy Apply / apply-friendly feeds BEFORE keyword searches.
    search_include_easy_apply_feed: bool = True
    # When true, visit the portal's general "all jobs" feed before categories.
    search_include_all_feed: bool = True
    # When set, ONLY these cities are searched (overrides profile location union).
    search_locations: list[str] = field(default_factory=list)


@dataclass
class ApplyConfig:
    mode: str
    first_run_confirmations: int
    max_applications_per_day: int
    delay_between_applications_seconds: int
    retry_limit: int
    easy_apply_only: bool
    # Production safety: always stop at the final confirmation page and require
    # an explicit human approval before Submit. After sufficient live validation
    # this can be set false; default True so we never accidentally submit.
    require_final_confirmation: bool = True
    # When True, unknown location cannot proceed to apply.
    require_preferred_location: bool = False


@dataclass
class RetentionSettings:
    """Long-running retention limits (days / max items)."""
    cache_days: int = 30
    report_days: int = 60
    screenshot_days: int = 14
    evidence_days: int = 14
    backup_days: int = 30
    human_interaction_days: int = 14
    session_history_max: int = 500
    good_jobs_max: int = 1000
    vacuum_db: bool = True
    maintenance_hour: int = 3  # local hour for daily cleanup

@dataclass
class EmailConfig:
    """Reserved for a future Email Manager. Not yet consumed by any module."""
    enabled: bool = False
    address: str = ""
    imap_host: str = ""
    password: str = ""


@dataclass
class AppConfig:
    app_name: str
    scan_interval_hours: int
    daily_summary_hour: int
    database_path: str
    backup_path: str
    screenshot_path: str
    log_path: str
    log_level: str
    report_path: str
    dashboard_host: str
    dashboard_port: int
    dashboard_refresh_seconds: int
    profiles_dir: str
    default_career_profile: str
    profile_confidence_threshold: float
    documents_dir: str
    browser: BrowserConfig
    ai: AIConfig
    rules: RuleConfig
    apply: ApplyConfig
    candidate: Candidate
    profile_engine: CareerProfileEngine
    email: EmailConfig
    debug: "DebugConfig" = None  # type: ignore
    portals_parse: dict = field(default_factory=dict)
    human: "HumanConfig" = None  # type: ignore
    telegram_token: str = ""
    telegram_chat_id: str = ""
    source_path: str = ""    # absolute path of the loaded config file
    retention: RetentionSettings = field(default_factory=RetentionSettings)
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # Convenience accessors kept for the rest of the codebase.
    @property
    def profiles(self):
        return self.profile_engine.profiles

    @property
    def headless(self) -> bool:
        return self.browser.headless

    @property
    def browser_profiles_path(self) -> str:
        return self.browser.profiles_path




def load_config(config_path: str | Path = "config/config.yaml",
                env_path: str | Path = ".env") -> AppConfig:
    """Load and validate configuration. Raises ConfigError on any problem."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if Path(env_path).exists():
        load_dotenv(env_path)

    raw = strip_line_meta(load_yaml(config_path))

    # Sections (new layout). Each falls back to old top-level keys below.
    application = raw.get("application", {}) or {}
    scheduler = raw.get("scheduler", {}) or {}
    db = raw.get("database", {}) or {}
    dash = raw.get("dashboard", {}) or {}
    browser = raw.get("browser", {}) or {}
    ai = raw.get("ai", {}) or {}
    rules = raw.get("rules", {}) or {}
    apply_cfg = raw.get("apply", {}) or {}
    profiles_cfg = raw.get("profiles", {}) or {}
    logging_cfg = raw.get("logging", {}) or {}
    documents_cfg = raw.get("documents", {}) or {}
    telegram_cfg = raw.get("telegram", {}) or {}
    email_cfg = raw.get("email", {}) or {}

    # ---- candidate (single modern schema: inline section, required) ----
    if not isinstance(raw.get("candidate"), dict):
        raise ConfigError(
            "config.yaml must contain a 'candidate:' section with your details.")
    candidate = candidate_from_dict(raw["candidate"])

    # ---- AI ----
    # Note: a *missing* AI key is NOT a structural config error -- it is a
    # readiness problem surfaced by validation/doctor. Letting the config object
    # build means the doctor reaches every check (incl. database init) and can
    # report a clear, actionable message instead of aborting early.
    gemini_keys = _resolve_env_list(ai.get("gemini_key_env_vars", []))
    deepseek_key = os.getenv(ai.get("deepseek_key_env_var", "DEEPSEEK_API_KEY"), "")
    if "min_apply_score" not in apply_cfg:
        raise ConfigError("Missing required config key 'min_apply_score' in apply")
    active_provider, provider_specs = _build_provider_specs(
        ai, gemini_keys, deepseek_key)
    ai_cfg = AIConfig(
        gemini_keys=gemini_keys,
        gemini_model=ai.get("gemini_model", ""),
        deepseek_key=deepseek_key,
        deepseek_model=ai.get("deepseek_model", "deepseek-chat"),
        request_timeout=int(ai.get("request_timeout_seconds", 30)),
        max_retries=int(ai.get("max_retries", 2)),
        min_apply_score=float(apply_cfg["min_apply_score"]),
        active_provider=active_provider,
        providers=provider_specs,
    )

    # ---- career profiles (modern 'profiles:' section only) ----
    profiles_dir = profiles_cfg.get("dir", "profiles")
    default_profile = profiles_cfg.get("default")
    if not default_profile:
        raise ConfigError("config.yaml must set 'profiles.default'")
    confidence_threshold = float(profiles_cfg.get("confidence_threshold", 70))
    engine = CareerProfileEngine(profiles_dir, default_profile, confidence_threshold)
    try:
        engine.load()
    except Exception as exc:  # noqa: BLE001 - surface as ConfigError
        raise ConfigError(str(exc)) from exc
    if default_profile not in engine.profiles:
        raise ConfigError(
            f"default career profile '{default_profile}' not among loaded "
            f"profiles: {sorted(engine.profiles)}")

    # ---- rules: keyword/location filters are the UNION across profiles ----
    union_keywords = engine.all_required_keywords()
    union_locations = engine.all_preferred_locations()
    extra_keywords = rules.get("extra_required_keywords", []) or []
    extra_locations = rules.get("extra_preferred_locations", []) or []
    search_locs = rules.get("search_locations", []) or []
    if search_locs:
        search_locations = _dedupe(search_locs)
    else:
        search_locations = _dedupe(union_locations + extra_locations)
    rule_cfg = RuleConfig(
        minimum_salary=int((rules.get("minimum_salary", {}) or {}).get("amount", 0)),
        salary_currency=(rules.get("minimum_salary", {}) or {}).get("currency", "INR"),
        minimum_experience=int(rules.get("minimum_experience", 15)),
        accepted_employment_types=rules.get("accepted_employment_types", ["Full Time"]),
        rejected_shifts=rules.get("rejected_shifts", []) or [],
        preferred_locations=search_locations,
        accepted_titles=rules.get("accepted_titles", []),
        rejected_titles=rules.get("rejected_titles", []),
        blacklist_companies=rules.get("blacklist_companies", []),
        required_keywords=_dedupe(union_keywords + extra_keywords),
        nice_to_have_keywords=rules.get("nice_to_have_keywords", []),
        minimum_match_score=float(rules.get("minimum_match_score", 0) or 0),
        excluded_title_terms=rules.get("excluded_title_terms", []) or [],
        search_keywords=rules.get("search_keywords", []) or [],
        search_nationwide=bool(rules.get("search_nationwide", False)),
        search_include_recommended=bool(rules.get("search_include_recommended",
                                                   False)),
        search_include_easy_apply_feed=bool(
            rules.get("search_include_easy_apply_feed", True)),
        search_include_all_feed=bool(rules.get("search_include_all_feed", True)),
        search_locations=search_locs,
    )

    apply_obj = ApplyConfig(
        mode=apply_cfg.get("mode", "dry_run"),
        first_run_confirmations=int(apply_cfg.get("first_run_confirmations", 3)),
        max_applications_per_day=int(apply_cfg.get("max_applications_per_day", 10)),
        delay_between_applications_seconds=int(
            apply_cfg.get("delay_between_applications_seconds", 120)),
        retry_limit=int(apply_cfg.get("retry_limit", 2)),
        easy_apply_only=bool(apply_cfg.get("easy_apply_only", True)),
        require_final_confirmation=bool(
            apply_cfg.get("require_final_confirmation", True)),
        require_preferred_location=bool(
            apply_cfg.get("require_preferred_location", False)),
    )
    if apply_obj.mode not in ("dry_run", "live"):
        raise ConfigError(f"apply.mode must be 'dry_run' or 'live', got '{apply_obj.mode}'")

    # ---- retention / long-running maintenance ----
    maint_cfg = raw.get("maintenance", {}) or {}
    retention = RetentionSettings(
        cache_days=int(maint_cfg.get("cache_days", 30)),
        report_days=int(maint_cfg.get("report_days", 60)),
        screenshot_days=int(maint_cfg.get("screenshot_days", 14)),
        evidence_days=int(maint_cfg.get("evidence_days", 14)),
        backup_days=int(maint_cfg.get("backup_days", 30)),
        human_interaction_days=int(maint_cfg.get("human_interaction_days", 14)),
        session_history_max=int(maint_cfg.get("session_history_max", 500)),
        good_jobs_max=int(maint_cfg.get("good_jobs_max", 1000)),
        vacuum_db=bool(maint_cfg.get("vacuum_db", True)),
        maintenance_hour=int(maint_cfg.get("maintenance_hour", 3)),
    )

    # ---- browser (config-driven engine/channel/viewport) ----
    viewport = browser.get("viewport", {}) or {}
    browser_cfg = BrowserConfig(
        engine=browser.get("engine", "chromium"),
        channel=browser.get("channel", "msedge"),
        headless=bool(browser.get("headless", False)),
        viewport_width=int(viewport.get("width", 1366)),
        viewport_height=int(viewport.get("height", 900)),
        profiles_path=browser.get("profiles_path", "profiles_browser"),
        timeout_seconds=int(browser.get("timeout_seconds", 30)),
        networkidle_timeout_ms=int(browser.get("networkidle_timeout_ms", 8000)),
        render_settle_ms=int(browser.get("render_settle_ms", 800)),
        scroll_passes=int(browser.get("scroll_passes", 3)),
        open_jobs=bool(browser.get("open_jobs", True)),
    )

    # ---- paths (modern sections only) ----
    database_path = db.get("path", "database/careerpilot.db")
    backup_path = db.get("backups_path", "database/backups")
    screenshot_path = browser.get("screenshots_path", "screenshots")
    log_path = logging_cfg.get("dir", "logs")
    report_path = application.get("reports_dir", "reports")
    documents_dir = documents_cfg.get("dir", "documents")

    email = EmailConfig(
        enabled=bool(email_cfg.get("enabled", False)),
        address=email_cfg.get("address", ""),
        imap_host=email_cfg.get("imap_host", ""),
        password=os.getenv(email_cfg.get("password_env_var", "EMAIL_PASSWORD"), ""),
    )

    cfg = AppConfig(
        app_name=application.get("name", "CareerPilot"),
        scan_interval_hours=int(scheduler.get("scan_interval_hours", 4)),
        daily_summary_hour=int(scheduler.get("daily_summary_hour", 20)),
        database_path=database_path,
        backup_path=backup_path,
        screenshot_path=screenshot_path,
        log_path=log_path,
        log_level=str(logging_cfg.get("level", "INFO")).upper(),
        report_path=report_path,
        dashboard_host=dash.get("host", "127.0.0.1"),
        dashboard_port=int(dash.get("port", 5000)),
        dashboard_refresh_seconds=int(dash.get("refresh_seconds", 30)),
        profiles_dir=profiles_dir,
        default_career_profile=default_profile,
        profile_confidence_threshold=confidence_threshold,
        documents_dir=documents_dir,
        browser=browser_cfg,
        ai=ai_cfg,
        rules=rule_cfg,
        apply=apply_obj,
        candidate=candidate,
        profile_engine=engine,
        email=email,
        debug=_build_debug(raw.get("debug", {}) or {}),
        portals_parse=(raw.get("portals", {}) or {}),
        human=_build_human(raw.get("human", {}) or {}),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=(telegram_cfg.get("chat_id")
                          or os.getenv("TELEGRAM_CHAT_ID", "")),
        retention=retention,
        _raw=raw,
    )
    try:
        cfg.source_path = str(config_path.resolve())
    except Exception:  # noqa: BLE001
        cfg.source_path = str(config_path)
    _validate_semantics(cfg)
    return cfg


def _build_human(d: dict) -> HumanConfig:
    return HumanConfig(
        enabled=bool(d.get("enabled", False)),
        words_per_minute=int(d.get("words_per_minute", 350)),
        scroll_step_min_px=int(d.get("scroll_step_min_px", 250)),
        scroll_step_max_px=int(d.get("scroll_step_max_px", 650)),
        scroll_pause_min_ms=int(d.get("scroll_pause_min_ms", 250)),
        scroll_pause_max_ms=int(d.get("scroll_pause_max_ms", 900)),
        upward_correction_chance=float(d.get("upward_correction_chance", 0.15)),
        mouse_moves=bool(d.get("mouse_moves", True)),
        seed=d.get("seed"),
        break_chance=float(d.get("break_chance", 0.12)),
        highlight_chance=float(d.get("highlight_chance", 0.25)),
        keyboard_scroll_chance=float(d.get("keyboard_scroll_chance", 0.30)),
        wander_chance=float(d.get("wander_chance", 0.5)),
    )


def _resolve_env_list(env_var_names: list[str]) -> list[str]:
    """Resolve a list of env var names to their non-empty values."""
    return [v for name in env_var_names if (v := os.getenv(name, "").strip())]


def _build_provider_specs(ai: dict, gemini_keys: list, deepseek_key: str):
    """Return (active_provider, [ProviderSpec]). Supports the new provider-driven
    schema and falls back to the legacy gemini/deepseek keys for compatibility.
    No model names are hardcoded -- preferred_model is optional and discovery
    fills the rest."""
    from ..ai.factory import ProviderSpec

    providers_cfg = ai.get("providers")
    if providers_cfg:
        specs = []
        for name, p in providers_cfg.items():
            p = p or {}
            kind = p.get("kind") or ("gemini" if name.lower() == "gemini"
                                     else "openai")
            key_env = p.get("api_key_env", "")
            key_envs = p.get("api_key_envs", [])
            keys = (_resolve_env_list(key_envs)
                    or ([os.getenv(key_env, "")] if key_env else []))
            # A provider with NO key env configured is treated as keyless/local
            # (Ollama, LM Studio, vLLM) -- it is usable without an API key. An
            # explicit requires_auth in config always wins.
            key_configured = bool(key_env or key_envs)
            requires_auth = bool(p.get("requires_auth", key_configured))
            specs.append(ProviderSpec(
                name=name, kind=kind, enabled=bool(p.get("enabled", True)),
                api_keys=[k for k in keys if k], base_url=p.get("base_url", ""),
                discover_models=bool(p.get("discover_models", True)),
                preferred_model=p.get("preferred_model", ""),
                headers=p.get("headers", {}) or {},
                requires_auth=requires_auth,
                cache_ttl=int(p.get("model_cache_ttl_seconds", 300))))
        active = ai.get("active_provider", "") or (specs[0].name if specs else "")
        return active, specs

    # Legacy fallback: synthesize specs from the old gemini/deepseek config.
    specs = [
        ProviderSpec(name="gemini", kind="gemini",
                     enabled=bool(gemini_keys), api_keys=gemini_keys,
                     preferred_model=ai.get("gemini_model", ""),
                     discover_models=True),
        ProviderSpec(name="deepseek", kind="openai",
                     enabled=bool(deepseek_key), api_keys=[deepseek_key],
                     base_url="https://api.deepseek.com/v1",
                     preferred_model=ai.get("deepseek_model", "deepseek-chat"),
                     discover_models=True),
    ]
    return ai.get("active_provider", "gemini"), specs


def _build_debug(d: dict) -> DebugConfig:
    colors = dict(DEFAULT_COLORS)
    colors.update(d.get("colors", {}) or {})
    return DebugConfig(
        visual_mode=bool(d.get("visual_mode", False)),
        pause_after_navigation_seconds=float(d.get("pause_after_navigation_seconds", 0)),
        pause_before_scroll_seconds=float(d.get("pause_before_scroll_seconds", 0)),
        pause_after_scroll_seconds=float(d.get("pause_after_scroll_seconds", 0)),
        evidence_dir=d.get("evidence_dir", "debug"),
        log_first_n_jobs=int(d.get("log_first_n_jobs", 5)),
        colors=colors,
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def _validate_semantics(cfg: AppConfig) -> None:
    if not (0 <= cfg.ai.min_apply_score <= 100):
        raise ConfigError("apply.min_apply_score must be between 0 and 100")
    if not (0 <= cfg.profile_confidence_threshold <= 100):
        raise ConfigError("profiles.confidence_threshold must be between 0 and 100")
    if cfg.scan_interval_hours <= 0:
        raise ConfigError("scheduler.scan_interval_hours must be positive")
    if cfg.apply.max_applications_per_day <= 0:
        raise ConfigError("apply.max_applications_per_day must be positive")
    if cfg.rules.minimum_experience < 0:
        raise ConfigError("rules.minimum_experience cannot be negative")
    if cfg.browser.normalized_engine() not in ("chromium", "firefox", "webkit"):
        raise ConfigError("browser.engine must be chromium, firefox, or webkit")

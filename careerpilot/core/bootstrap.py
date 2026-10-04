"""First-run bootstrap / scaffolding.

A fresh clone ships `deployment_input/` (the real production files), a blank
`.env`, and templates under `examples/`. This module turns that into a
runnable layout:

* copy `deployment_input/config.yaml` to `config/config.yaml` if missing
* copy the six `deployment_input/profiles/` folders if missing
* otherwise create config and profiles from `examples/` if those are missing
* leave an existing `.env` alone (the clone already contains a blank one)
* create the runtime directories (logs, database, screenshots, reports)

It never overwrites an existing file, so it is safe to call on every startup.
Returns the list of human-readable actions taken (empty if nothing was needed).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .logging_setup import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG = Path("config/config.yaml")
EXAMPLE_CONFIG = Path("examples/config.example.yaml")
PROFILES_DIR = Path("profiles")
EXAMPLE_PROFILES = Path("examples/profiles")
PRODUCTION_EXAMPLE_CONFIG = Path("examples/config.production.example.yaml")
ENV_FILE = Path(".env")
EXAMPLE_ENV = Path("examples/.env.example")
DEPLOYMENT_INPUT = Path("deployment_input")
DEPLOYMENT_CONFIG = DEPLOYMENT_INPUT / "config.yaml"
DEPLOYMENT_PROFILES = DEPLOYMENT_INPUT / "profiles"
PRODUCTION_PROFILES = (
    "Default", "Leadership", "Digital_Workplace", "EUC", "GCC", "Contact_Centre",
)
PROFILE_FILES = (
    "profile.yaml", "keywords.yaml", "preferred_locations.yaml",
    "screening_answers.yaml", "resume.pdf",
)
RUNTIME_DIRS = (
    "logs", "database", "database/backups", "screenshots", "reports",
    "profiles_browser", "profiles_browser/linkedin", "profiles_browser/naukri",
    "cache", "cache/jobs", "documents", "debug",
)

# Example-only folder. Production uses the six career profiles; this one is
# kept under examples/profiles/ as a template and is not copied into profiles/.
SKIP_EXAMPLE_PROFILES = frozenset({"Infrastructure"})


def _copy_example_profiles(src: Path, dst: Path) -> None:
    """Copy example profile folders. Never touches a profiles/ tree that exists."""
    dst.mkdir(parents=True, exist_ok=False)
    for child in sorted(src.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in SKIP_EXAMPLE_PROFILES:
            continue
        shutil.copytree(child, dst / child.name)


def _resume_is_placeholder(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return True
    if len(data) <= 192:
        return True
    if len(data) < 1024 and b"stream" not in data:
        return True
    return False


_CONFIG_KEYS = {
    "application", "scheduler", "schedule", "database", "dashboard", "browser",
    "ai", "rules", "apply", "profiles", "logging", "documents", "telegram",
    "email", "candidate", "maintenance", "vision", "debug", "portals", "human",
}
_CANDIDATE_PLACEHOLDERS = {
    "", "your name", "your_email", "your_profile", "your company", "your title",
    "city, country", "+91-xxxxxxxxxx", "changeme", "todo", "tbd",
}


def _yaml_or_problem(path: Path, label: str) -> tuple[object, list[str]]:
    from .yaml_utils import load_yaml
    try:
        return load_yaml(path), []
    except Exception as exc:  # noqa: BLE001
        return None, [f"{label} is invalid YAML: {exc}"]


def validate_profile_dir(folder: Path) -> list[str]:
    """Return human-readable problems for one profile folder. Empty means OK."""
    problems: list[str] = []
    if not folder.is_dir():
        return [f"{folder} is missing"]
    for name in PROFILE_FILES:
        if not (folder / name).exists():
            problems.append(f"{folder.name}/{name} is missing")
    resume = folder / "resume.pdf"
    if resume.exists() and _resume_is_placeholder(resume):
        problems.append(
            f"{folder.name}/resume.pdf is the {resume.stat().st_size}-byte "
            "example placeholder, not a real resume")
    from .career_profile import (
        collect_answers, flatten_locations, split_keywords, _resume_filename,
    )
    profile_yaml = folder / "profile.yaml"
    meta: dict = {}
    if profile_yaml.exists():
        loaded, errs = _yaml_or_problem(profile_yaml, f"{folder.name}/profile.yaml")
        problems.extend(errs)
        if isinstance(loaded, dict):
            meta = loaded
        elif loaded is not None and not errs:
            problems.append(f"{folder.name}/profile.yaml must be a mapping")
        stated = str(meta.get("name") or "").strip()
        if stated and stated != folder.name:
            problems.append(
                f"{folder.name}/profile.yaml name is {stated!r}, expected {folder.name!r}")
        if not stated and not errs:
            problems.append(f"{folder.name}/profile.yaml is missing name")
        if meta:
            resume_name = _resume_filename(meta)
            if not (folder / resume_name).exists():
                problems.append(f"{folder.name} resume file {resume_name} is missing")
    keywords = folder / "keywords.yaml"
    if keywords.exists():
        loaded, errs = _yaml_or_problem(keywords, f"{folder.name}/keywords.yaml")
        problems.extend(errs)
        if isinstance(loaded, dict):
            required, preferred = split_keywords(loaded)
            if not required and not preferred:
                problems.append(f"{folder.name}/keywords.yaml has no keyword lists")
        elif loaded is not None and not errs:
            problems.append(f"{folder.name}/keywords.yaml must be a mapping")
    locations = folder / "preferred_locations.yaml"
    if locations.exists():
        loaded, errs = _yaml_or_problem(
            locations, f"{folder.name}/preferred_locations.yaml")
        problems.extend(errs)
        if not errs and not flatten_locations(loaded):
            problems.append(f"{folder.name}/preferred_locations.yaml has no locations")
    answers = folder / "screening_answers.yaml"
    if answers.exists():
        loaded, errs = _yaml_or_problem(
            answers, f"{folder.name}/screening_answers.yaml")
        problems.extend(errs)
        if not errs and not collect_answers(loaded if isinstance(loaded, dict) else {}):
            problems.append(f"{folder.name}/screening_answers.yaml has no answers")
    return problems


def validate_deployment_config(data: object, label: str = "deployment_input/config.yaml") -> list[str]:
    """Check a parsed production config against the fields the loader requires."""
    problems: list[str] = []
    if not isinstance(data, dict):
        return [f"{label} must be a mapping"]
    unknown = sorted(set(data) - _CONFIG_KEYS)
    if unknown:
        problems.append(f"{label} has unused top-level fields: {', '.join(unknown)}")
    cand = data.get("candidate")
    if not isinstance(cand, dict):
        problems.append(f"{label} has no candidate: section")
    else:
        for key in ("full_name", "email", "phone"):
            raw = cand.get(key)
            value = raw.strip() if isinstance(raw, str) else str(raw or "").strip()
            if value.lower() in _CANDIDATE_PLACEHOLDERS:
                problems.append(f"{label} candidate.{key} is missing or still an example")
    apply_cfg = data.get("apply") or {}
    if not isinstance(apply_cfg, dict):
        problems.append(f"{label} apply: must be a mapping")
        apply_cfg = {}
    if "min_apply_score" not in apply_cfg:
        problems.append(f"{label} is missing apply.min_apply_score")
    mode = str(apply_cfg.get("mode") or "")
    if not mode:
        problems.append(f"{label} apply.mode is missing (runtime stays dry_run)")
    elif mode not in ("dry_run", "approval", "auto", "live"):
        problems.append(
            f"{label} apply.mode {mode!r} is not dry_run, approval, or auto")
    profiles_cfg = data.get("profiles") or {}
    if not isinstance(profiles_cfg, dict) or not profiles_cfg.get("default"):
        problems.append(f"{label} must set profiles.default")
    else:
        default = str(profiles_cfg.get("default"))
        if default not in PRODUCTION_PROFILES:
            problems.append(
                f"{label} profiles.default {default!r} is not one of the six production profiles")
        folder = str(profiles_cfg.get("dir") or "profiles")
        if folder not in ("profiles", "./profiles"):
            problems.append(f"{label} profiles.dir must be profiles, got {folder!r}")
    ai = data.get("ai") or {}
    if isinstance(ai, dict):
        provider = str(ai.get("active_provider") or "")
        if provider and provider != "ollama":
            problems.append(
                f"{label} ai.active_provider is {provider!r}; this deployment uses ollama")
        providers = (ai.get("providers") or {}) if isinstance(ai.get("providers"), dict) else {}
        ollama = providers.get("ollama") or {}
        model = str((ollama or {}).get("preferred_model") or "")
        if provider == "ollama" and model and model != "qwen3:8b":
            problems.append(
                f"{label} ollama preferred_model is {model!r}; expected qwen3:8b")
    vision = data.get("vision") or {}
    if isinstance(vision, dict):
        vmodel = str(vision.get("model") or "")
        if vmodel and vmodel != "qwen3-vl:8b":
            problems.append(f"{label} vision.model is {vmodel!r}; expected qwen3-vl:8b")
    return problems


def validate_deployment_input(root: Path = DEPLOYMENT_INPUT) -> list[str]:
    """Check the shipped deployment_input tree. Empty list means it is usable."""
    problems: list[str] = []
    config = root / "config.yaml"
    profiles = root / "profiles"
    if not config.exists():
        problems.append(f"{config} is missing")
    else:
        loaded, errs = _yaml_or_problem(config, str(config))
        problems.extend(errs)
        if not errs:
            problems.extend(validate_deployment_config(loaded, str(config)))
    if not profiles.is_dir():
        problems.append(f"{profiles} is missing")
        return problems
    for name in PRODUCTION_PROFILES:
        problems.extend(validate_profile_dir(profiles / name))
    infra = profiles / "Infrastructure"
    if infra.exists():
        problems.append(
            "deployment_input/profiles/Infrastructure must not be a production profile")
    return problems


def install_deployment_input(config_path: Path) -> list[str]:
    """Copy deployment_input into config/ and profiles/ without overwriting."""
    actions: list[str] = []
    if not DEPLOYMENT_INPUT.exists():
        return actions
    problems = validate_deployment_input()
    for problem in problems:
        logger.warning("deployment_input: %s", problem)
        actions.append(f"deployment_input problem: {problem}")
    if DEPLOYMENT_CONFIG.exists() and not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEPLOYMENT_CONFIG, config_path)
        actions.append(f"installed {config_path} from {DEPLOYMENT_CONFIG}")
    elif config_path.exists() and DEPLOYMENT_CONFIG.exists():
        actions.append(f"left existing {config_path} in place")
    if DEPLOYMENT_PROFILES.is_dir():
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        for name in PRODUCTION_PROFILES:
            src = DEPLOYMENT_PROFILES / name
            dst = PROFILES_DIR / name
            if not src.is_dir():
                actions.append(f"deployment_input problem: profiles/{name}/ is missing")
                continue
            if dst.exists():
                actions.append(f"left existing profiles/{name}/ in place")
                continue
            shutil.copytree(src, dst)
            actions.append(f"installed profiles/{name}/ from deployment_input")
        for extra in sorted(p for p in DEPLOYMENT_PROFILES.iterdir() if p.is_dir()):
            if extra.name not in PRODUCTION_PROFILES:
                actions.append(f"did not install profiles/{extra.name}/")
    copied_problems = []
    if DEPLOYMENT_CONFIG.exists() and not config_path.exists():
        copied_problems.append(f"{config_path} was not installed")
    elif config_path.exists() and DEPLOYMENT_CONFIG.exists():
        _loaded, errs = _yaml_or_problem(config_path, str(config_path))
        copied_problems.extend(errs)
    for name in PRODUCTION_PROFILES:
        dest = PROFILES_DIR / name
        if DEPLOYMENT_PROFILES.is_dir() and (DEPLOYMENT_PROFILES / name).is_dir():
            copied_problems.extend(
                f"installed profiles/{name}: {item}"
                for item in validate_profile_dir(dest))
    if (PROFILES_DIR / "Infrastructure").exists() and DEPLOYMENT_INPUT.exists():
        copied_problems.append(
            "profiles/Infrastructure exists; production install must not create it")
    for problem in copied_problems:
        if f"deployment_input problem: {problem}" not in actions:
            logger.warning("after copy: %s", problem)
            actions.append(f"deployment_input problem: {problem}")
    return actions


def ensure_scaffold(config_path: str | Path = DEFAULT_CONFIG,
                    *, prefer_production: bool = False) -> list[str]:
    """Create missing runtime files/dirs. Idempotent. Never overwrites."""
    actions: list[str] = []
    config_path = Path(config_path)

    has_deploy = DEPLOYMENT_INPUT.exists()
    actions.extend(install_deployment_input(config_path))

    # 1. config/config.yaml  <-  deployment_input, else production or default example.
    # A present deployment_input tree is the production source. Do not fill gaps
    # with example placeholders.
    if not config_path.exists() and not has_deploy:
        example = None
        prod = PRODUCTION_EXAMPLE_CONFIG
        if prefer_production and prod.exists():
            example = prod
        elif EXAMPLE_CONFIG.exists():
            example = EXAMPLE_CONFIG
        if example is not None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, config_path)
            actions.append(f"created {config_path} from {example}")
        else:
            logger.warning("No %s and no example config to copy from",
                           config_path)

    # 2. profiles/  <-  examples/profiles/ only when deployment_input is absent.
    # Existing profiles/ is left completely alone, including real resumes.
    if not PROFILES_DIR.exists() and not has_deploy:
        if EXAMPLE_PROFILES.exists():
            _copy_example_profiles(EXAMPLE_PROFILES, PROFILES_DIR)
            actions.append(
                f"created {PROFILES_DIR}/ from {EXAMPLE_PROFILES}/ "
                f"(skipped {', '.join(sorted(SKIP_EXAMPLE_PROFILES))})")
        else:
            logger.warning("No %s/ and no %s/ to copy from",
                           PROFILES_DIR, EXAMPLE_PROFILES)

    # 3. .env is shipped blank. Recreate it only if a checkout deleted it.
    if not ENV_FILE.exists() and EXAMPLE_ENV.exists():
        shutil.copyfile(EXAMPLE_ENV, ENV_FILE)
        actions.append(f"created {ENV_FILE} from {EXAMPLE_ENV} "
                       "(fill in your real secrets)")

    # 4. runtime directories
    for name in RUNTIME_DIRS:
        d = Path(name)
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            actions.append(f"created {name}/")

    if actions:
        for a in actions:
            logger.info("bootstrap: %s", a)
    return actions


def protect_local_env() -> list[str]:
    """Keep a filled .env from being committed.

    Registers the clean filter named in .gitattributes and marks .env
    skip-worktree. Local edits stay on disk. Staging the file stores blanks.
    No-op outside a git checkout.
    """
    import subprocess
    import sys

    actions: list[str] = []
    if not Path(".git").exists() or not ENV_FILE.exists():
        return actions
    script = Path("scripts/git/blank_env_filter.py")
    if not script.exists():
        return actions
    clean = f"{sys.executable} {script.resolve()}"
    commands = [
        ["git", "config", "filter.careerpilot-blank-env.clean", clean],
        ["git", "config", "filter.careerpilot-blank-env.smudge", "cat"],
        ["git", "config", "filter.careerpilot-blank-env.required", "true"],
        ["git", "update-index", "--skip-worktree", ".env"],
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            logger.warning("env protection: %s (%s)", " ".join(cmd), exc)
            actions.append(f"env protection failed: {' '.join(cmd)}")
            return actions
    actions.append("protected .env (local secrets are not committed)")
    return actions

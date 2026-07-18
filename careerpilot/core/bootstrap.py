"""First-run bootstrap / scaffolding for the production data layout.

The Git repository ships templates under ``data/`` (``.env.example``,
``data/config/config.example.yaml``, ``data/profiles/Sample_Candidate/``) plus
legacy root copies (``config.example.yaml``, ``profiles.example/``,
``.env.example``).

Real user files live under the **data root** (see ``careerpilot.core.paths``):

* ``<data_root>/config/config.yaml``
* ``<data_root>/.env``
* ``<data_root>/profiles/``
* runtime dirs (logs, database, browser, reports, …)

Legacy single-folder mode (data root == app root) is still supported.

Never overwrites existing user files. Returns actions taken.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .logging_setup import get_logger
from .paths import DATA_SUBDIRS, get_layout

logger = get_logger(__name__)

# Back-compat alias for tests / scripts that imported RUNTIME_DIRS from here.
RUNTIME_DIRS = tuple(DATA_SUBDIRS) + (
    "profiles_browser",
    "profiles_browser/linkedin",
    "profiles_browser/naukri",
)

# Example → production renames inside a Sample_Candidate template pack.
_PROFILE_RENAMES = (
    ("profile.example.yaml", "profile.yaml"),
    ("keywords.example.yaml", "keywords.yaml"),
    ("preferred_locations.example.yaml", "preferred_locations.yaml"),
    ("screening_answers.example.yaml", "screening_answers.yaml"),
    ("cover_letter.example.md", "cover_letter.md"),
)


def _first_existing(*candidates: Path) -> Path | None:
    for p in candidates:
        if p is not None and p.exists():
            return p
    return None


def _materialize_sample_profile(src: Path, dest: Path) -> list[str]:
    """Copy Sample_Candidate templates and rename *.example.* → live names."""
    actions: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name == "README.md":
            # Keep README as documentation inside the live folder.
            target = dest / child.name
            if not target.exists():
                shutil.copy2(child, target)
                actions.append(f"created {target}")
            continue
        if child.is_dir():
            continue
        # Skip example names here; handled via renames below.
        if ".example." in child.name or child.name.endswith(".example"):
            continue
        # Non-example assets (e.g. resume.pdf)
        target = dest / child.name
        if not target.exists():
            shutil.copy2(child, target)
            actions.append(f"created {target}")

    for src_name, dest_name in _PROFILE_RENAMES:
        s = src / src_name
        d = dest / dest_name
        if s.exists() and not d.exists():
            shutil.copy2(s, d)
            actions.append(f"created {d} from {src_name}")
    # Wire cover_letter into profile.yaml when the markdown letter was created
    profile = dest / "profile.yaml"
    cover = dest / "cover_letter.md"
    if profile.exists() and cover.exists():
        try:
            text = profile.read_text(encoding="utf-8")
            if "cover_letter: cover_letter.md" not in text:
                text = text.replace(
                    "# cover_letter: cover_letter.md",
                    "cover_letter: cover_letter.md")
                if "cover_letter:" not in text:
                    text = text.rstrip() + "\ncover_letter: cover_letter.md\n"
                profile.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return actions


def ensure_scaffold(config_path: str | Path | None = None,
                    *, prefer_production: bool = False,
                    env_path: str | Path | None = None) -> list[str]:
    """Create missing data-root files/dirs from shipped examples. Idempotent."""
    actions: list[str] = []
    layout = get_layout()
    app = layout.app_root
    templates = app / "data"  # shipped template tree inside the Git repo

    created = layout.ensure_dirs()
    for c in created:
        actions.append(f"created {c}")

    # Also ensure legacy sibling dirs when running in-repo (backward compat).
    if layout.data_root == layout.app_root:
        for name in ("profiles_browser/linkedin", "profiles_browser/naukri"):
            d = layout.data_root / name
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                actions.append(f"created {d}")

    cfg_dest = Path(config_path) if config_path else layout.config_yaml
    explicit_config = config_path is not None
    # Prefer data/config/config.yaml; fall back to legacy config/config.yaml
    # only when the caller did not pass an explicit path and data root == app.
    if (not explicit_config and not cfg_dest.exists()
            and layout.data_root == layout.app_root):
        legacy = app / "config" / "config.yaml"
        if legacy.exists():
            cfg_dest = legacy

    example = None
    if prefer_production:
        example = _first_existing(
            app / "config.production.example.yaml",
            templates / "config" / "config.example.yaml",
            app / "config.example.yaml",
        )
    else:
        example = _first_existing(
            templates / "config" / "config.example.yaml",
            app / "config.example.yaml",
            app / "config.production.example.yaml",
        )

    if not cfg_dest.exists() and example is not None:
        cfg_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, cfg_dest)
        # Rewrite legacy profiles_browser → browser in a fresh production copy.
        try:
            text = cfg_dest.read_text(encoding="utf-8")
            text2 = text.replace("profiles_path: profiles_browser",
                                 "profiles_path: browser")
            if text2 != text:
                cfg_dest.write_text(text2, encoding="utf-8")
        except OSError:
            pass
        actions.append(f"created {cfg_dest} from {example}")
    elif not cfg_dest.exists():
        logger.warning("No config example found to scaffold %s", cfg_dest)

    # Profiles — prefer nested Murahari_M pack, then Sample_Candidate, then profiles.example/
    profiles_dest = layout.profiles_dir
    has_live = any(profiles_dest.glob("*/profile.yaml")) if profiles_dest.exists() else False
    has_nested = any(profiles_dest.glob("*/*/profile.yaml")) if profiles_dest.exists() else False
    sample_nested = templates / "profiles" / "Murahari_M"
    sample_src = templates / "profiles" / "Sample_Candidate"
    example_profiles = app / "profiles.example"

    if not has_live and not has_nested:
        if sample_nested.is_dir() and (sample_nested / "General" / "profile.yaml").exists():
            dest = profiles_dest / "Murahari_M"
            if not dest.exists():
                shutil.copytree(sample_nested, dest)
                actions.append(f"created {dest}/ from data/profiles/Murahari_M/")
        elif sample_src.is_dir() and (sample_src / "profile.example.yaml").exists():
            dest = profiles_dest / "Sample_Candidate"
            if not (dest / "profile.yaml").exists():
                actions.extend(_materialize_sample_profile(sample_src, dest))
        elif example_profiles.exists():
            if profiles_dest.exists() and not any(profiles_dest.iterdir()):
                profiles_dest.rmdir()
            if not profiles_dest.exists():
                shutil.copytree(example_profiles, profiles_dest)
                actions.append(f"created {profiles_dest}/ from profiles.example/")
            else:
                for child in example_profiles.iterdir():
                    dest = profiles_dest / child.name
                    if child.is_dir() and not dest.exists():
                        shutil.copytree(child, dest)
                        actions.append(f"created {dest}/")

    # .env
    env_dest = Path(env_path) if env_path else layout.env_file
    example_env = _first_existing(
        templates / ".env.example",
        app / ".env.example",
    )
    if not env_dest.exists() and example_env is not None:
        shutil.copyfile(example_env, env_dest)
        actions.append(f"created {env_dest} from {example_env.name} (add your real keys)")

    # README marker inside live data root (not the templates tree)
    readme = layout.data_root / "README.md"
    if (not readme.exists() and layout.data_root != layout.app_root
            and layout.data_root.resolve() != templates.resolve()):
        readme.write_text(
            "# CareerPilot data root\n\n"
            "This folder holds **all user-specific and runtime data**.\n"
            "The Git repository (`app/`) must never contain these files.\n\n"
            "Templates shipped with the app live in `app/data/` "
            "(see that README).\n"
            "Docs: `app/docs/DATA_STRUCTURE.md`, `app/docs/USER_FILES.md`.\n",
            encoding="utf-8")
        actions.append(f"created {readme}")

    if actions:
        for a in actions:
            logger.info("bootstrap: %s", a)
    return actions

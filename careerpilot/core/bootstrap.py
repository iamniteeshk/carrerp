"""First-run bootstrap / scaffolding for the production data layout.

The Git repository ships only examples (``config.example.yaml``,
``profiles.example/``, ``.env.example``). Real user files live under the
**data root** (see ``careerpilot.core.paths``):

* ``data/config/config.yaml``
* ``data/.env``
* ``data/profiles/``
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


def ensure_scaffold(config_path: str | Path | None = None,
                    *, prefer_production: bool = False,
                    env_path: str | Path | None = None) -> list[str]:
    """Create missing data-root files/dirs from shipped examples. Idempotent."""
    actions: list[str] = []
    layout = get_layout()
    app = layout.app_root

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
    prod = app / "config.production.example.yaml"
    default_ex = app / "config.example.yaml"
    if prefer_production and prod.exists():
        example = prod
    elif default_ex.exists():
        example = default_ex

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
        actions.append(f"created {cfg_dest} from {example.name}")
    elif not cfg_dest.exists():
        logger.warning("No config example found to scaffold %s", cfg_dest)

    # Profiles
    profiles_dest = layout.profiles_dir
    example_profiles = app / "profiles.example"
    if not any(profiles_dest.glob("*/profile.yaml")) and example_profiles.exists():
        if profiles_dest.exists() and not any(profiles_dest.iterdir()):
            profiles_dest.rmdir()
        if not profiles_dest.exists():
            shutil.copytree(example_profiles, profiles_dest)
            actions.append(f"created {profiles_dest}/ from profiles.example/")
        else:
            # Copy missing profile folders only
            for child in example_profiles.iterdir():
                dest = profiles_dest / child.name
                if child.is_dir() and not dest.exists():
                    shutil.copytree(child, dest)
                    actions.append(f"created {dest}/")

    # .env
    env_dest = Path(env_path) if env_path else layout.env_file
    example_env = app / ".env.example"
    if not env_dest.exists() and example_env.exists():
        shutil.copyfile(example_env, env_dest)
        actions.append(f"created {env_dest} from .env.example (add your real keys)")

    # README marker inside data root
    readme = layout.data_root / "README.md"
    if not readme.exists() and layout.data_root != layout.app_root:
        readme.write_text(
            "# CareerPilot data root\n\n"
            "This folder holds **all user-specific and runtime data**.\n"
            "The Git repository (`app/`) must never contain these files.\n\n"
            "See `app/docs/DATA_STRUCTURE.md`.\n",
            encoding="utf-8")
        actions.append(f"created {readme}")

    if actions:
        for a in actions:
            logger.info("bootstrap: %s", a)
    return actions

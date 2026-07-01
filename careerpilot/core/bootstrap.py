"""First-run bootstrap / scaffolding.

A fresh clone ships only example files (`config.example.yaml`, `profiles.example/`,
`.env.example`) because the real ones are gitignored. This module turns a fresh
clone into a runnable layout automatically, so the project is clone-and-run:

* create `config/config.yaml` from `config.example.yaml` if missing
* create `profiles/` from `profiles.example/` if missing
* create `.env` from `.env.example` if missing
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
EXAMPLE_CONFIG = Path("config.example.yaml")
PROFILES_DIR = Path("profiles")
EXAMPLE_PROFILES = Path("profiles.example")
ENV_FILE = Path(".env")
EXAMPLE_ENV = Path(".env.example")
RUNTIME_DIRS = ("logs", "database", "screenshots", "reports", "profiles_browser")


def ensure_scaffold(config_path: str | Path = DEFAULT_CONFIG) -> list[str]:
    """Create missing runtime files/dirs from shipped examples. Idempotent."""
    actions: list[str] = []
    config_path = Path(config_path)

    # 1. config/config.yaml  <-  config.example.yaml
    if not config_path.exists():
        if EXAMPLE_CONFIG.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(EXAMPLE_CONFIG, config_path)
            actions.append(f"created {config_path} from {EXAMPLE_CONFIG}")
        else:
            logger.warning("No %s and no %s to copy from",
                           config_path, EXAMPLE_CONFIG)

    # 2. profiles/  <-  profiles.example/
    if not PROFILES_DIR.exists():
        if EXAMPLE_PROFILES.exists():
            shutil.copytree(EXAMPLE_PROFILES, PROFILES_DIR)
            actions.append(f"created {PROFILES_DIR}/ from {EXAMPLE_PROFILES}/")
        else:
            logger.warning("No %s/ and no %s/ to copy from",
                           PROFILES_DIR, EXAMPLE_PROFILES)

    # 3. .env  <-  .env.example
    if not ENV_FILE.exists() and EXAMPLE_ENV.exists():
        shutil.copyfile(EXAMPLE_ENV, ENV_FILE)
        actions.append(f"created {ENV_FILE} from {EXAMPLE_ENV} "
                       "(add your real keys)")

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
